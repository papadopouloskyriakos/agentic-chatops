# Changelog

All notable changes to claude-gateway are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This file is required by
Article I of the constitution and the D2 spec-driven slice (IFRNLLEI01PRD-1260).

## [Unreleased]

### Added
- Spec-driven development for the safety-critical surfaces: root `PROJECT.json`,
  `constitution.md` (7 articles), and `spec/` tree (EARS requirements + Gherkin
  acceptance + OpenAPI/AsyncAPI/JSON-Schema contracts) for the risk-classification,
  prediction-gate, auto-resolve, governance, tier1-suppression, and interfaces contexts.
- `AGENTS.md` root entry point for coding agents.
- `scripts/check-spec-code-lockstep.py` — spec↔code traceability guard.
- QA suite `test-1260-spec-driven.sh` — runs the validator against good/bad fixtures
  and the gateway's own spec (closes the missing-fixture-runner debt).
- CI `validate_spec` job and a holistic-health section enforcing the spec gate continuously.
- **Round 2 — executable BDD**: `scripts/run-spec-bdd.py` + `spec/steps/` execute every Gherkin
  scenario against real code (the classifier, the SQLite schema, the blast-radius matcher) — an
  unbound step is a hard failure, so no scenario is cosmetic. 14/14 scenarios pass.
- **Round 2 — content-aware lockstep**: `check-spec-code-lockstep.py` now records a content-hash
  manifest (`spec/.lockstep.lock`); a governed safety file changing without its spec being updated
  is reported as drift and fails the gate (`--update-manifest` re-stamps). Existence-only → drift-aware.
- **Round 2 — practiced red-green**: the content-drift behavior was authored spec-first as a new
  bounded context `spec-governance` (REQ-701..703 + `drift.feature`); its scenarios were RED (0/2)
  before the detector existed and GREEN (2/2) after — a genuine spec→failing-test→code cycle.
- **Round 3 — hardened marquee scenario**: the irreversible safety-floor BDD step now forces the
  band engine on (hermetically, SMS to a dead endpoint) and asserts strict `risk==high` +
  `POLL_PAUSE` + irreversible signal + `sms_required`, so deleting the irreversible re-tagging now
  fails the suite (proven 13/14). It no longer passes vacuously.
- **Round 3 — semantic-content lockstep (REQ-704)**, shipped as an *auditable* red-green (a RED
  commit with the failing spec/scenario, then a GREEN commit with the implementation): the spec
  hash now covers only requirement statements + Gherkin structure, so a cosmetic spec edit cannot
  clear genuine code drift.

### Changed
- `bootstrap-pack/scripts/validate-project-spec.py`: real Python Gherkin structural
  parser (C14), offline npx-free OpenAPI/AsyncAPI validation fallback (C06/C07), and
  deep `slot-config.entry.json` validation (C16).
