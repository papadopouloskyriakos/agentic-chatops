# Runbook: fix Phase F validator failures

When `bootstrap-pack/scripts/validate-project-spec.py` reports a failure, look up the check name here for the remediation recipe.

---

## C01 — `project_json_schema`

**What failed:** PROJECT.json is missing or has wrong shape.

**Fix:**
1. Check the JSON parses: `python3 -m json.tool PROJECT.json`
2. Copy missing fields from `bootstrap-pack/templates/PROJECT.json.tmpl`
3. Required: `slug, title, youtrack_prefix, matrix_room, primary_language, test_command, lint_command, bounded_contexts, max_parallel_workers, owners, risk_profile`

---

## C02 — `constitution_article_count`

**What failed:** `constitution.md` has fewer than 5 or more than 15 `# Article ...` headers.

**Fix:** add or split articles. Start from the 7-article template at `bootstrap-pack/templates/constitution.md.tmpl`. Each article must start with `# Article <RomanNumeral>` exactly.

---

## C03 — `ears_compliance`

**What failed:** A line starting with `REQ-NNN:` in `requirements.md` doesn't match any of the 5 EARS patterns.

**Fix:** rewrite the line into one of the 5 templates:

| Pattern | Template |
|---|---|
| Ubiquitous | `REQ-NNN: The <subject> shall <response>.` |
| Event-driven | `REQ-NNN: When <trigger>, the <subject> shall <response>.` |
| State-driven | `REQ-NNN: While <precondition>, the <subject> shall <response>.` |
| Optional | `REQ-NNN: Where <feature included>, the <subject> shall <response>.` |
| Unwanted | `REQ-NNN: If <trigger>, then the <subject> shall <response>.` |

Common mistakes:
- Missing terminating period → required by regex
- "The X should be fast" — `should` is too soft, use `shall`. Also "fast" isn't testable; use a quantified threshold ("shall respond in <500ms p99").
- Multi-clause: "When X, the system shall Y, and also Z." → split into two REQ-NNNs
- "TODO" in the line → that's caught by C05 weasel-words too

Delegate to `spec-author` subagent if you want it auto-fixed iteratively.

---

## C04 — `requirement_unique_ids`

**What failed:** Two REQ-NNN lines use the same number.

**Fix:** renumber. Run `grep -h '^REQ-' spec/*/requirements.md | sort | uniq -d` to find duplicates.

---

## C05 — `no_weasel_words`

**What failed:** Found a forbidden word: `TODO`, `TBD`, `FIXME`, `should be`, `various`, `etc.`, `might`, `maybe`.

**Fix:** replace with concrete language. Examples:
- "should be fast" → "shall respond in less than 500ms p99"
- "TODO: figure out caching" → either resolve and write the requirement, or remove the line (defer the work to a later feature)
- "various error states" → enumerate them explicitly

---

## C06 / C07 / C08 — `openapi_valid` / `asyncapi_valid` / `json_schemas_valid`

**What failed:** One or more contract files don't validate.

**Fix:**
```bash
npx swagger-cli validate spec/001-*/contracts/openapi.yaml
npx @asyncapi/cli validate spec/001-*/contracts/asyncapi.yaml
for f in spec/001-*/contracts/schemas/*.json; do npx ajv-cli compile -s "$f"; done
```

Each command prints which line fails. Common issues:
- Missing `openapi: 3.x.x` version
- Schema referenced via `$ref` but not defined under `components/schemas/`
- Trailing tabs/spaces in YAML breaking indent

Templates at `bootstrap-pack/templates/{openapi,asyncapi}.yaml.tmpl` parse cleanly.

---

## C09 — `tasks_required_fields`

**What failed:** A task in tasks.json is missing one of the required fields: `task_id, title, dependencies, parallelizable, files_owned, requirement_ids, bounded_context, acceptance_test, risk_score`.

**Fix:** copy the template at `bootstrap-pack/templates/tasks.json.tmpl` and fill in every field. Field types matter:
- `dependencies`: must be a JSON array (use `[]` for no deps, not `null`)
- `files_owned`: must be a JSON array of strings, non-empty
- `parallelizable`: boolean (`true`/`false`)
- `risk_score`: number in [0, 1]

---

## C10 — `tasks_dag_no_cycles`

**What failed:** Tasks form a dependency cycle (e.g. T-001 depends on T-002 which depends on T-001).

**Fix:**
1. Run the validator with `--check tasks_dag_no_cycles` to see the cyclic task ids
2. Break the cycle: usually one of the deps is wrong/spurious. Re-read each task's `dependencies` and ask "do I really NEED this dep to complete before mine starts?"
3. If you genuinely need both directions, your decomposition is wrong — combine them into one larger task and `parallelizable: false`.

---

## C11 — `parallelizable_no_file_collision`

**What failed:** Two tasks with `parallelizable: true` at the same dependency depth share at least one path in `files_owned`.

**Fix (three options, pick one):**
1. **Serialize them:** make one depend on the other (`dependencies: ["T-001"]`). They become different waves; no collision.
2. **Disable parallelism:** set `parallelizable: false` on one. It still runs in the same wave but exclusively.
3. **Refactor file boundaries:** split the shared file into two so each task owns its own. Often a sign that the original file was doing too much.

The validator prints which 2 task_ids + which file(s) collide. Most often the fix is to make a sequential helper task (e.g. "T-000: create shared interface" that T-001 + T-002 both depend on, then they don't fight over the interface file).

---

## C12 — `req_cross_references`

**What failed:** A task's `requirement_ids` references a REQ-NNN that doesn't exist in any requirements.md, OR the list is empty.

**Fix:**
- Empty list → every task must implement at least one REQ. If you can't think of one, this task probably shouldn't exist (it's not user-visible). Or: add the missing REQ to requirements.md.
- Unknown REQ → typo in the task's reference. Compare against `grep -h '^REQ-' spec/*/requirements.md`.

---

## C13 — `bounded_context_membership`

**What failed:** A task's `bounded_context` value isn't in `PROJECT.json#bounded_contexts`.

**Fix:** either:
- Change the task's `bounded_context` to a valid one
- Or add the context to `PROJECT.json#bounded_contexts` if it's a legitimate new boundary

---

## C14 — `gherkin_parseable`

**What failed:** A `.feature` file under `acceptance/` doesn't have both `Feature:` and `Scenario:` keywords, OR doesn't reference any REQ-NNN.

**Fix:** copy the template at `bootstrap-pack/templates/gherkin.feature.tmpl`. Every feature file needs:
- One `Feature:` header
- At least one `Scenario:` block
- The REQ-NNN(s) the scenarios prove, mentioned anywhere in the file

---

## C15 — `adr_exists`

**What failed:** `adr/` directory missing or has no MADR-format files (`NNNN-*.md`).

**Fix:** at minimum, copy `bootstrap-pack/templates/adr-0001-record-architecture-decisions.md` to `adr/0001-record-architecture-decisions.md`. Add more as architectural decisions emerge.

---

## C16 — `slot_config_entry_valid`

**What failed:** `.agentic/slot-config.entry.json` is missing, doesn't parse, or has empty content.

**Fix:** the `/bootstrap` meta-skill should generate this. If you ran phases manually and skipped it:

```bash
SLUG=$(jq -r .slug PROJECT.json)
CWD=$(pwd)
ROOM=$(jq -r .matrix_room PROJECT.json)
mkdir -p .agentic
jq -n --arg slug "$SLUG" --arg cwd "$CWD" --arg room "$ROOM" \
  '{($slug): {cwd: $cwd, room: $room}}' > .agentic/slot-config.entry.json
```

---

## C17 — `risk_score_per_task`

**What failed:** A task is missing `risk_score`, or it's not in [0, 1].

**Fix:**
- Missing → add (subjective but consistent): 0.0-0.3 pure addition, 0.3-0.5 small mod, 0.5-0.7 multi-file, 0.7-1.0 critical infra
- Out of range → clamp to [0, 1]. Higher than 1 is meaningless.

>0.7 will gate auto-merge in the merge-coordinator. Score honestly.

---

## When the validator output is confusing

Run with `--check <specific_name>` to isolate one check at a time:

```bash
bootstrap-pack/scripts/validate-project-spec.py . --check ears_compliance
```

Or `--json` for machine-readable output:

```bash
bootstrap-pack/scripts/validate-project-spec.py . --json | jq '.results[] | select(.passed==false)'
```

The Phase F gate is `validate-project-spec.py .` (no `--check`) returning exit 0 = `17/17 checks passed`. Anything less = the project is NOT yet ready for parallel-dev dispatch.
