# n8n Code-node safety — post-14h-outage runbook

## Why this runbook exists

On 2026-04-10 the Runner **Build Prompt** Code node started throwing
`SyntaxError` on every execution. Because it's a parse-time error,
`try/catch` inside the node couldn't recover it. Every OpenClaw→Claude Code
escalation that hit the Runner crashed at Build Prompt. **14-hour silent
outage.** Full post-mortem: `operational_activation_audit_20260410.md` →
"CRITICAL BUG: Runner Build Prompt SyntaxError".

Root cause was structural, not a typo:

- Build Prompt had **3 copy-pasted variant blocks** sharing one function scope.
- Only the first block was reachable (unconditional `return` between them).
- Blocks 2 + 3 were dead code. But they were still *parsed* — any syntactic
  regression in them broke the whole node.
- A prior edit had left two string literals truncated. As long as the dead
  blocks' structure still parsed, n8n accepted the node. Once a regex-based
  injection shifted surrounding code, the parse broke and Runner died.

The permanent fix (2026-04-19 this runbook) is in two parts: **delete the
dead code** (Build Prompt 90 KB → 36 KB, 3 returns → 1, 3× duplicated
`var reactFramework` → 1) and **add a pre-push validator** that catches
this entire class of regression before the PUT lands in production.

## Validator — `scripts/validate-n8n-code-nodes.sh`

Runs on every Code node in a workflow. Checks:

1. **`node --check`** — authoritative parse. This is exactly what the 14h
   outage would have failed on.
2. **`new Function(...)` constructor parse** — matches n8n's runtime
   semantics (catches a few things `--check` misses like strict-mode
   redeclaration).
3. **Top-level return count** — more than 1 unconditional `return` means
   everything after the first is dead code. `[FAIL]`. This is the shape
   Build Prompt had before this cleanup.
4. **Duplicate top-level `var` declarations** — same variable name declared
   at column 0 multiple times almost always means "copy-pasted sibling
   block sharing scope," which is the pattern behind the 14h outage.
   `[WARN]` (not `[FAIL]` because `var` allows it by spec).

Quote-balance heuristic was tried and removed — escaped quotes in string
literals produce odd raw counts even for valid code (false positive on
"Prepare Result" in Runner).

## Usage

```bash
# Validate a workflow fetched live from the n8n API
./scripts/validate-n8n-code-nodes.sh qadF2WcaBsIR7SWG

# Validate an exported workflow file (before PUT)
./scripts/validate-n8n-code-nodes.sh --file workflows/claude-gateway-runner.json
```

Exit 0 = safe to push. Exit non-zero = do **not** `curl -X PUT`.

## The required edit sequence

Any time you modify a Code node's jsCode:

1. **Fetch current live workflow** via `curl -H "X-N8N-API-KEY: …" …/workflows/<id>` → save as `/tmp/<wf>.rollback.json`. This is your rollback snapshot.
2. **Extract the Code node's jsCode** to a file, make your edits locally.
3. **`node --check` the edited jsCode** — must pass.
4. **Splice the edited jsCode back into the workflow JSON**.
5. **Run the validator** against the patched workflow JSON.
6. **PUT to n8n** (`curl -X PUT …/workflows/<id>`).
7. **Re-fetch + re-validate** to confirm the live state matches what you pushed.
8. **Test-fire** a synthetic execution or watch the first 2–3 real runs.
9. **Export** via `cp /tmp/wf.live-after.json workflows/<name>.json` and commit.

The validator step is the gate. It was not gated before the 14h outage
and the outage ran for 14 hours precisely because nothing failed loud
enough to page anyone.

## What still isn't automated

- **Failure-signal**: n8n Runner execution failures still only surface as
  error rows in n8n's web UI. A Prometheus alert on
  `n8n_workflow_execution_failures_total{workflow="NL - Claude Gateway Runner"}`
  would move the detection floor from "someone notices" to "fires in 5m".
  Not yet installed.
- **Staging environment**: n8n has no dev/stage/prod separation. The
  validator catches parse issues; it can't catch logic regressions without
  a replay harness (IFRNLLEI01PRD-632 referenced this as a "20-alert
  replay" acceptance gate — still pending).

## Historical context

- 2026-04-10 11:56 UTC — SyntaxError starts
- 2026-04-11 01:53 UTC — fix pushed, 3-round debug (14h outage)
- 2026-04-19 ~12:51 UTC — Build Prompt dead code removed (this runbook),
  validator added

Commits: `6ccf4dd` (validator scaffold — this session will replace with
actual commit SHA on push).
