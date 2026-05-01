# OpenClaw retirement migration plan

**Date:** 2026-04-29
**Driver:** Anthropic April-4 OAuth-for-third-party-tools ban + OpenClaw 2026.4.26 MCP-binding regression. OpenClaw alert triage has been broken since 08:56 UTC. Replacing with direct n8n→SSH→`claude -p` (the same path used for dev/CUBEOS/MESHSAT today).

## Audit findings

### OpenClaw's actual role in alert triage (the surprise)

**OpenClaw is NOT doing the triage analysis.** The triage scripts (`k8s-triage.sh` 40KB, `infra-triage.sh` 58KB) are self-contained bash that:
- Search YouTrack for existing issues (dedup) → create/reuse one
- Run kubectl / SSH / curl investigations
- Post findings to YouTrack
- Optionally escalate

The script does everything end-to-end. OpenClaw's role was just: receive a Matrix mention, spawn its own claude binary, let claude execute the bash script via its Bash tool. The LLM's only judgement was "yes I will run this script as instructed". The actual triage logic is all in bash.

**This means we don't need an LLM in the path at all for L1 triage.** The script is the agent.

### Already-existing infrastructure that fits

| Asset | Where | Used by |
|---|---|---|
| `claude-gateway-runner.json` workflow | n8n | Existing — runs `claude -p` on claude01 for dev tasks (CUBEOS/MESHSAT) and infra issues (IFRNLLEI01PRD/IFRGRSKG01PRD prefix routing already wired) |
| Triage scripts | `/app/claude-gateway/openclaw/skills/{k8s-triage,infra-triage}/` | Repo-tracked, runnable from claude01 directly |
| `cc-cc` mode | `/home/app-user/gateway.mode` | Documented "Claude Code only (legacy, bypass OpenClaw)" mode — flipping to this is half the migration |
| `claude` binary | `/home/app-user/.local/bin/claude` on claude01 | Already used by the Runner workflow; sanctioned by Anthropic for direct CLI use |

### Inventory

#### Triage-relevant skills (port targets)
| Skill | Path | Purpose | Action |
|---|---|---|---|
| `k8s-triage` | `openclaw/skills/k8s-triage/` | K8s alert triage (Prometheus) | KEEP, runs from claude01 |
| `infra-triage` | `openclaw/skills/infra-triage/` | Host alert triage (LibreNMS) | KEEP, runs from claude01 |
| `security-triage` | `openclaw/skills/security-triage/` | CrowdSec/scanner triage | KEEP, runs from claude01 |
| `correlated-triage` | `openclaw/skills/correlated-triage/` | Multi-alert correlation | KEEP, runs from claude01 |
| `escalate-to-claude` | `openclaw/skills/escalate-to-claude/` | Tier-2 escalation prompt builder | KEEP, runs from claude01 |
| `proactive-scan` | `openclaw/skills/proactive-scan/` | Cron-driven background scanning | KEEP if cron-invoked, runs from claude01 |
| `safe-exec.sh`, `site-config.sh`, `yt-post-comment.sh`, `claude-knowledge-lookup.sh` | `openclaw/skills/` (top-level) | Support libraries the triage scripts source | KEEP, used by triage scripts |
| `lab-lookup`, `netbox-lookup`, `playbook-lookup`, `operational-kb`, `memory-recall`, `youtrack-lookup`, `codegraph-lookup` | various | RAG / catalog lookups | KEEP if any triage path uses them; verify per-script |
| `baseline-add`, `cross-tier-review`, `error-propagation`, `exec-safety` | various | Operational helpers | UNCERTAIN — verify if triage uses them; otherwise out-of-scope for L1 migration |

#### N8n workflows that mention @openclaw
| Workflow | Currently does | Migration action |
|---|---|---|
| `claude-gateway-prometheus-receiver.json` | Posts `@openclaw use exec ./skills/k8s-triage/k8s-triage.sh ...` to Matrix | **REWIRE** — replace Matrix-mention post with SSH-to-claude01 to run script directly |
| `claude-gateway-prometheus-receiver-gr.json` | Same for GR site | REWIRE (same change) |
| `claude-gateway-librenms-receiver.json` | Posts `@openclaw use exec ./skills/infra-triage/infra-triage.sh ...` | REWIRE |
| `claude-gateway-librenms-receiver-gr.json` | Same for GR | REWIRE |
| `claude-gateway-security-receiver.json` | Posts `@openclaw use exec ./skills/security-triage/...` | REWIRE |
| `claude-gateway-security-receiver-gr.json` | GR | REWIRE |
| `claude-gateway-crowdsec-receiver.json` | CrowdSec alerts | REWIRE |
| `claude-gateway-crowdsec-receiver-gr.json` | GR | REWIRE |
| `claude-gateway-synology-dsm-receiver.json` | DSM alerts | REWIRE |
| `claude-gateway-matrix-bridge.json` | Has "Run OpenClaw" SSH node + `!mode` switching + openclaw-mention parsing | **TRIM** — remove OpenClaw routing, keep @claude routing. `!mode` becomes a no-op or removed. |
| `claude-gateway-runner.json` | Already runs claude binary on claude01 — no change for dev path | UNCHANGED for dev. May get a new entry-point for triage delegation if we want LLM summary. |
| `claude-gateway-session-end.json` | Has openclaw-related cleanup | TRIM openclaw refs |

#### Scripts referencing openclaw (~16 total)
| Script | Action |
|---|---|
| `poll-openclaw-usage.sh` | RETIRE — Tier-1 token tracking via openclaw-cli; no longer relevant if openclaw stops. Comment out cron, keep file for replay. |
| `sync-openclaw-skills.sh` | RETIRE — synced gateway repo skills into openclaw container; no need if openclaw stops. Comment out cron. |
| `agentic-stats.py`, `write-agent-metrics.sh`, `write-session-metrics.sh`, `holistic-agentic-health.sh` | UPDATE — drop openclaw references from metric calculations, but keep the scripts |
| `wiki-compile.py`, `build-wiki-site.sh` | UPDATE — wiki sources include OpenClaw skill metadata; can keep referencing the repo `openclaw/skills/` directory since it stays |
| `teacher-agent.py`, `kb-semantic-search.py`, `archive-session-transcript.py`, `ragas-eval.py`, `agent-diary.py`, `service-health.py`, `golden-test-suite.sh`, `grade-prompts.sh`, `test-hook-blocks.py`, `test-security-hooks.sh`, `export-attack-navigator.py`, `write-security-metrics.sh`, `lib/handoff.py`, `lib/wiki_url.py` | UPDATE only if they reach the openclaw container directly. Mostly they reference openclaw the *concept* (skill paths, patterns). Will audit case-by-case during implementation. |

#### CLAUDE.md changes
- Mode table — collapse to single mode (no `oc-*` modes); document `cc-cc` as the only mode
- Architecture diagram — remove "OpenClaw" frontend; n8n receivers go directly to app-user SSH
- "Master workflow skill" wording — chatops-workflow already references @openclaw infrastructure
- 03_Lab integration — keep mentioning `lab-lookup` skill but path is now in claude-gateway repo
- Operating Modes section — replace with a brief note about cc-cc as the only mode post-migration

#### Memory files
- 10 `openclaw_*.md` files — KEEP as historical record
- 2 `feedback_openclaw_*.md` files (`_deploy_checklist`, `_ssh`) — KEEP, still useful if anyone touches the openclaw01 host

## Migration plan

### Phase A — Rewire n8n receiver workflows (1.5–2 hours)

For each receiver workflow listed above, replace the "Post Triage Instruction" pattern:

**OLD (current pattern, simplified):**
```yaml
node "Post Triage Instruction":
  type: httpRequest
  url: "$MATRIX/_matrix/client/v3/rooms/$ROOM/send/m.room.message/$txn"
  body: { msgtype: m.text, body: "@openclaw use the exec tool to run: ./skills/k8s-triage/k8s-triage.sh ..." }
```

**NEW (proposed pattern):**
```yaml
node "Run Triage Script":
  type: ssh
  host: nl-claude01
  user: app-user
  command: |
    cd /app/claude-gateway/openclaw
    timeout 300 ./skills/k8s-triage/k8s-triage.sh \
      "{{$json.alertname}}" "{{$json.severity}}" \
      "{{$json.namespace}}" "{{$json.summary}}" \
      "{{$json.hostname}}" "{{$json.pod}}"
  # The script self-creates YT issue, investigates, posts findings.
  # No Matrix message needed at this step — the script handles all output.
```

The Runner workflow stays unchanged. It already handles tier-2 escalation when YT issues need richer Sonnet-level analysis (the existing dev-side path).

For escalations (currently `Post Escalation Instruction` posts `@openclaw use exec FORCE_ESCALATE=true ./skills/escalate-to-claude.sh ...`), call the Runner workflow with a "build-escalation-prompt + invoke claude" payload. **This already exists for dev-side issues**; just needs the trigger wired.

### Phase B — Script accessibility verification (30 min)

Run each triage script directly from claude01 against a test alert to confirm:
1. They run without OpenClaw container
2. They source `site-config.sh` and other support libs correctly from the repo path
3. They post YT comments / Matrix messages with the expected formatting

Scripts ARE already in the gateway repo on claude01 — `/app/claude-gateway/openclaw/skills/`. Just need to confirm they work standalone.

### Phase C — Parallel run + cutover (45 min + monitoring)

1. Deploy the rewired receiver workflows alongside the existing ones (OR in-place; receivers are stateless, easy to swap)
2. Stop the openclaw container: `docker stop openclaw-openclaw-gateway-1`
3. Trigger a few test alerts via the receivers (curl the webhook URLs with synthetic Prometheus payloads)
4. Verify the triage scripts run, YT issues are created, Matrix messages posted as @claude
5. Wait for real alerts to flow through naturally over the next ~30 min
6. If clean: declare migration done. If broken: roll back by re-importing old workflows (snapshots taken before edits).

### Phase D — Retire / cleanup (after 24h of clean operation)

- Comment out `poll-openclaw-usage.sh` cron (keep script)
- Comment out `sync-openclaw-skills.sh` cron (keep script)
- Update `agentic-stats.py` to drop openclaw rows from cost calculations
- Update CLAUDE.md mode table (collapse to single mode)
- Update chatops-workflow skill to remove openclaw-mention references
- Optional: power off openclaw01 LXC entirely (saves ~1.5GB RAM on nl-pve01 — relevant given the host's pressure history)

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Triage script depends on OpenClaw runtime env vars / paths that don't exist on claude01 | Phase B verification catches this before cutover. Rollback = re-enable openclaw container. |
| n8n workflow edit breaks something silently | Snapshot every workflow before editing; n8n keeps versions natively. Rollback = re-import previous version. |
| Real alert arrives during cutover and gets dropped | Trigger phase B in a maintenance window OR run both old + new in parallel for one alert cycle |
| Script path differences between openclaw container and claude01 cause site-config.sh to fail | Test each triage script's `--dry-run` mode (if it exists) or with a known-safe alert (TargetDown for cluster-wide, no destructive ops) |
| Metric dashboards lose openclaw cost-tracking continuity | poll-openclaw-usage.sh historical data stays in `llm_usage` table; new tier=2 rows from claude binary continue via existing `poll-claude-usage.sh` |
| dominicus / clawdbot / matrix-side tooling depends on @openclaw being responsive | None today (openclaw is silent already since 08:56 UTC). No regression vs current state. |

## Out of scope (intentionally NOT migrating)

- Dreaming-narrative cron (an OpenClaw-specific feature)
- OpenClaw memory-core (separate from app-user's memory)
- OpenClaw-specific skills (apple-notes, slack, github, etc.) — these were openclaw's general-purpose dev tools, not relevant for infra triage
- OpenClaw mode switching (`!mode` command) — collapses to a single mode, no switching
- A2A / cross-tier review handoff (the `_a2aMessageType: "review"` flow in matrix-bridge) — this is openclaw → claude-code review handoff. With openclaw stopped it becomes vestigial. Will leave the SQL tables but disable the parser path during cleanup.

## Decision points for operator review

Please confirm before I implement:

1. **Scope:** Is "1st-level triage" exactly k8s-triage + infra-triage + security-triage + crowdsec? Or also correlated-triage / proactive-scan?
2. **Cutover style:** in-place workflow edits (faster, requires snapshots) or parallel deploy of new workflows alongside old (safer, more setup)?
3. **OpenClaw retirement:** stop container only, or power off LXC entirely?
4. **Tier-2 escalation:** keep the existing `escalate-to-claude.sh` invocation pattern (just wire it to Runner instead of @openclaw mention)? Or redesign?
5. **Dependent scripts:** drop openclaw-touching scripts immediately or keep them with cron commented for ~1 week as rollback insurance?

Reply with answers to these 5 points and I will start Phase A.
