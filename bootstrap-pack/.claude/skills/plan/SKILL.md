---
name: plan
description: Phase D of greenfield project bootstrap. Produce design.md + data-model.md + contracts/{openapi,asyncapi,schemas/*} + adr/NNNN-*.md. Validates contracts via swagger-cli/asyncapi/ajv before exit.
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Glob
---

# /plan — design + contracts + ADRs

After `/constitute` locked in non-negotiables, this skill produces the technical design that workers will implement.

## Artifacts to produce

1. `spec/001-<slug>/design.md` — architecture overview, sequence diagrams (mermaid), error handling strategy
2. `spec/001-<slug>/data-model.md` — entities, relationships, persistence shape
3. `spec/001-<slug>/contracts/openapi.yaml` — sync API contracts (HTTP endpoints)
4. `spec/001-<slug>/contracts/asyncapi.yaml` — event contracts (queues/topics)
5. `spec/001-<slug>/contracts/schemas/*.json` — shared JSON Schema for data shapes
6. `adr/NNNN-<decision>.md` — one MADR file per arguable architectural choice

## Templates

`<bootstrap-pack>/templates/{design.md,data-model.md,openapi.yaml,asyncapi.yaml,adr-0001-record-architecture-decisions.md}.tmpl`

## Validation

Before exit, run:

```bash
# Each contracts file must parse
npx swagger-cli validate spec/001-*/contracts/openapi.yaml
npx @asyncapi/cli validate spec/001-*/contracts/asyncapi.yaml
for f in spec/001-*/contracts/schemas/*.json; do
  npx ajv-cli compile -s "$f"
done

# Validator-gate checks
<bootstrap-pack>/scripts/validate-project-spec.py . --check openapi_valid
<bootstrap-pack>/scripts/validate-project-spec.py . --check asyncapi_valid
<bootstrap-pack>/scripts/validate-project-spec.py . --check json_schemas_valid
<bootstrap-pack>/scripts/validate-project-spec.py . --check adr_exists
```

If any contract fails to parse, iterate until clean.

## ADR criteria

Write an ADR for any choice the operator (or a future contributor) might argue about in 6 months:
- Database choice (Postgres vs Mongo vs SQLite)
- Auth mechanism (JWT vs OAuth2 vs mTLS)
- Message bus (NATS vs Kafka vs Redis Streams)
- Frontend framework
- Deployment target (K8s vs containers-on-VMs vs serverless)
- Significant library choice with alternatives

Each ADR has: Status, Context, Decision, Consequences (positive + negative), Alternatives considered.

## Definition of done

- [ ] All 6 artifact categories exist
- [ ] All contract files parse cleanly
- [ ] At least one ADR exists (always include ADR-0001 from template)
- [ ] Operator has skimmed design.md + reviewed top-level architecture

## What's next

Operator runs `/tasks` to atomize the design into the work_units that parallel-dev workers will execute.
