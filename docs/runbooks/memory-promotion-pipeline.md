# Memory promotion pipeline — runbook (IFRNLLEI01PRD-630)

## What this delivers

A manually-run audit (`scripts/memory-audit.py`) that surfaces two kinds of
maintenance opportunities in the auto-memory directory:

1. **Distillation candidates** — clusters of memories covering overlapping
   topics, where operator review could collapse several files into one
   canonical entry. Reduces MEMORY.md index bloat (currently 26 KB, over
   the 24 KB truncation threshold).
2. **Expiry candidates** — project-type memories older than N days (default
   90) that likely represent frozen-in-time snapshots the model no longer
   benefits from.

## Operator workflow

```bash
# Full report
cd /app/claude-gateway
python3 scripts/memory-audit.py

# Machine-readable
python3 scripts/memory-audit.py --json /tmp/memory-audit.json

# Tune sensitivity
MEMORY_DUP_THRESHOLD=0.85 python3 scripts/memory-audit.py --candidates-only
MEMORY_STALE_DAYS=60 python3 scripts/memory-audit.py
```

Review the output. For each cluster: decide whether to **distill** (combine
into one canonical file, delete the others) or **leave** (the overlap is
intentional, e.g. one per repo).

For each expiry candidate: decide whether to **archive** (move to
`memory/archive/` for historical reference) or **delete**.

## What this does NOT do (by design)

- **Never auto-deletes.** The script is a report; the operator decides.
- **Never calls an LLM for distillation.** Writing the canonical text is a
  judgment call — today it stays with the operator. The LLM-assisted
  distillation is a clear follow-up once we see which clusters recur.
- **Never expires feedback memories.** Feedback rules ("don't push to main
  for repo X", "always use full hostnames") are durable guidance; staleness
  doesn't apply. Expiry is project-only.
- **Doesn't read access counts.** We don't yet instrument memory Read hits,
  so "unused for 90 days" is approximated via git-log/mtime rather than
  actual access. Access instrumentation is deferred — when implemented,
  extend this script with an `access_count < N` filter.

## Clustering mechanics

- Embeds `"{name}: {description}"` of each memory (NOT the body — topic
  identity is in the name/description; body is what would change between
  near-duplicates). Uses `nomic-embed-text` on `nl-gpu01:11434`
  (already present for RAG).
- Union-find on pairs with cosine ≥ `MEMORY_DUP_THRESHOLD` (default 0.82)
  — chains resolve: `A~B, B~C` → single 3-member cluster `{A, B, C}`.
- Cross-type pairs are rejected: a `project` memory never gets proposed
  for merge with a `feedback` memory. Different durability classes.

## Example output (2026-04-19)

First run flagged 5 clusters from 143 files:

- 4 `chaos_audit_*` project memories (clear merge candidate — one canonical
  "chaos engineering audit history")
- 4 `session_summary_*` project memories — all Compacted-session snapshots,
  identical schema, different issue IDs. Probably should move out of
  memory entirely (to `docs/compacted-sessions/` or similar).
- `chaos_baseline_plan` + `chaos_baseline_impl` — plan + impl pair
- `github_mirror_chatops` + `github_sync` — both about GitHub mirroring
- `feedback_push_to_main_gateway` + `feedback_push_to_main` — one for
  gateway, one for meshsat. Either merge into a single "repos that push to
  main" list or keep separate (current state is fine; it's borderline).

## Cron (optional — daily digest)

Once the operator has a feel for signal quality, add a weekly cron that
posts the report to Matrix:

```
# 0 7 * * 1 /app/claude-gateway/scripts/memory-audit.py --candidates-only > /tmp/memory-audit.txt 2>&1 && scripts/matrix-alert.sh INFO "memory audit" "$(cat /tmp/memory-audit.txt)"
```

Not installed yet — add after 2-3 manual-run iterations confirm the
signal quality is high enough to be worth the weekly ping.

## Acceptance for moving 630 to Done

1. `scripts/memory-audit.py` produces useful clusters. (✓ this session — 5
   found on first run, 4 of them clearly actionable)
2. Operator does at least one round of distillation (collapses one of the
   flagged clusters). (pending)
3. MEMORY.md size drops below the 24 KB truncation threshold after
   distillation. (pending — depends on #2)
4. Memory Read-access instrumentation is added so future rounds can use
   `access_count < N` as a filter rather than git-log heuristic. (pending —
   open as a sub-ticket if we want it)
5. Optional: LLM-assisted distillation script that drafts the canonical
   entry from a cluster, for operator review. (explicitly deferred —
   see "What this does NOT do")

## References

- `scripts/memory-audit.py` — the tool
- IFRNLLEI01PRD-630 — competitive-gap source (homelab-agent)
- Related: MEMORY.md truncation warning observed in today's session
  (system-reminder: "MEMORY.md is 26.1KB (limit: 24.4KB) — index entries
  are too long")
