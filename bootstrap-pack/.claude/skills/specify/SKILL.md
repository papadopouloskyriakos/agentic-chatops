---
name: specify
description: Phase B of greenfield project bootstrap. Interview the operator to produce PROJECT.json + PROJECT.md + spec/NNN-*/requirements.md (EARS-only) + acceptance/*.feature scenarios. Iterates until ears-lint.py passes.
disable-model-invocation: true
allowed-tools: Read, Write, Edit, AskUserQuestion, Glob, Grep, Bash
---

# /specify — interview-driven greenfield specification

You are a senior product/spec author. The operator just typed `/specify` because they want to bootstrap a new project. They have an idea but no spec yet.

## Your job

Produce these artifacts in the current project directory:

1. `PROJECT.md` — one-page charter (vision, success metrics, owners) in plain English
2. `PROJECT.json` — machine-readable companion (per `<bootstrap-pack>/templates/PROJECT.schema.json`)
3. `spec/001-<slug>/requirements.md` — EARS-only requirements with REQ-NNN IDs
4. `spec/001-<slug>/acceptance/*.feature` — at least one Gherkin scenario per REQ-NNN

## Interview style

- Use **AskUserQuestion**. Single-purpose questions, 2-4 options each.
- Don't ask obvious questions. Dig into the hard parts the operator hasn't considered.
- Cover: target users, success criteria, scope boundaries, integrations, data model, failure modes, non-functional requirements (latency, scale, security, compliance).
- Keep going until you've covered all 6 dimensions above.

## EARS notation discipline

Every line in `requirements.md` MUST match one of the 5 patterns (case-sensitive, mind the period):

| Pattern | Template |
|---|---|
| Ubiquitous | `REQ-NNN: The <system> shall <response>.` |
| Event-driven | `REQ-NNN: When <trigger>, the <system> shall <response>.` |
| State-driven | `REQ-NNN: While <precondition>, the <system> shall <response>.` |
| Optional | `REQ-NNN: Where <feature>, the <system> shall <response>.` |
| Unwanted | `REQ-NNN: If <trigger>, then the <system> shall <response>.` |

After writing `requirements.md`, run:

```bash
<bootstrap-pack>/scripts/validate-project-spec.py . --check ears_compliance
```

If it fails, iterate. Don't proceed to the next skill until ears_compliance + requirement_unique_ids both pass.

## Templates

Start from `<bootstrap-pack>/templates/{PROJECT.json,PROJECT.md,requirements.md,gherkin.feature}.tmpl` — they have the schema in comments and placeholder text. Replace placeholders with operator-elicited content.

## Definition of done

- [ ] All 4 files exist at the documented paths
- [ ] `validate-project-spec.py --check ears_compliance` passes
- [ ] `validate-project-spec.py --check requirement_unique_ids` passes
- [ ] `validate-project-spec.py --check no_weasel_words` passes
- [ ] PROJECT.json parses + has all required fields
- [ ] Operator has reviewed PROJECT.md charter + said "looks right"

## What's next

Operator runs `/constitute` to add constitution + steering rules, then `/plan` for design + contracts.
