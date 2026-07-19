---
name: bootstrap
description: Meta-skill chaining /specify → /constitute → /plan → /tasks → spec-validation → dispatch-ready. Greenfield project from idea to parallel-dev-ready in one flow. Halts with clear remediation if any phase fails the DoD gate.
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, AskUserQuestion
---

# /bootstrap — greenfield project, idea → dispatch-ready

This is the orchestrator skill. It runs the 5-phase bootstrap sequence and halts cleanly at any phase-gate failure, with explicit instructions for the operator on how to remediate.

## Phases

```
A. (Conversational draft — already happened before /bootstrap was invoked)
B. /specify           → PROJECT.json + requirements.md (EARS) + acceptance/*.feature
                        (gates: ears_compliance, requirement_unique_ids, no_weasel_words)
C. /constitute        → constitution.md + steering/*.md
                        (gate: constitution_article_count + operator approval)
D. /plan              → design.md + data-model.md + contracts/* + adr/*
                        (gates: openapi_valid, asyncapi_valid, json_schemas_valid, adr_exists)
E. /tasks             → tasks.json
                        (gates: tasks_required_fields, tasks_dag_no_cycles,
                                parallelizable_no_file_collision, req_cross_references,
                                bounded_context_membership, risk_score_per_task)
F. Phase F validator  → all 17 checks must pass
G. Emit .agentic/slot-config.entry.json + youtrack-project.json + matrix-room.json
   Then print: "READY FOR DISPATCH" + the slot-config entry to append.
   On fail: print which checks failed + how to remediate.
```

## How to execute

You can invoke the sub-skills directly in sequence OR delegate each to a subagent (recommended for parallel-quality reviewing). The `spec-author`, `architect`, `task-decomposer` subagents wrap /specify, /plan, /tasks respectively; `spec-verifier` runs the final validator pass.

```
# Sequential approach (simpler)
/specify
/constitute
/plan
/tasks
<bootstrap-pack>/scripts/validate-project-spec.py .

# Subagent approach (one fresh context per phase, recommended for big projects)
Use the Agent tool, subagent_type=spec-author, prompt="Run /specify for this project"
Use the Agent tool, subagent_type=architect,   prompt="Run /plan based on the existing requirements + PROJECT.md"
Use the Agent tool, subagent_type=task-decomposer, prompt="Run /tasks based on existing design + contracts"
Use the Agent tool, subagent_type=spec-verifier,   prompt="Run validate-project-spec.py and report any gaps"
```

## Phase F gate

The final gate is the comprehensive validator:

```bash
<bootstrap-pack>/scripts/validate-project-spec.py . --json > /tmp/dod-report.json
```

If ALL 17 checks pass: print the slot-config.entry.json content with instructions to append it to `gateway-state/slot-config.json`. Operator then runs `project-onboard.sh .` to dispatch.

If ANY check fails: print the failure-mode dictionary (see `docs/runbooks/spec-lint-failures.md`) entry for that check + remediation steps. STOP.

## Definition of done

- [ ] All 17 validator checks pass
- [ ] `.agentic/slot-config.entry.json` exists + non-duplicate vs existing gateway-state slots
- [ ] Operator has run `project-onboard.sh .` and seen "READY FOR DISPATCH"
