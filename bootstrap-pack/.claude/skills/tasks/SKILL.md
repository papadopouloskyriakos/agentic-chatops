---
name: tasks
description: Phase E of greenfield project bootstrap. Atomize design.md + contracts into tasks.json with files_owned + dependencies + acceptance_test + risk_score per task. Iterates until task-dag-validate passes.
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash
---

# /tasks — atomize design into parallel-dev work_units

After `/plan` produced design.md + contracts, this skill decomposes the work into atomic tasks suitable for ≤4 parallel Claude workers.

## Output

`spec/001-<slug>/tasks.json` per `<bootstrap-pack>/templates/tasks.schema.json`.

## Atomization rules (load-bearing)

For each task you write:

1. **files_owned** — exact file paths (relative to repo root) the task will create or modify. Must be non-empty. NEW files OK.
2. **dependencies** — list of task_ids this task depends on. Empty list = wave-0 task.
3. **parallelizable** — `true` if it can run alongside other tasks in the same wave; `false` if it needs exclusive write access.
4. **acceptance_test** — executable command (e.g. `go test ./... -run TestFoo`) that returns exit 0 iff the task succeeded. NOT prose.
5. **bounded_context** — exactly one value from `PROJECT.json#bounded_contexts`.
6. **requirement_ids** — list of REQ-NNN this task fulfills (must exist in `requirements.md`).
7. **risk_score** — 0.0 to 1.0. >0.7 triggers needs-human auto-merge gate.
8. **complexity** — 1 to 10. >5 should be split.

## Hard constraints (rejected at validation time)

- No two `parallelizable: true` tasks in the same wave may share any `files_owned` entry. The validator's `parallelizable_no_file_collision` catches this.
- Dependency graph must be acyclic (`tasks_dag_no_cycles`).
- Every `requirement_ids` entry must exist (`req_cross_references`).
- Max 4 parallel tasks per wave (matches MAX_WORKERS in parallel-dev).

## Validation loop

After writing tasks.json, run:

```bash
<bootstrap-pack>/scripts/validate-project-spec.py . --check tasks_required_fields
<bootstrap-pack>/scripts/validate-project-spec.py . --check tasks_dag_no_cycles
<bootstrap-pack>/scripts/validate-project-spec.py . --check parallelizable_no_file_collision
<bootstrap-pack>/scripts/validate-project-spec.py . --check req_cross_references
<bootstrap-pack>/scripts/validate-project-spec.py . --check bounded_context_membership
<bootstrap-pack>/scripts/validate-project-spec.py . --check risk_score_per_task
```

If any fail, iterate. Don't exit until all 6 pass.

## Template

`<bootstrap-pack>/templates/tasks.json.tmpl` shows the per-task schema.

## Definition of done

- [ ] tasks.json exists at spec/001-*/
- [ ] All 6 task-related validator checks pass
- [ ] No more than 4 parallelizable tasks per wave
- [ ] Operator has reviewed the decomposition + accepted

## What's next

Operator runs `/bootstrap` (meta-skill) which chains all of /specify → /constitute → /plan → /tasks → validator, or directly runs `project-onboard.sh` to register the project with the gateway.
