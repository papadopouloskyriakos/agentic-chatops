# nl-n8n01

**Site:** NL (Leiden)

## Knowledge Base References

**gateway:CLAUDE.md**
- n8n LXC (CT VMID_REDACTED, hostname `nl-n8n01`, 10.0.181.X) lives on **nl-pve01**. Two remediations landed 2026-04-19 after IFRNLLEI01PRD-622 (LXC cgroup OOM-kill every ~90 min, 69 lifetime events):

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-16 | n8n SQLite mutex timeout | Same pve01 memory-pressure class as IFRNLLEI01PRD-566/567. p | Self-healed in ~90s. No intervention needed. Recurring failu | 0.9 |

## Related Memory Entries

- **CLI and n8n Audit 2026-03-12** (reference): Comprehensive audit of Claude Code CLI flags, n8n node patterns, and MCP tool usage against official documentation. Includes HIGH-risk bugs, correct/incorrect patterns, and action items.
- **defra01agri01 — agentic system mirror target** (project): Designated mirror target for gradual deploy of the NL agentic system (n8n + Claude Code + RAG + chaos). Access + baseline specs.
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 pve01 memory pressure class.
- **local_n8n_db_snapshot_is_stale** (project): /tmp/n8n-db.sqlite on nl-claude01 is a stale manual snapshot, not the live DB. Use workflows/ repo exports or n8n-mcp for current state.
- **n8n Technical Facts and Pitfalls** (project): Key technical facts about n8n, Claude CLI, expression pitfalls, MCP update safety, webhook registration, and known bugs

*Compiled: 2026-05-06 00:48 UTC*