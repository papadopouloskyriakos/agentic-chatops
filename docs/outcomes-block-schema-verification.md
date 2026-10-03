# Outcomes block — schema verification

Pre-merge audit of the SQL/data sources used by the new
`outcomes` field added to `scripts/agentic-stats.py` (auto-resolve
rolling 7d + closed-loop median/p95).

Date: 2026-05-11.
Branch: `fix/tx-latency-pings` (extended scope; see MR).

## Data sources

| Field | Source | Column | Notes |
|---|---|---|---|
| triage outcome (resolved\|escalated) | `triage.log` | `parts[4]` | Pipe-delimited; same parse already used by the lifetime `alerts_auto_resolved` / `alerts_escalated` counters. |
| triage timestamp | `triage.log` | `parts[0]` | ISO-8601 UTC (`...Z`). Parsed as `datetime` with `+00:00` substitution. |
| issue id | `triage.log` | `parts[7]` | Used to join into `sessions.issue_id`. |
| escalated session duration | `sessions.duration_seconds` | `INTEGER DEFAULT 0` | Populated by Runner at session end; verified live (41/43 in last 7d are non-zero). |

`session_log` was considered but ruled out: its most recent `ended_at`
is 2026-04-09 (the only rows present are bulk "stale_cleanup /
auto_archived" entries pre-cc-cc), so it cannot serve as the closure
signal under the post-2026-04-29 dispatch path.

## Live numbers at audit time

```
$ wc -l /app/cubeos/claude-context/triage.log
442

$ awk -F'|' '{print $5}' triage.log | sort | uniq -c
    356 escalated
     86 resolved
```

```sql
-- Per-day outcome distribution, recent
SELECT DATE(ts) AS day, outcome, COUNT(*) FROM triage_events
WHERE ts > date('now','-14 days') GROUP BY day, outcome ORDER BY day, outcome;
-- (output truncated — see audit transcript)
```

Generated JSON from the extended script:

```
auto_resolve.current_rate = 0.0599  (6.0%)
auto_resolve.prior_rate   = 0.4000  (40.0%)
auto_resolve.delta_pp     = -34.0
auto_resolve.daily        = 56 rows, 13 non-null
                            (triage.log starts 2026-04-29 cc-cc cutover)

closed_loop.n_closed             = 220
closed_loop.n_open               = 47
closed_loop.median_seconds       = 279
closed_loop.p95_seconds          = 448
closed_loop.prior_median_seconds = 165
closed_loop.prior_p95_seconds    = 358
closed_loop.delta_median_seconds = 114
closed_loop.delta_p95_seconds    = 90
```

## Backwards compatibility

Existing fields unchanged:

```
totals.alerts_auto_resolved   = 86      (was 86)
totals.alerts_escalated       = 356     (was 354 — drift from intervening hours)
models[0]                     = Claude Opus 4.6  (unchanged ordering)
time_series                   = 7 rows  (unchanged shape)
```

Top-level keys after change:
`['models', 'operational_depth', 'outcomes', 'platform', 'quality', 'security', 'time_series', 'totals', 'updated_at']`

The shortcode (`kyriakos:layouts/shortcodes/agentic-stats.html`)
guards every read with `if (data.outcomes && data.outcomes.auto_resolve && data.outcomes.closed_loop)` so any pre-deploy snapshot of the
JSON (no `outcomes` key) skips the block entirely.

## Semantic decisions captured here

- **Tier 1 (resolved) contribution to closed-loop duration**: 0 seconds.
  Reason: triage.log carries one timestamp (logged at the end of the Tier 1
  run). The same timestamp serves as both alert ingestion and terminal state
  for an auto-resolved incident. The result is honest: as auto-resolve % rises,
  the median trends toward zero; the p95 carries the Tier 2 tail.

- **"Open" definition**: an escalated triage row whose `sessions.duration_seconds`
  is 0 (still mid-run OR session abandoned). The badge surfaces only when this
  count is non-zero.

- **Sparkline window**: 56 daily points (last 8 weeks). Each point is the rolling
  7d auto-resolve rate ending at that day. Days with no events in the trailing
  7d window are `rate=null`; the renderer plots only the consecutive trailing
  run of data points (the triage.log doesn't extend further back than 2026-04-29).

## Verification commands

```bash
# 1. Run the extended script against the live DB
python3 scripts/agentic-stats.py > /tmp/outcomes-test.json

# 2. Inspect the outcomes block
python3 -c "
import json
d = json.load(open('/tmp/outcomes-test.json'))['outcomes']
print('auto_resolve:', d['auto_resolve']['current_rate'], 'vs', d['auto_resolve']['prior_rate'])
print('closed_loop: median', d['closed_loop']['median_seconds'], 'p95', d['closed_loop']['p95_seconds'])
print('             n_closed', d['closed_loop']['n_closed'], 'n_open', d['closed_loop']['n_open'])
"

# 3. Render the page locally and run the regression spec
cd /app/websites/papadopoulos.tech/kyriakos && \
  hugo server --bind 127.0.0.1 --port 1318 --disableFastRender --minify=false &
cd /app/claude-gateway/visual-audit && \
  BASE_URL=http://127.0.0.1:1318 npx playwright test --config playwright.outcomes.config.js
```
