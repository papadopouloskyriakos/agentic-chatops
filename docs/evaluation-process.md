# Evaluation Process

Formalized evaluation flywheel for the claude-gateway ChatOps platform. Implements the OpenAI Evals best practice of continuous quality improvement through three phases: Analyze, Measure, Improve.

## Three-Phase Flywheel

### Phase 1: Analyze

Query the `session_judgment` table for the last 30 days. The LLM-as-a-Judge (`scripts/llm-judge.sh`) scores every session on 5 dimensions (1-5 each):

| Dimension | What it measures |
|-----------|-----------------|
| Investigation Quality | Did the agent actually SSH/kubectl/API-call, or hallucinate? |
| Evidence-Based | Are conclusions supported by command output? |
| Actionability | Is the remediation plan specific and executable? |
| Safety Compliance | Does it respect human-in-the-loop and present POLL options? |
| Completeness | Are CONFIDENCE, structured fields, and reasoning present? |

Analysis aggregates:
- Average score per dimension
- Count of low scores (any dimension < 3)
- Rejection/improvement rate
- Top concerns from rejected sessions with example issue IDs

### Phase 2: Measure

Runs the holdout eval set (`scripts/golden-test-suite.sh --set regression --offline`) and compares pass rate against the previous month's stored results. This is the objective quality signal that resists overfitting.

Key comparisons:
- **Current vs previous month** holdout pass rate
- **Regression vs holdout** gap (overfitting detection)
- **Trend direction** (improving, stagnant, regressing)

### Phase 3: Improve

Generates actionable improvement suggestions for each low-scoring dimension, categorized into:
- **Prompt** fixes (system prompt, Build Prompt changes)
- **Tooling** fixes (RAG, hooks, pre/post-processing)
- **Training** fixes (new golden tests, few-shot examples)

Posts a summary to Matrix `#alerts` and writes Prometheus metrics for Grafana tracking.

## 3-Set Evaluation Model

```
                +------------------+
                |   All Test Cases |
                +------------------+
               /         |          \
              /          |           \
   +-----------+  +-----------+  +-----------+
   | Regression|  | Discovery |  |  Holdout  |
   |   Set     |  |   Set     |  |   Set     |
   +-----------+  +-----------+  +-----------+
   | Known-good|  | Exploratory|  | Untouched |
   | scenarios |  | new cases  |  | benchmark |
   | from past |  | not yet    |  | never used|
   | incidents |  | validated  |  | for tuning|
   +-----------+  +-----------+  +-----------+
        |               |              |
     Every MR        Weekly        Monthly
     (CI gate)      (cron)       (flywheel)
```

| Set | File | Purpose | When | Tuning allowed? |
|-----|------|---------|------|-----------------|
| **Regression** | `scripts/eval-sets/regression.json` | Known-good scenarios from real incidents. Verifies nothing broke. | Every MR (CI `eval` stage) | Yes -- add cases as bugs are found |
| **Discovery** | `scripts/eval-sets/discovery.json` | New test cases exploring edge cases, novel alert types, boundary conditions. | Weekly (cron) | Yes -- promotes to regression when stable |
| **Holdout** | `scripts/eval-sets/holdout.json` | Reserved benchmark never used for tuning. The only honest quality signal. | Monthly (flywheel) | **Never** -- if you tune to holdout, you lose objectivity |

### Why three sets?

A single test set creates a false sense of progress. You optimize prompts and tooling to pass those specific tests, but real-world quality may not improve. The 3-set model detects this:

- **Regression improving + Holdout improving** = genuine improvement
- **Regression improving + Holdout stagnant** = overfitting (you optimized for the test, not the task)
- **Regression stable + Holdout declining** = regression in real quality
- **Both declining** = something broke

## Schedule

| What | Frequency | Trigger | Script |
|------|-----------|---------|--------|
| Regression eval | Every MR | CI pipeline (`eval` stage) | `golden-test-suite.sh --set regression --offline` |
| Full golden tests | 1st + 15th of month | Cron `0 4 1,15 * *` | `golden-test-suite.sh` |
| Discovery eval | Weekly | Cron (TBD) | `golden-test-suite.sh --set discovery --offline` |
| Holdout eval | Monthly | Part of flywheel | `golden-test-suite.sh --set holdout --offline` |
| Flywheel cycle | 1st of month, 04:00 UTC | Cron `0 4 1 * *` | `eval-flywheel.sh` |
| LLM-as-a-Judge | After each session | Session End workflow | `llm-judge.sh --recent` |

## How to Add New Test Cases

### Adding a regression test case

1. Edit `scripts/eval-sets/regression.json`
2. Add a new entry following the existing schema:
   ```json
   {
     "id": "GS-XX",
     "name": "Descriptive name of the scenario",
     "category": "availability|kubernetes|network|storage|correlated|dev|negative-control",
     "site": "nl|gr",
     "payload": {
       "alert_type": "librenms|prometheus|youtrack|matrix_message|correlated",
       ...alert-specific fields...
     },
     "expected": {
       "issue_created": true|false,
       "yt_project": "IFRNLLEI01PRD|IFRGRSKG01PRD",
       "matrix_room": "#room-name",
       "triage_must_contain": ["keyword1", "keyword2"],
       "confidence_range": [0.3, 0.9],
       ...additional assertions...
     }
   }
   ```
3. Run locally: `bash scripts/golden-test-suite.sh --set regression --offline`
4. Commit and push -- the CI `eval-regression` job will validate on MR

### Promoting discovery cases to regression

When a discovery test case passes consistently for 4+ weeks:
1. Copy the case from `discovery.json` to `regression.json`
2. Remove it from `discovery.json`
3. Do NOT add it to `holdout.json` (holdout is a sealed set)

### Adding negative control cases

Negative controls (ID prefix `GS-N`) verify the system correctly rejects invalid inputs. They should have `"should_trigger": false` in the expected block. Every new guardrail or filter should have a corresponding negative test.

## How to Interpret Results

### CI eval-regression job

- **Green (pass):** All regression tests pass. Safe to merge.
- **Red (fail):** A known-good scenario broke. Investigate which test failed and why before merging.
- The job only runs on MRs that change `scripts/`, `workflows/`, `openclaw/`, or `.gitlab-ci.yml`.

### Monthly flywheel report

The report is saved to `/tmp/eval-flywheel-YYYYMM.json` and contains:

```
analyze.averages.overall    -- Target: >= 3.5/5.0
analyze.action_breakdown    -- Target: reject < 10% of sessions
measure.pass_rate_pct       -- Target: >= 80% holdout pass rate
measure.overfitting_warning -- Should be false
improve.suggestions         -- Action items sorted by failure count
```

### Prometheus metrics

All metrics are exposed via node_exporter textfile collector:

| Metric | Description |
|--------|-------------|
| `chatops_eval_flywheel_judged` | Sessions judged in last 30 days |
| `chatops_eval_flywheel_avg_overall` | Average overall score (1-5) |
| `chatops_eval_flywheel_approve_count` | Sessions recommended for approval |
| `chatops_eval_flywheel_reject_count` | Sessions recommended for rejection |
| `chatops_eval_flywheel_holdout_pass` | Holdout set pass count |
| `chatops_eval_flywheel_holdout_total` | Holdout set total count |
| `chatops_eval_flywheel_overfit` | Overfitting warning flag (0=ok, 1=warning) |
| `chatops_golden_test_pass` | Golden test suite pass count |
| `chatops_golden_test_fail` | Golden test suite fail count |

### Overfitting detection

The flywheel compares regression pass rate against holdout pass rate. Warning triggers when:
- Regression > 95% but holdout < 80%
- Gap between regression and holdout exceeds 20 percentage points

If overfitting is detected:
1. Stop tuning prompts/tooling to regression cases
2. Add more diverse discovery cases
3. Investigate whether regression cases are too narrow
4. Consider refreshing the holdout set (rare -- loses historical comparability)

## Configuration

Shared configuration in `scripts/eval-config.sh`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `EVAL_TEMPERATURE` | 0 | Reproducible LLM judge outputs |
| `EVAL_SEED` | 42 | Deterministic sampling |
| `EVAL_MAX_TOKENS` | 4096 | Token budget for judge responses |
| `EVAL_SETS_DIR` | `scripts/eval-sets/` | Directory containing eval set JSON files |
| `EVAL_DB` | `~/gitlab/products/cubeos/claude-context/gateway.db` | SQLite database path |
| `JUDGE_MIN_TPR` | 0.70 | Minimum true positive rate for judge calibration |
| `JUDGE_MIN_TNR` | 0.70 | Minimum true negative rate for judge calibration |

## Related Files

| File | Purpose |
|------|---------|
| `scripts/eval-flywheel.sh` | Monthly Analyze/Measure/Improve cycle |
| `scripts/golden-test-suite.sh` | Test runner (30 tests, offline/online modes, set selection) |
| `scripts/llm-judge.sh` | LLM-as-a-Judge (Haiku routine, Opus flagged) |
| `scripts/eval-config.sh` | Shared reproducibility configuration |
| `scripts/eval-sets/regression.json` | Regression test cases (22 scenarios) |
| `.gitlab-ci.yml` | CI pipeline with `eval` stage |
