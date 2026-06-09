#!/usr/bin/env python3
"""prompt-improver.py — Eval-flywheel prompt patch generator.

Closes the eval-flywheel loop by auto-generating and applying prompt patches
based on low-scoring dimensions from the LLM-as-a-Judge session_judgment table.

Database: ~/gitlab/products/cubeos/claude-context/gateway.db
Config:   config/prompt-patches.json  (relative to repo root)

Usage modes:
    --analyze   Show current dimension averages + which patches would fire (dry run)
    --apply     Generate patches and write to config/prompt-patches.json
    --report    Show patch history with before/after scores
    --promote   Check if react_v2 should be promoted over react_v1
    --expire    Remove patches older than 30 days

n8n Integration Path (not auto-wired — do it manually):
    The Query Knowledge SSH node can append active patches to its output:
        echo "PROMPT_PATCHES:$(cat /app/claude-gateway/config/prompt-patches.json 2>/dev/null || echo '[]')"
    Then in the Build Prompt Code node, parse and inject:
        var patchMatch = kbRaw.match(/PROMPT_PATCHES:(.*)/);
        if (patchMatch) {
            var patches = JSON.parse(patchMatch[1]);
            var activePatches = patches.filter(p => p.active);
            // Inject each active patch instruction into the prompt
        }
"""

import sqlite3
import json
import os
import sys
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.expanduser('~/gitlab/products/cubeos/claude-context/gateway.db')
PATCH_FILE = os.path.join(REPO_ROOT, 'config', 'prompt-patches.json')

# Dimension -> patch rule.  Threshold is the avg score below which
# a patch instruction gets generated.
PATCH_RULES = {
    'investigation_quality': {
        'threshold': 3.5,
        'instruction': (
            'INVESTIGATION REQUIREMENT: You MUST SSH to the affected device '
            'and run at least 2 diagnostic commands (e.g., systemctl status, '
            'free -h, df -h, docker ps, pct list) before drawing any '
            'conclusion. Do NOT guess or infer — verify with evidence.'
        ),
        'category': 'investigation',
    },
    'evidence_based': {
        'threshold': 3.5,
        'instruction': (
            'EVIDENCE REQUIREMENT: Every factual claim in your response MUST '
            'cite a specific command output, metric value, or API response. '
            'Format: "Based on [command output showing X], the root cause is Y."'
        ),
        'category': 'evidence',
    },
    'actionability': {
        'threshold': 3.5,
        'instruction': (
            'ACTIONABILITY REQUIREMENT: Remediation plans must include exact '
            'commands to run, specific config changes, and expected outcomes. '
            'Avoid vague suggestions like "check the logs" — instead specify '
            'which log file and what pattern to grep for.'
        ),
        'category': 'actionability',
    },
    'safety_compliance': {
        'threshold': 3.0,
        'instruction': (
            'SAFETY ENFORCEMENT: NEVER execute infrastructure changes without '
            'presenting a [POLL] first. Always present 2-3 options with risk '
            'levels. Wait for human approval before any modification.'
        ),
        'category': 'safety',
    },
    'completeness': {
        'threshold': 3.5,
        'instruction': (
            'COMPLETENESS CHECKLIST: Your response MUST include: '
            '(1) CONFIDENCE: X.XX score, (2) Root cause identification, '
            '(3) Evidence citations, (4) Remediation plan with [POLL] options, '
            '(5) Risk assessment.'
        ),
        'category': 'completeness',
    },
}

# Minimum number of scored sessions to consider a dimension's average valid
MIN_SAMPLES = 3

# Patch expiry in days
PATCH_EXPIRY_DAYS = 30

# Variant promotion: v2 must beat v1 by this margin with at least this many
# samples on each side.
PROMOTION_MARGIN = 0.3
PROMOTION_MIN_SAMPLES = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg):
    """Log to stderr."""
    print(f'[prompt-improver] {msg}', file=sys.stderr)


def connect_db():
    """Open a read-only connection to gateway.db."""
    if not os.path.exists(DB_PATH):
        log(f'ERROR: database not found at {DB_PATH}')
        sys.exit(1)
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_patches():
    """Load the current patch config (or empty list)."""
    if not os.path.exists(PATCH_FILE):
        return []
    with open(PATCH_FILE, 'r') as f:
        return json.load(f)


def save_patches(patches):
    """Write patches to config file."""
    os.makedirs(os.path.dirname(PATCH_FILE), exist_ok=True)
    with open(PATCH_FILE, 'w') as f:
        json.dump(patches, f, indent=2)
        f.write('\n')
    log(f'Wrote {len(patches)} patches to {PATCH_FILE}')


def now_iso():
    """Current UTC time in ISO-8601."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------------------
# Core: compute dimension averages
# ---------------------------------------------------------------------------

def compute_dimension_averages(conn):
    """Return dict of {dimension: (avg, count)} for the last 30 days.

    Only includes rows where the dimension score > 0 (valid).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
    results = {}
    for dim in PATCH_RULES:
        row = conn.execute(
            f'SELECT AVG({dim}) AS avg_score, COUNT(*) AS cnt '
            f'FROM session_judgment '
            f'WHERE {dim} > 0 AND judged_at >= ?',
            (cutoff,)
        ).fetchone()
        avg = row['avg_score'] if row['avg_score'] is not None else 0.0
        cnt = row['cnt'] if row['cnt'] else 0
        results[dim] = (round(avg, 2), cnt)
    return results


# ---------------------------------------------------------------------------
# --analyze
# ---------------------------------------------------------------------------

def cmd_analyze(conn):
    """Show dimension averages and which patches would fire."""
    avgs = compute_dimension_averages(conn)

    print('=' * 70)
    print('PROMPT IMPROVER — Dimension Analysis (last 30 days)')
    print('=' * 70)
    print()
    print(f'{"Dimension":<25} {"Avg":>6} {"N":>5} {"Threshold":>10} {"Action":>12}')
    print('-' * 70)

    patches_needed = []
    for dim, rule in PATCH_RULES.items():
        avg, cnt = avgs[dim]
        threshold = rule['threshold']
        if cnt < MIN_SAMPLES:
            action = 'SKIP (n<3)'
        elif avg < threshold:
            action = 'PATCH'
            patches_needed.append(dim)
        else:
            action = 'OK'
        print(f'{dim:<25} {avg:>6.2f} {cnt:>5} {threshold:>10.1f} {action:>12}')

    print()
    if patches_needed:
        print(f'Patches needed: {len(patches_needed)}')
        for dim in patches_needed:
            print(f'  - {dim} ({PATCH_RULES[dim]["category"]})')
    else:
        print('All dimensions above threshold — no patches needed.')

    # Also show existing active patches
    patches = load_patches()
    active = [p for p in patches if p.get('active', False)]
    if active:
        print()
        print(f'Active patches in config: {len(active)}')
        for p in active:
            exp = p.get('expires_at', 'never')
            print(f'  - {p["dimension"]} (applied {p["applied_at"]}, expires {exp})')

    print()
    return patches_needed


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------

def cmd_apply(conn):
    """Generate patches for low-scoring dimensions and write to config."""
    avgs = compute_dimension_averages(conn)
    patches = load_patches()

    # Build set of dimensions that already have active patches
    active_dims = {p['dimension'] for p in patches if p.get('active', False)}

    new_count = 0
    for dim, rule in PATCH_RULES.items():
        avg, cnt = avgs[dim]

        if cnt < MIN_SAMPLES:
            log(f'{dim}: skipping (only {cnt} samples, need {MIN_SAMPLES})')
            continue

        if avg >= rule['threshold']:
            log(f'{dim}: avg {avg:.2f} >= threshold {rule["threshold"]} — no patch needed')
            continue

        if dim in active_dims:
            log(f'{dim}: active patch already exists — skipping')
            continue

        # Generate patch
        applied_at = now_iso()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=PATCH_EXPIRY_DAYS)).strftime('%Y-%m-%dT%H:%M:%SZ')

        patch = {
            'dimension': dim,
            'category': rule['category'],
            'instruction': rule['instruction'],
            'applied_at': applied_at,
            'score_before': avg,
            'score_after': None,
            'active': True,
            'expires_at': expires_at,
        }
        patches.append(patch)
        new_count += 1
        log(f'{dim}: PATCH GENERATED (avg={avg:.2f}, threshold={rule["threshold"]})')

    if new_count > 0:
        save_patches(patches)
        print(f'Applied {new_count} new patches. Total patches in config: {len(patches)}')
    else:
        print('No new patches needed.')

    return new_count


# ---------------------------------------------------------------------------
# --report
# ---------------------------------------------------------------------------

def cmd_report(conn):
    """Show patch history with before/after scores."""
    patches = load_patches()
    avgs = compute_dimension_averages(conn)

    print('=' * 78)
    print('PROMPT IMPROVER — Patch Report')
    print('=' * 78)

    if not patches:
        print('\nNo patches in history.')
        return

    print()
    print(f'{"Dimension":<25} {"Before":>7} {"After":>7} {"Delta":>7} {"Status":>10} {"Applied":<22}')
    print('-' * 78)

    for p in patches:
        dim = p['dimension']
        before = p.get('score_before', 0) or 0
        # Compute current average as "after"
        after, cnt = avgs.get(dim, (0.0, 0))

        # Update score_after in-place for persistence
        p['score_after'] = after

        delta = after - before
        delta_str = f'{delta:+.2f}' if delta != 0 else '  0.00'

        if not p.get('active', False):
            status = 'EXPIRED'
        elif cnt < MIN_SAMPLES:
            status = 'PENDING'
            delta_str = '   N/A'
        else:
            status = 'ACTIVE'

        applied = p.get('applied_at', 'unknown')[:19]
        print(f'{dim:<25} {before:>7.2f} {after:>7.2f} {delta_str:>7} {status:>10} {applied:<22}')

    # Persist updated score_after values
    save_patches(patches)
    print()


# ---------------------------------------------------------------------------
# --promote
# ---------------------------------------------------------------------------

def cmd_promote(conn):
    """Check if react_v2 should be promoted over react_v1."""
    print('=' * 70)
    print('PROMPT IMPROVER — Variant Promotion Check')
    print('=' * 70)
    print()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')

    rows = conn.execute(
        'SELECT s.prompt_variant, '
        '       COUNT(*) AS cnt, '
        '       AVG(j.overall_score) AS avg_score, '
        '       AVG(j.investigation_quality) AS avg_inv, '
        '       AVG(j.evidence_based) AS avg_evi, '
        '       AVG(j.actionability) AS avg_act, '
        '       AVG(j.safety_compliance) AS avg_saf, '
        '       AVG(j.completeness) AS avg_com '
        'FROM session_judgment j '
        'JOIN session_log s ON j.issue_id = s.issue_id '
        'WHERE j.overall_score > 0 '
        '  AND s.prompt_variant != \'\' '
        '  AND j.judged_at >= ? '
        'GROUP BY s.prompt_variant',
        (cutoff,)
    ).fetchall()

    if not rows:
        print('No variant data found (no sessions with both judgment and prompt_variant).')
        print()
        print('This happens when session_log.prompt_variant is empty or the join')
        print('on issue_id finds no matches. Check that the Runner sets prompt_variant.')
        return

    variants = {}
    for r in rows:
        variants[r['prompt_variant']] = {
            'count': r['cnt'],
            'avg_score': round(r['avg_score'], 2),
            'avg_inv': round(r['avg_inv'], 2),
            'avg_evi': round(r['avg_evi'], 2),
            'avg_act': round(r['avg_act'], 2),
            'avg_saf': round(r['avg_saf'], 2),
            'avg_com': round(r['avg_com'], 2),
        }

    print(f'{"Variant":<15} {"N":>5} {"Overall":>8} {"Invest":>7} {"Evid":>7} {"Action":>7} {"Safety":>7} {"Compl":>7}')
    print('-' * 70)
    for v, d in sorted(variants.items()):
        print(f'{v:<15} {d["count"]:>5} {d["avg_score"]:>8.2f} {d["avg_inv"]:>7.2f} '
              f'{d["avg_evi"]:>7.2f} {d["avg_act"]:>7.2f} {d["avg_saf"]:>7.2f} {d["avg_com"]:>7.2f}')

    print()

    v1 = variants.get('react_v1')
    v2 = variants.get('react_v2')

    if not v1 and not v2:
        print('Neither react_v1 nor react_v2 found in data.')
        return

    if not v2:
        print('react_v2 has no scored sessions yet — promotion not possible.')
        return

    if not v1:
        print('react_v1 has no scored sessions — nothing to compare against.')
        return

    # Check sample sizes
    if v1['count'] < PROMOTION_MIN_SAMPLES or v2['count'] < PROMOTION_MIN_SAMPLES:
        needed_v1 = max(0, PROMOTION_MIN_SAMPLES - v1['count'])
        needed_v2 = max(0, PROMOTION_MIN_SAMPLES - v2['count'])
        print(f'Insufficient samples for promotion decision.')
        print(f'  react_v1: {v1["count"]}/{PROMOTION_MIN_SAMPLES}' +
              (f' (need {needed_v1} more)' if needed_v1 else ' OK'))
        print(f'  react_v2: {v2["count"]}/{PROMOTION_MIN_SAMPLES}' +
              (f' (need {needed_v2} more)' if needed_v2 else ' OK'))
        return

    delta = v2['avg_score'] - v1['avg_score']
    print(f'Delta (v2 - v1): {delta:+.2f}  (threshold: +{PROMOTION_MARGIN:.2f})')
    print()

    if delta > PROMOTION_MARGIN:
        print('RECOMMENDATION: PROMOTE react_v2')
        print(f'  react_v2 ({v2["avg_score"]:.2f}) beats react_v1 ({v1["avg_score"]:.2f}) '
              f'by {delta:.2f} (> {PROMOTION_MARGIN:.2f})')
        print()
        print('  Action: Change Build Prompt hash threshold from 50 to 70')
        print('  This shifts more sessions to react_v2.')
        print('  NOTE: Requires human approval — not auto-applied.')
    elif delta < -PROMOTION_MARGIN:
        print('WARNING: react_v2 is UNDERPERFORMING react_v1')
        print(f'  react_v1 ({v1["avg_score"]:.2f}) beats react_v2 ({v2["avg_score"]:.2f}) '
              f'by {abs(delta):.2f}')
        print()
        print('  Consider rolling back: set hash threshold to 30 or 0.')
    else:
        print('NO ACTION: Variants are within noise margin.')
        print(f'  react_v1: {v1["avg_score"]:.2f}, react_v2: {v2["avg_score"]:.2f}, '
              f'delta: {delta:+.2f}')


# ---------------------------------------------------------------------------
# --expire
# ---------------------------------------------------------------------------

def cmd_expire():
    """Remove (deactivate) patches older than 30 days."""
    patches = load_patches()
    now = datetime.now(timezone.utc)
    expired = 0

    for p in patches:
        if not p.get('active', False):
            continue
        exp_str = p.get('expires_at')
        if not exp_str:
            continue
        try:
            exp_dt = datetime.fromisoformat(exp_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue

        if now >= exp_dt:
            p['active'] = False
            expired += 1
            log(f'{p["dimension"]}: expired (was applied {p["applied_at"]})')

    if expired > 0:
        save_patches(patches)
        print(f'Expired {expired} patches.')
    else:
        print('No patches eligible for expiry.')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print('Usage: prompt-improver.py [--analyze|--apply|--report|--promote|--expire]')
        sys.exit(1)

    mode = sys.argv[1]

    if mode == '--analyze':
        conn = connect_db()
        cmd_analyze(conn)
        conn.close()
    elif mode == '--apply':
        conn = connect_db()
        cmd_apply(conn)
        conn.close()
    elif mode == '--report':
        conn = connect_db()
        cmd_report(conn)
        conn.close()
    elif mode == '--promote':
        conn = connect_db()
        cmd_promote(conn)
        conn.close()
    elif mode == '--expire':
        cmd_expire()
    else:
        print(f'Unknown mode: {mode}')
        print('Usage: prompt-improver.py [--analyze|--apply|--report|--promote|--expire]')
        sys.exit(1)


if __name__ == '__main__':
    main()
