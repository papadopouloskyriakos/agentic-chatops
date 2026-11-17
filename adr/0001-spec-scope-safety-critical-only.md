# 0001 — Spec scope: safety-critical surfaces only, not the whole estate

- Status: accepted
- Date: 2026-06-23
- Context issue: IFRNLLEI01PRD-1260

## Context

The Google 5-Day AI Agents benchmark (Source #10) scores spec-driven development on the
thesis "the spec is the source of truth and code is disposable / regenerable." Applied
literally, that would require making the entire claude-gateway estate — roughly 71,000
lines of operational code across 35.5k Python, 28k shell, 6.6k n8n jsCode, and 981 SQL,
plus 442 n8n nodes bound to live infrastructure state — regenerable from a reviewed spec.

## Decision

We adopt spec-driven discipline for the **safety-critical behavioral surfaces** (risk
classification, the fail-closed prediction gate, auto-resolve, governance auto-demote,
tier-1 suppression) and the **real component interfaces** (HTTP webhooks, the event bus,
the persistent SQLite schema). We do **not** make the full estate regenerable from spec.

## Consequences

- The contract and behavioral surfaces gain machine-validated EARS requirements, Gherkin
  acceptance, and OpenAPI/AsyncAPI/JSON-Schema contracts under continuous enforcement.
- The "code is disposable" framing is recorded as product-development framing that does
  not fit an operations platform whose source of truth is its code plus live state.
- The legacy free-prose `*-SPEC.md` files are superseded by the EARS spec and marked
  deprecated.
