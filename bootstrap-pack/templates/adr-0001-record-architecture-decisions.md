# ADR-0001 — Record architecture decisions

## Status

Accepted — `YYYY-MM-DD`

## Context

We need to capture significant architectural decisions made during the project so future contributors (human or agent) understand why current structure exists and can challenge or revisit decisions on basis of new information rather than rediscovering history.

## Decision

Use MADR (Markdown Architecture Decision Records) format. One ADR per file under `adr/NNNN-<title>.md`. Each ADR has Status / Context / Decision / Consequences / Alternatives.

## Consequences

**Positive:**
- Decisions become inspectable + searchable.
- Agents can read ADRs to understand why current patterns exist (avoid re-litigating decided things).
- Onboarding cost drops.

**Negative:**
- Discipline cost — every meaningful decision must be ADR'd.

## Alternatives considered

- **No ADRs** — rejected because tribal knowledge becomes silent context-loss on contributor turnover.
- **Single ARCHITECTURE.md** — rejected because monolithic docs don't capture WHEN/WHY a decision was made; ADRs are inherently dated.
- **Inline code comments** — rejected because architectural decisions span files; one file's comment can't capture cross-cutting choices.

## References

- Michael Nygard's original ADR post: https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
- MADR template: https://adr.github.io/madr/
