---
name: constitute
description: Phase C of greenfield project bootstrap. Produce constitution.md (5-15 non-negotiable articles) + steering/*.md (cross-cutting agent-wide rules). Pauses for operator review before exit.
disable-model-invocation: true
allowed-tools: Read, Write, Edit, AskUserQuestion
---

# /constitute — define non-negotiables + cross-cutting rules

After `/specify` produced PROJECT.md + requirements.md, the project needs:

1. `constitution.md` — 5-15 articles of non-negotiable principles
2. `steering/{coding-standards,security-baseline,test-strategy,repo-conventions}.md` — cross-cutting rules every Claude session loads

## Constitution authoring

Start from `<bootstrap-pack>/templates/constitution.md.tmpl` (7 default articles cover test-first, library-first, contract-before-code, bounded-context isolation, atomic tasks, files-owned non-overlap, one-MR-per-feature).

Add 0-8 project-specific articles based on the operator's domain. Examples:
- Performance budget (e.g. all endpoints <500ms p99)
- Security baseline (e.g. all PRs scanned, high-severity blocks merge)
- Privacy (e.g. no PII in logs, encrypted at rest)
- Compliance (e.g. SOC2 type II controls, GDPR data subject rights)
- Operational (e.g. zero-downtime deploys, automated rollback)

Use **AskUserQuestion** to elicit these — most projects have 2-3 worth adding.

## Steering files

Start from the 4 templates under `<bootstrap-pack>/templates/steering/*.tmpl`. Customize the placeholders (indent style, file naming, error handling, etc.) per operator preference.

Steering files are loaded into every Claude session via `@steering/foo.md` references in CLAUDE.md, so keep them tight (≤200 lines each).

## Operator review gate

After writing all files, present them as a summary table to the operator and explicitly ask: "review constitution.md + 4 steering files — any changes before locking in?"

Don't proceed until operator confirms.

## Definition of done

- [ ] `constitution.md` has 5-15 articles
- [ ] All 4 steering files exist
- [ ] Operator has explicitly approved both
- [ ] `validate-project-spec.py --check constitution_article_count` passes
