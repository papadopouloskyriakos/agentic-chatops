# AGENTS.md — Claude Gateway

Entry point for any coding agent operating in this repository. The course (Google
5-Day AI Agents, Day 5) calls for a root `AGENTS.md`; this is it.

## Read first
- **`CLAUDE.md`** — operating instructions, hostnames, MCP tools, conventions (authoritative).
- **`.claude/rules/`** — infrastructure, platform-features, workflows, CI/CD rules.
- **`.claude/skills/chatops-workflow/SKILL.md`** — Phase 0→6 incident choreography.

## Spec-driven surfaces (D2 slice — IFRNLLEI01PRD-1260)
The safety-critical behaviors and component interfaces are specified under **`spec/`**
and governed by **`constitution.md`**. Before changing any file listed in a
`spec/<context>/tasks.json#files_owned`, update its `REQ-NNN` requirement and Gherkin
acceptance in the same commit (Article I + VII). Validate with:

```
python3 bootstrap-pack/scripts/validate-project-spec.py .
python3 scripts/check-spec-code-lockstep.py
```

Both run in CI (`validate_spec`), the QA suite (`test-1260-spec-driven.sh`), and
holistic-health. A change that breaks them fails the pipeline.

## What is and is not spec-regenerable
Only the safety-critical surfaces are spec-driven. The full ~71k-LOC estate (442 n8n
nodes, 35k LOC Python) is **not** regenerable from spec by design — see `adr/0001`.

## Conventions
Direct-push to `main` (single-operator). Narrow commits (`git add <files>`). One smoke
test after push. Full conventions in `CLAUDE.md`.
