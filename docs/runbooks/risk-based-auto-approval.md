# Risk-based auto-approval — integration runbook (IFRNLLEI01PRD-632)

## What this delivers

A classifier (`scripts/classify-session-risk.py`) that decides per-session
whether a Tier-2 Claude Code run is safe to auto-resolve without the Matrix
`[POLL]` prompt. Three outputs:

| risk_level | meaning                                            | auto_approve |
|------------|----------------------------------------------------|--------------|
| `low`      | Plan is read-only: kubectl get, diagnostic reads, no AWX templates, no mutation verbs | **yes** |
| `mixed`    | Ambiguous — containment verbs, AWX templates referenced, IaC plan/apply in plan | no (current HITL path) |
| `high`     | Explicit mutation (kubectl apply, systemctl restart, crypto map clear, pct set, reboot, etc.), or category in `{maintenance, security-incident, deployment}` | no |

Also delivers:
- `session_risk_audit` SQLite table — one row per classification with full signals + plan hash, so "did we ever auto-approve a non-low session?" is auditable.
- `scripts/audit-risk-decisions.sh` — weekly operator audit with invariant check (exits non-zero on violation).
- Operator override flag (`--override "reason"`) — forces `high` even on a would-be low plan, useful for sensitive alerts.
- Fail-closed behaviour: `RISK_FAIL_CLOSED=1` env forces `high` on any classifier error.

## What this runbook does NOT deliver (yet)

The n8n workflow wiring. The classifier is standalone; three small edits to
existing workflows are needed to take advantage of it. Deferred to avoid
touching the Build Prompt + Matrix Bridge JS without a planned window (past
Build Prompt bugs cost 14h of availability — see
`operational_activation_audit_20260410.md` "Runner Build Prompt SyntaxError"
section).

## Wiring plan — 3 touchpoints

### 1. Runner workflow (`qadF2WcaBsIR7SWG`) — add Classify Risk SSH node

Insert between `Build Plan` and `Build Prompt`:

```
Query Knowledge → Build Plan → **Classify Risk** → Build Prompt → Launch Claude
```

Node config:

```json
{
  "name": "Classify Risk",
  "type": "n8n-nodes-base.ssh",
  "typeVersion": 1,
  "credentials": { "sshPrivateKey": { "id": "REDACTED_SSH_CRED" } },
  "parameters": {
    "authentication": "privateKey",
    "command": "echo '{{ JSON.stringify($json.plan) }}' | ALERT_CATEGORY='{{ $json.alert_category }}' ISSUE_ID='{{ $json.issue_id }}' RISK_FAIL_CLOSED=1 python3 /app/claude-gateway/scripts/classify-session-risk.py"
  }
}
```

The classifier writes its audit row, prints JSON to stdout. The SSH node's
`stdout` becomes available as `$json.stdout` downstream; Build Prompt reads
`JSON.parse($json.stdout).risk_level` and `.auto_approve_recommended`.

### 2. Build Prompt (`Runner` → `Build Prompt` Code node) — inject risk context

In each of the three prompt variants (`react_v1`, `react_v2`, `dev`), after
the `INVESTIGATION_PLAN` section, add:

```javascript
// Risk classification from previous SSH node's stdout
let riskInfo = {};
try { riskInfo = JSON.parse($('Classify Risk').first().json.stdout); } catch(e) {}
const risk = riskInfo.risk_level || 'mixed';
const autoApprove = !!riskInfo.auto_approve_recommended;

const riskSection = autoApprove
  ? `\n\n## SESSION RISK: LOW\n\nThis session has been classified as read-only / diagnostic. End your final message with \`[AUTO-RESOLVE]\` instead of \`[POLL]\` if you have confidence in your diagnosis and no infrastructure changes are needed. If during investigation you discover that a change IS needed, switch to \`[POLL]\` to request human approval.\n`
  : `\n\n## SESSION RISK: ${risk.toUpperCase()}\n\nThis session is ${risk === 'high' ? 'high-risk' : 'ambiguous'} — always use \`[POLL]\` for any remediation step. Do not \`[AUTO-RESOLVE]\` on this session.\n`;
```

Splice `riskSection` into each variant's prompt string. Follow the
existing `INVESTIGATION_PLAN` injection as a pattern.

### 3. Matrix Bridge (`QGKnHGkw4casiWIU`) — handle `[AUTO-RESOLVE]`

In the existing bridge node that parses Claude's final message:

```javascript
// After the existing [POLL] handling...
if (msg.includes('[AUTO-RESOLVE]')) {
  // Post summary as m.notice (no ping) instead of m.text with poll
  postToMatrix(roomId, { msgtype: 'm.notice', body: summary });
  // Auto-close YT issue
  closeYtIssue(issueId, 'auto-resolved-low-risk');
  // Update audit row to reflect auto-approval took effect
  sqlite3.run(
    `UPDATE session_risk_audit SET auto_approved = 1
       WHERE issue_id = ? AND id = (SELECT MAX(id) FROM session_risk_audit WHERE issue_id = ?)`,
    [issueId, issueId]
  );
  return; // done, no poll
}
```

## Safety nets

### 1. `scripts/audit-risk-decisions.sh` runs as weekly cron

```
15 6 * * 1 /app/claude-gateway/scripts/audit-risk-decisions.sh 7 > /tmp/risk-audit-weekly.txt 2>&1
```

If the invariant check fails (any `auto_approved=1` row with
`risk_level != 'low'`), script exits non-zero. Wrap with a Matrix alert
in the cron line for pagers.

### 2. `holistic-agentic-health.sh` hook

Add a section that runs the auditor in check-only mode and flags the same
invariant violation. Gets picked up by the 96%+ health target.

### 3. Operator rollback

If the classifier is misbehaving in production, disable auto-approve in one
of two ways:

- Shell: export `CLASSIFIER_FORCE_MIXED=1` in the Runner workflow's env (not
  implemented yet — add in Build Prompt wrapper as a simple short-circuit).
- Cron: stop the weekly audit while investigating. Classification still
  happens per-session but without rollup reporting.

## Acceptance for moving 632 to Done

1. Classifier CLI + tests pass (✓ this session — 10/10 smoke tests).
2. `session_risk_audit` table created + audit script working (✓ this session).
3. Runner workflow has Classify Risk SSH node wired in production. **(pending)**
4. Build Prompt injects risk context into all 3 variants. **(pending)**
5. Matrix Bridge handles `[AUTO-RESOLVE]` end-to-end with m.notice + YT auto-close. **(pending)**
6. 20 representative alert replays: infra-modifying sessions still hit poll path (100%); investigation-only sessions auto-resolve at ≥40%. **(pending — requires replay harness)**
7. Audit invariant holds over 14 days in production. **(pending)**

## References

- `scripts/classify-session-risk.py` — the classifier
- `scripts/audit-risk-decisions.sh` — the weekly operator audit
- `session_risk_audit` table in `gateway.db`
- IFRNLLEI01PRD-622's sister ticket on Build Prompt fragility (operational_activation_audit_20260410.md)
- Competitive source: homelab-agent diagnostic-auto-approval pattern
