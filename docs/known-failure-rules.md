# Known Failure Rules

Rules derived from 26 bugs fixed 2026-03-10 through 2026-03-14. Follow these to avoid regressions.

| # | Rule | Why |
|---|------|-----|
| 1 | Only set `sessionExpired` on structured `{is_error: true}` JSON — never string-match "session" in response text | False positive lock deletion |
| 2 | Only clean up lock/session on explicit end commands (`!done`, `!issue done/close`) — never in Parse Response | Session drops after first reply |
| 3 | SSH nodes: `authentication="privateKey"` requires `credentials.sshPrivateKey` (NOT `sshPassword`), credential ID `REDACTED_SSH_CRED` | Silent auth failure with `continueOnFail` |
| 4 | OpenClaw SOUL.md must reference `exec` tool by name — GPT-4o ignores generic "run this command" | Tool calls silently skipped |
| 5 | Claude `-r` + `-p` intermittently fails (GitHub #1967) — session resume may return "not found" | Known upstream bug, handle gracefully |
| 6 | `kill -INT` during tool use can corrupt session JSONL (GitHub #3003) — prefer `timeout` for termination | Incomplete tool_use without tool_result |
| 7 | Stream-JSON `{"type":"result"}` line sometimes missing (#1920, #8126) — all 4 Wait nodes have JSONL text fallback | Empty response posted despite output |
| 8 | n8n SSH `executeTimeout` is undocumented/unreliable — use bash `timeout` + env vars `EXECUTIONS_TIMEOUT=900` | Timeouts silently ignored |
| 9 | n8n 2.11.3 `waitForSubWorkflow: false` broken — use HTTP POST to webhook instead of Execute Workflow | Sub-workflow never starts |
| 10 | Webhook nodes need `webhookId` as top-level property; `responseMode` must be top-level parameter (NOT in `options`) | 404s and "Unused Respond to Webhook" errors |
| 11 | n8n Code nodes run in task runner process — `require('fs')` can't read claude01 files. Use SSH nodes for file I/O. | ENOENT on remote paths |
| 12 | SSH nodes wait for child stdout/stderr — background processes must redirect: `</dev/null >/dev/null 2>&1 &` | 5min SSH hang on `sleep` |
| 13 | Never increase LXC RAM without checking pve03 total committed RAM (claude01 steady-state: ~2.5GB, limit: 8GB) | 32GB caused host OOM crash |
| 14 | YT state changes: use command API `POST /api/commands` with `idReadable` — MCP `update_issue_state` is broken | Silent failure with `{"id": ...}` |
| 15 | Bridge session lookup must be room-aware (project prefix) — never use global `WHERE is_current=1` | Cross-room session interference |
| 16 | Alert triage instructions: use `@openclaw` mention pill + `m.notice` for alerts — prevents dual response | OpenClaw responds to both alert and instruction |
| 17 | Issue ID regex must allow digits in project prefix: `^[A-Z0-9]+-[0-9]+$` (not `^[A-Z]+-`) | Rejected IFRNLLEI01PRD-* IDs |
| 18 | Pipe SSH output through `grep -v "^Warning: Permanently added"` in triage scripts | SSH warnings pollute YT comments |
| 19 | LXC `/proc/loadavg` and `free -m` show host metrics — use cgroup v2 (`cpu.pressure`, `memory.current/max`) | Misleading container stats |
| 20 | Before draining K8s worker nodes, check for SeaweedFS pods — no PDBs, 000 replication, cascade restart causes data loss | GR thanos-store 7h crash loop from lost volumes |
