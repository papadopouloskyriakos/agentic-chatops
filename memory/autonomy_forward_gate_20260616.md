# Autonomy-forward gate — human as circuit-breaker (2026-06-16, IFRNLLEI01PRD-1102)

**Why:** the human-in-the-loop almost never votes on the Matrix approval polls (notifications off, ~0 votes in the prior 1–2 months — confirmed: no clean per-vote ledger exists, only the bridge's capped-100 `pollCache` + a thumbs `session_feedback` signal that stopped 2026-05-07). So ~56% of sessions escalated to a poll → no vote → 15-min remind → 30-min `shouldPause:true` → **session stranded**. And there was **zero session→SMS path** (SMS fired only from Alertmanager tier-1). Net: the gate was a dead-end — not autonomous, not supervised. Operator directive: **more auto-resolve; SMS for critical-only.**

## What shipped (epic IFRNLLEI01PRD-1102, children -1103..-1109)
Merged to `main` at `778406b` (CI #37237 green: validate_scripts / validate_code_nodes / validate_workflows all ✅). Branch `feature/autonomy-forward-gate`, commits `988d59b` → `706afc5` → `04596e6` → merge `778406b`.

**3-band model** (was the binary `auto = risk==low`), emitted by `classify-session-risk.py` only when enabled:
| Band | Trigger | Action | Operator |
|---|---|---|---|
| `AUTO` | low, OR reversible+prediction-eligible MIXED (non-P0, blast < threshold) | `[AUTO-RESOLVE]`, no poll, no SMS | none |
| `AUTO_NOTICE` | reversible MIXED on a **P0 host** OR wide blast (≥ `INFRAGRAPH_BLAST_THRESHOLD`) | `[AUTO-RESOLVE]` **+ parallel SMS** | out-of-band veto (`!session abort`) |
| `POLL_PAUSE` | HIGH / irreversible / deviation / partial / no-prediction / jailbreak / P0-reboot | `[POLL]`, no-vote PAUSES, **SMS** | mandatory |

Operator answered 4 decision forks: Q1 timeout=proceed-for-reversible, Q2 SMS=HIGH-only, Q3 auto-resolve=ALL reversible+prediction-eligible MIXED, Q4 reversible-P0 auto-proceeds+SMS.

**Components:**
- `classify-session-risk.py`: band engine + `_assign_bands()`; irreversible re-tagging via `IRREVERSIBLE_PATTERNS` (**closed real gaps** — `terraform destroy` was only MIXED; `mkfs`/`dd-of-dev`/`zpool destroy`/`dropdb` were *unmatched* → could have auto-resolved a wipe); `_P0_HOSTS_BASE`; `sms_required`; `_fire_session_sms()` best-effort POST to `/alert-session` at classify time (earlier than the poll = more reaction time, never blocks classify). (-1103)
- `alertmanager-twilio-bridge.py`: new `/alert-session` endpoint (the missing session→SMS path), dedup by `issue_id`, critical-gated defense-in-depth, `/metrics` `session_sms_total{outcome}` counter. Service is systemd `--user` `alertmanager-twilio-bridge.service` (restart needs `XDG_RUNTIME_DIR=/run/user/1000`). (-1105)
- Runner `Build Prompt` (n8n PUT live, validator PASSED): band-aware directive — AUTO/AUTO_NOTICE emit `[AUTO-RESOLVE]`, POLL_PAUSE keeps `[POLL]`. Backward-compatible (no band → exact legacy text). (-1106)
- `session_risk_audit` v2 (`band`/`auto_proceed_on_timeout`/`sms_required`) + schema_version bump (-1108); `docs/host-blast-radius.md` P0 source-of-truth (-1107); `test-1103-autonomy-bands.sh` 14/14 + band-aware weekly invariant in `audit-risk-decisions.sh` + runbook (-1109).

## Enablement = sentinel files (no n8n edit, instant kill-switch)
`_envflag()` honors env var OR `~/gateway.<name lowercased>` (matches `gateway.mode`/`gateway.maintenance`). **ENABLED 2026-06-16:** `touch ~/gateway.autonomy_forward ~/gateway.autonomy_session_sms`. **Kill-switch:** `rm ~/gateway.autonomy_forward` → instant byte-identical legacy (only risk==low auto-resolves). Env knobs: `AUTONOMY_P0_HOSTS_EXTRA`, `AUTONOMY_SOFT_REVERSIBLE_EXTRA`, `AUTONOMY_P0_REBOOT_AUTO` (default off), `INFRAGRAPH_BLAST_THRESHOLD` (8).

## Safety floor (never auto, NOT operator-configurable)
Infragraph deviation; irreversible-destructive; remediation with no committed plan_hash prediction (the existing fail-CLOSED -1044 gate, intact); partial verdict; jailbreak; P0-reboot. Auto-resolve keys on the fail-CLOSED prediction gate, NOT the fail-OPEN advisory. The weekly `audit-risk-decisions.sh` invariant FAILS (and prints `rm ~/gateway.autonomy_forward`) if any auto-approved row is outside AUTO/AUTO_NOTICE or carries a floor signal.

## Two design decisions vs the original plan
1. **-1104 (matrix-bridge timeout-proceed) SUPERSEDED, not built.** Live tracing showed the bridge's 30-min-pause only engages the *"awaiting-approval" text* flow, not the `[POLL]` flow a POLL_PROCEED session uses — and the operator watches SMS not polls. **Folded POLL_PROCEED → AUTO_NOTICE** (wide-blast reversible auto-proceeds + parallel SMS). Net: **zero bridge surgery**, Q1 intent delivered more directly. Model is 3-band (POLL_PROCEED reserved-but-unassigned).
2. **-1106 verdict-gating:** the match/partial/deviation verdict is computed **post-execution** by `infragraph-verify.py`, so it cannot gate the pre-execution `[AUTO-RESOLVE]` decision. The available-information gate IS enforced (reversible + committed prediction; irreversible/deviation excluded at classify time).

## Merge-to-main note (the divergence)
`main` already had the Infragraph epic (its own MRs); this branch carried the handbook-audit epic (deployed-live but never git-merged) + autonomy. Merge resolved 8 conflicts — notably the **`docs/host-blast-radius.md` filename collision** (infragraph's declared-edges seeder doc vs my P0 doc): **unioned** so both the `| source | rel_type | target |` table and the `p0_hosts:` YAML block coexist (both code consumers verified). `classify-session-risk.py` kept infragraph advisory + bands + jailbreak coexisting; `runner.json` took the live superset (bands + infragraph ctx + prediction gate). The push landed autonomy **and** the handbook-audit epic on main together.

Verification: band tests 9/9, QA 14/14, parity (flag-off → byte-identical legacy), floor (`terraform destroy → POLL_PAUSE+SMS`), `/alert-session` gates non-critical, no real SMS sent during verification. Runbook: `docs/runbooks/risk-based-auto-approval.md` § Autonomy-forward gate. Feature doc: `.claude/rules/platform-features.md`.

## Live-verified in production — first real Tier-2 auto-resolve (2026-06-17)
Gate ENABLED since 2026-06-16 20:10 (both sentinels). End-to-end confirmed on a **real alert**, not just synthetics:
- **IFRNLLEI01PRD-1117** — `nlnc01` *Service up/down* (critical). pipeline-debug.log chain: `infra-triage escalate=yes` → `escalate→Runner http=200` → `classify band=AUTO auto_approve=true` (read-only pct/diagnostic reads) → a genuine **26-turn `claude-opus-4-8` session** (id `6a3ff306`, $2.73, 374s, confidence 0.86) that confirmed the host up (LibreNMS Status:True, ~4d uptime = recovered flap) → `[AUTO-RESOLVE]` → `reconcile-sessions yt_state=Done http200 reason=auto-resolve`. Result: YT **Done**, `session_log.resolution_type=auto_resolved`, comment "Auto-resolved by the gateway (band=AUTO); session 6a3ff306 archived." Auto-close was **correct** (host genuinely recovered).
- Plus 3 synthetic E2E (1114/1115/1116) → AUTO → Done → auto_resolved.
- **Discrimination works:** since enablement **4 AUTO (all low/read-only) vs 8 POLL_PAUSE** — the high-risk seaweedfs OOM (-1113) classified `high → POLL_PAUSE` every time; mixed first-passes held at POLL_PAUSE. Not blindly auto-closing.
- **Caveat:** small real sample (1 real + 3 synthetic) — AUTO-eligible real alerts are infrequent (most are Tier-1-suppressed pre-session or higher-risk→poll). Mechanism + correctness proven; volume accrues over time. Trend check: `SELECT resolution_type,count(*) FROM session_log WHERE ended_at>=date('now','-7 days') GROUP BY 1` + `grep 'reconcile_session' ~/logs/claude-gateway/pipeline-debug.log | grep 'band.*AUTO'`.
