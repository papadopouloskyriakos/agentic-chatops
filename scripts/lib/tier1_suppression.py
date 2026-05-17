"""Tier 1 suppression decision library.

Three phases, all read-only against existing tables:

  Phase 1 — open-issue dedup
    If the same (hostname, rule_name) was triaged within the last
    RECENT_WINDOW_MIN minutes AND its YouTrack issue is still open,
    suppress this triage as a duplicate. Counter-bumps the existing
    issue with a comment but does not spawn a new Tier 2 session.

  Phase 2 — known-transient knowledge match
    If incident_knowledge has a row for the same (hostname, alert_rule)
    within KNOWLEDGE_WINDOW_DAYS, severity != critical, and the row's
    tags/resolution contains a transient-pattern keyword (transient,
    flap, self-resolved, recovered), suppress as a known recurring
    pattern. Confidence ≥ 0.7 required.

  Phase 3 — active-memory operator rules
    If openclaw_memory has a row with category='triage-rule', a key
    matching the (hostname, rule_name) pair, and value starting with
    'suppress:', suppress with the operator-supplied reason.

Safety rails:
  - FORCE_ESCALATE=true short-circuits ALL phases.
  - severity == 'critical' is allowed for Phase 1 dedup (the parent
    incident IS the open work) but disallowed for Phases 2 and 3.
  - Any exception fails OPEN — i.e. returns ESCALATE. The deterministic
    shell loses nothing when this library misbehaves.

The CLI entry point at the bottom is what the bash triage scripts call.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional


RECENT_WINDOW_MIN_DEFAULT = 360            # 6 hours
KNOWLEDGE_WINDOW_DAYS_DEFAULT = 7
KNOWN_TRANSIENT_KEYWORDS = (
    "transient", "flap", "self-resolved", "self resolved",
    "recovered", "auto-cleared", "self-cleared",
)
KNOWN_TRANSIENT_MIN_CONFIDENCE = 0.7


@dataclass
class SuppressionDecision:
    outcome: str                       # "escalate" | "dedup" | "resolved-knownpattern" | "resolved-active-memory"
    phase: str                         # "none" | "phase1-dedup" | "phase2-knownpattern" | "phase3-active-memory"
    reason: str                        # human-readable explanation
    existing_issue_id: str = ""        # populated for phase1 (the parent issue)
    comment_text: str = ""             # text to post on the YT issue (parent for phase1, current for 2/3)
    confidence: float = 0.0            # suppression confidence (heuristic)
    signals: dict = field(default_factory=dict)  # debug payload for event_log

    def is_suppression(self) -> bool:
        return self.outcome != "escalate"

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


# ─────────────────────────────────────────────────────────────────────
# Phase 1 — open-issue dedup
# ─────────────────────────────────────────────────────────────────────
def _scan_recent_triage_log(triage_log_path: str, hostname: str, rule_name: str,
                            now_utc: datetime.datetime, window_min: int) -> list[tuple]:
    """Return [(ts, outcome, issue_id), ...] for matching (host, rule) inside window.

    Newest-first. Returns empty list on file-missing / parse failure.
    """
    cutoff = now_utc - datetime.timedelta(minutes=window_min)
    matches: list[tuple] = []
    try:
        with open(triage_log_path, "r") as fh:
            for line in fh:
                parts = line.strip().split("|")
                if len(parts) < 5:
                    continue
                if parts[1] != hostname or parts[2] != rule_name:
                    continue
                try:
                    ts = datetime.datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                outcome = parts[4]
                issue_id = parts[7] if len(parts) >= 8 else ""
                matches.append((ts, outcome, issue_id))
    except FileNotFoundError:
        return []
    matches.sort(key=lambda m: m[0], reverse=True)
    return matches


def check_phase1_dedup(hostname: str, rule_name: str, severity: str,
                       triage_log_path: str, current_issue_id: str,
                       now_utc: datetime.datetime, window_min: int,
                       yt_issue_open_checker: Optional[Callable[[str], bool]]) -> SuppressionDecision:
    """Return SuppressionDecision (outcome=dedup) or pass-through (outcome=escalate)."""
    recent = _scan_recent_triage_log(triage_log_path, hostname, rule_name, now_utc, window_min)
    # Find the most recent escalated entry that has an issue_id different from the current one
    candidates = [
        (ts, oc, iid) for (ts, oc, iid) in recent
        if oc == "escalated" and iid and iid != current_issue_id
    ]
    if not candidates:
        return SuppressionDecision(
            outcome="escalate", phase="none",
            reason="phase1: no prior escalated entry in window",
            signals={"window_min": window_min, "recent_count": len(recent)},
        )

    ts_parent, _, parent_id = candidates[0]
    # Confirm the parent issue is still open. Fail-OPEN (assume open) if checker errors.
    if yt_issue_open_checker is not None:
        try:
            is_open = bool(yt_issue_open_checker(parent_id))
        except Exception as exc:
            return SuppressionDecision(
                outcome="escalate", phase="none",
                reason=f"phase1: yt_open_checker failed ({type(exc).__name__}) — failing open",
                existing_issue_id=parent_id,
                signals={"window_min": window_min, "error": str(exc)[:200]},
            )
        if not is_open:
            return SuppressionDecision(
                outcome="escalate", phase="none",
                reason=f"phase1: parent issue {parent_id} is closed — escalating fresh",
                existing_issue_id=parent_id,
                signals={"window_min": window_min, "parent_state": "closed"},
            )

    age_min = (now_utc - ts_parent).total_seconds() / 60.0
    comment = (
        f"Tier 1 deduplicated repeat alert at "
        f"{now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}. Same (host, rule) was already "
        f"triaged and escalated {age_min:.1f} min ago in this issue. No new Tier 2 "
        f"session spawned. Reason: phase1-dedup, window={window_min}m."
    )
    return SuppressionDecision(
        outcome="dedup", phase="phase1-dedup",
        reason=f"phase1: parent {parent_id} escalated {age_min:.1f}m ago, still open",
        existing_issue_id=parent_id,
        comment_text=comment,
        confidence=0.95,
        signals={
            "window_min": window_min,
            "parent_age_min": round(age_min, 1),
            "parent_outcome_count": len(candidates),
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Phase 2 — known-transient knowledge match
# ─────────────────────────────────────────────────────────────────────
def check_phase2_knownpattern(hostname: str, rule_name: str, severity: str,
                              db_conn: sqlite3.Connection,
                              now_utc: datetime.datetime,
                              window_days: int) -> SuppressionDecision:
    if severity == "critical":
        return SuppressionDecision(
            outcome="escalate", phase="none",
            reason="phase2: severity=critical never auto-resolved by knowledge match",
            signals={"severity": severity},
        )
    cutoff_iso = (now_utc - datetime.timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = db_conn.execute(
            """SELECT id, root_cause, resolution, confidence, tags, created_at, issue_id
               FROM incident_knowledge
               WHERE hostname = ? AND alert_rule = ?
                 AND created_at >= ?
                 AND confidence >= ?
               ORDER BY created_at DESC LIMIT 5""",
            (hostname, rule_name, cutoff_iso, KNOWN_TRANSIENT_MIN_CONFIDENCE),
        ).fetchall()
    except sqlite3.Error as exc:
        return SuppressionDecision(
            outcome="escalate", phase="none",
            reason=f"phase2: SQL error ({type(exc).__name__}) — failing open",
            signals={"error": str(exc)[:200]},
        )

    matched = None
    for row in rows:
        ik_id, root_cause, resolution, confidence, tags, created_at, prior_issue_id = row
        blob = " ".join([t or "" for t in (root_cause, resolution, tags)]).lower()
        if any(kw in blob for kw in KNOWN_TRANSIENT_KEYWORDS):
            matched = row
            break

    if not matched:
        return SuppressionDecision(
            outcome="escalate", phase="none",
            reason=f"phase2: no transient-tagged knowledge row matched in last {window_days}d",
            signals={"rows_scanned": len(rows)},
        )

    ik_id, root_cause, resolution, confidence, tags, created_at, prior_issue_id = matched
    comment = (
        f"Tier 1 auto-resolved as known-transient pattern.\n"
        f"Prior incident: {prior_issue_id or 'n/a'} "
        f"(incident_knowledge id={ik_id}, recorded {created_at}, confidence {confidence:.2f}).\n"
        f"Root cause (prior): {root_cause}\n"
        f"Resolution (prior): {resolution}\n"
        f"Tags: {tags}\n"
        f"If this is a NEW issue and not a re-fire of the same pattern, reopen this YT issue "
        f"to escalate to Tier 2 manually."
    )
    return SuppressionDecision(
        outcome="resolved-knownpattern", phase="phase2-knownpattern",
        reason=f"phase2: matched ik_id={ik_id} prior_issue={prior_issue_id} confidence={confidence:.2f}",
        existing_issue_id=str(prior_issue_id or ""),
        comment_text=comment,
        confidence=float(confidence or 0),
        signals={
            "ik_id": ik_id,
            "prior_issue_id": prior_issue_id,
            "prior_confidence": float(confidence or 0),
            "prior_created_at": created_at,
            "window_days": window_days,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Phase 3 — active-memory operator rules
# ─────────────────────────────────────────────────────────────────────
def _match_active_memory_key(stored_key: str, hostname: str, rule_name: str) -> bool:
    """openclaw_memory.key is a glob like 'nlap*:Device Down*'.

    Anchor format: '<hostpat>:<rulepat>'. Either side may be '*' for any.
    """
    if ":" not in stored_key:
        return False
    host_pat, rule_pat = stored_key.split(":", 1)
    return fnmatch.fnmatchcase(hostname, host_pat) and fnmatch.fnmatchcase(rule_name, rule_pat)


def check_phase3_active_memory(hostname: str, rule_name: str, severity: str,
                               db_conn: sqlite3.Connection) -> SuppressionDecision:
    if severity == "critical":
        return SuppressionDecision(
            outcome="escalate", phase="none",
            reason="phase3: severity=critical never auto-resolved by active-memory rule",
            signals={"severity": severity},
        )
    try:
        rows = db_conn.execute(
            "SELECT key, value, updated_at FROM openclaw_memory WHERE category='triage-rule'"
        ).fetchall()
    except sqlite3.Error as exc:
        return SuppressionDecision(
            outcome="escalate", phase="none",
            reason=f"phase3: SQL error ({type(exc).__name__}) — failing open",
            signals={"error": str(exc)[:200]},
        )

    for stored_key, value, updated_at in rows:
        if not _match_active_memory_key(stored_key or "", hostname, rule_name):
            continue
        v = (value or "").strip()
        if not v.lower().startswith("suppress:"):
            continue
        op_reason = v.split(":", 1)[1].strip()
        comment = (
            f"Tier 1 auto-resolved by active-memory rule.\n"
            f"Rule: openclaw_memory key='{stored_key}' updated_at={updated_at}\n"
            f"Operator reason: {op_reason}\n"
            f"To revoke this rule, delete the matching openclaw_memory row."
        )
        return SuppressionDecision(
            outcome="resolved-active-memory", phase="phase3-active-memory",
            reason=f"phase3: matched key='{stored_key}' reason={op_reason!r}",
            comment_text=comment,
            confidence=1.0,
            signals={"rule_key": stored_key, "rule_value": v, "rule_updated_at": updated_at},
        )

    return SuppressionDecision(
        outcome="escalate", phase="none",
        reason="phase3: no matching active-memory triage-rule",
        signals={"rules_scanned": len(rows)},
    )


# ─────────────────────────────────────────────────────────────────────
# Top-level decision
# ─────────────────────────────────────────────────────────────────────
def check_suppression(hostname: str, rule_name: str, severity: str,
                      db_path: str, triage_log_path: str,
                      current_issue_id: str = "",
                      now_utc: Optional[datetime.datetime] = None,
                      recent_window_min: int = RECENT_WINDOW_MIN_DEFAULT,
                      knowledge_window_days: int = KNOWLEDGE_WINDOW_DAYS_DEFAULT,
                      force_escalate: bool = False,
                      globally_disabled: bool = False,
                      yt_issue_open_checker: Optional[Callable[[str], bool]] = None
                      ) -> SuppressionDecision:
    """Run all three phases in order. Return the first non-escalate decision."""
    if globally_disabled:
        return SuppressionDecision(outcome="escalate", phase="none",
                                   reason="suppression globally disabled (TIER1_SUPPRESSION_DISABLED=1)")
    if force_escalate:
        return SuppressionDecision(outcome="escalate", phase="none",
                                   reason="force_escalate=true (n8n flapping detector)")
    if now_utc is None:
        now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Track each phase's pass-through reason so the final escalate decision
    # carries the journey (e.g. "phase1 matched but parent issue was closed").
    journey: list[tuple[str, str]] = []
    accumulated_signals: dict = {}

    # Phase 1 — does not need the DB
    try:
        d1 = check_phase1_dedup(hostname, rule_name, severity, triage_log_path,
                                current_issue_id, now_utc, recent_window_min,
                                yt_issue_open_checker)
        if d1.is_suppression():
            return d1
        journey.append(("phase1", d1.reason))
        if d1.signals:
            accumulated_signals["phase1"] = d1.signals
    except Exception as exc:
        journey.append(("phase1", f"uncaught {type(exc).__name__}: {exc}"))
        accumulated_signals["phase1"] = {"error": str(exc)[:200]}

    # Phases 2 + 3 need the DB
    try:
        db_conn = sqlite3.connect(db_path, timeout=5.0)
        db_conn.row_factory = None
    except sqlite3.Error as exc:
        journey.append(("db_connect", f"failed ({type(exc).__name__}: {exc})"))
        return SuppressionDecision(
            outcome="escalate", phase="none",
            reason="; ".join(f"{p}: {r}" for p, r in journey),
            signals={**accumulated_signals, "error": str(exc)[:200]},
        )

    try:
        try:
            d2 = check_phase2_knownpattern(hostname, rule_name, severity, db_conn,
                                           now_utc, knowledge_window_days)
            if d2.is_suppression():
                return d2
            journey.append(("phase2", d2.reason))
            if d2.signals:
                accumulated_signals["phase2"] = d2.signals
        except Exception as exc:
            journey.append(("phase2", f"uncaught {type(exc).__name__}: {exc}"))
            accumulated_signals["phase2"] = {"error": str(exc)[:200]}

        try:
            d3 = check_phase3_active_memory(hostname, rule_name, severity, db_conn)
            if d3.is_suppression():
                return d3
            journey.append(("phase3", d3.reason))
            if d3.signals:
                accumulated_signals["phase3"] = d3.signals
        except Exception as exc:
            journey.append(("phase3", f"uncaught {type(exc).__name__}: {exc}"))
            accumulated_signals["phase3"] = {"error": str(exc)[:200]}
    finally:
        db_conn.close()

    return SuppressionDecision(
        outcome="escalate", phase="none",
        reason="; ".join(f"{p}: {r}" for p, r in journey) or "all three phases passed through",
        signals=accumulated_signals,
    )


# ─────────────────────────────────────────────────────────────────────
# CLI — called by the bash triage scripts
# ─────────────────────────────────────────────────────────────────────
def _yt_open_checker_default(yt_url: str, yt_token: str) -> Callable[[str], bool]:
    import urllib.request, urllib.error
    def _check(issue_id: str) -> bool:
        if not issue_id:
            return False
        req = urllib.request.Request(
            f"{yt_url.rstrip('/')}/api/issues/{issue_id}?fields=id,resolved",
            headers={"Authorization": f"Bearer {yt_token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())
        # YouTrack's `resolved` field is a unix epoch ms when the issue is resolved, else null
        return payload.get("resolved") is None
    return _check


def main(argv=None):
    p = argparse.ArgumentParser(description="Tier 1 triage suppression decision (3-phase)")
    p.add_argument("--hostname", required=True)
    p.add_argument("--rule-name", required=True)
    p.add_argument("--severity", required=True)
    p.add_argument("--current-issue-id", default="")
    p.add_argument("--db", default="/app/cubeos/claude-context/gateway.db")
    p.add_argument("--triage-log", default="/app/cubeos/claude-context/triage.log")
    p.add_argument("--recent-window-min", type=int, default=RECENT_WINDOW_MIN_DEFAULT)
    p.add_argument("--knowledge-window-days", type=int, default=KNOWLEDGE_WINDOW_DAYS_DEFAULT)
    p.add_argument("--force-escalate", action="store_true")
    p.add_argument("--no-yt-check", action="store_true",
                   help="Skip the live YT-open check (assume parent is open). For tests + offline runs.")
    p.add_argument("--yt-url", default=os.environ.get("YOUTRACK_URL", ""))
    p.add_argument("--yt-token", default=os.environ.get("YOUTRACK_TOKEN", ""))
    p.add_argument("--now-utc", default="",
                   help="ISO UTC override for tests; default = real now.")
    args = p.parse_args(argv)

    if args.no_yt_check or not (args.yt_url and args.yt_token):
        yt_checker = None
    else:
        yt_checker = _yt_open_checker_default(args.yt_url, args.yt_token)

    now_utc = None
    if args.now_utc:
        now_utc = datetime.datetime.fromisoformat(args.now_utc.replace("Z", "+00:00"))

    decision = check_suppression(
        hostname=args.hostname,
        rule_name=args.rule_name,
        severity=args.severity.lower(),
        db_path=args.db,
        triage_log_path=args.triage_log,
        current_issue_id=args.current_issue_id,
        now_utc=now_utc,
        recent_window_min=args.recent_window_min,
        knowledge_window_days=args.knowledge_window_days,
        force_escalate=args.force_escalate,
        globally_disabled=os.environ.get("TIER1_SUPPRESSION_DISABLED", "") == "1",
        yt_issue_open_checker=yt_checker,
    )
    print(decision.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
