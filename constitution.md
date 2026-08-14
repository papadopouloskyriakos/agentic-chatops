# Claude Gateway Constitution

The governing articles every agentic change to this platform obeys. These encode
invariants the running system already enforces in code; this file makes them the
reviewed source of truth. Derived as the D2 (spec-driven development) slice of the
Google 5-Day AI Agents benchmark (IFRNLLEI01PRD-1260).

## Article I — Test-First Imperative

Every safety-critical behavior has an executable acceptance specification (a Gherkin
`.feature` referencing an EARS `REQ-NNN`) before its code is changed. A change that
weakens or deletes a safety acceptance test without replacing it is rejected. Tests
fail before the behavior exists and pass after.

## Article II — Contract-Before-Code

Every interface between components — the n8n webhook surface, the alert/event surface,
and the persistent SQLite surface — is described by a machine-validated contract
(OpenAPI, AsyncAPI, JSON-Schema) kept in `spec/`. A payload-shape change lands in the
contract in the same commit as the code.

## Article III — Fail-Closed on Safety

When a safety gate cannot evaluate its inputs, it denies rather than allows. The
infragraph prediction gate refuses an approval poll without a committed prediction;
the risk classifier forces the highest band on parse failure. Absence of evidence is
treated as denial, never as permission.

## Article IV — Human as Circuit-Breaker

Autonomy is risk-tiered, not all-or-nothing. Reversible, predicted, low-risk actions
auto-resolve; irreversible, unpredicted, or high-risk actions pause for a human and
page over SMS. The human is a circuit-breaker for the decisions that matter, never a
per-action gatekeeper.

## Article V — Proving-Your-Work

A confidence assertion at or above 0.8 is paired with visible, file-grounded evidence.
A claim of a passing test is accompanied by the command output that proves it.

## Article VI — Reversibility and Kill-Switch

Every autonomous capability has a single-action off switch (a sentinel file removal, a
flag, a closed control issue) that reverts to byte-identical prior behavior. A capability
without a kill-switch is not enabled by default.

## Article VII — Spec-Code Lockstep

Every safety-critical implementation file is owned by exactly one spec task, and every
spec task names files that exist. Drift between the spec and the code it governs fails
the continuous-validation gate.
