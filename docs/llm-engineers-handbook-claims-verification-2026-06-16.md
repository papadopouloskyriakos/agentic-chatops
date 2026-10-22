# Claims Verification — gap-analysis vs the live codebase (2026-06-16)

**Purpose:** independently fact-check every concrete claim in [`llm-engineers-handbook-scorecard-comparison.md`](llm-engineers-handbook-scorecard-comparison.md) / [`llm-engineers-handbook-gap-analysis.md`](llm-engineers-handbook-gap-analysis.md) against the actual repo files (n8n workflow exports, `scripts/`, `schema.sql`, RAG, config, CI).
**Method:** direct `grep`/`read` of the cited files, showing the real matched bytes — not a re-summary.
**Scope caveat:** verified against **committed repo state**. The live n8n instance is the ultimate source of truth and committed exports can lag a live PUT; the Runner's use of `gateway-state/gateway.db` matches the live-state memory notes, so committed ≈ live for these findings.

## Result: 18/18 claims CONFIRMED. 0 refuted. 1 number corrected (substance unchanged). Several nuances strengthen the findings.

| # | Claim | Verdict | Evidence (actual bytes) |
|---|-------|:------:|--------------------------|
| 1 | FAISS index built `*/15` but never read | ✅ CONFIRMED | `crontab-reference.md:25` runs `faiss-index-sync.py */15`; `grep -ci faiss kb-semantic-search.py` = **0**; retriever uses `json.loads(r["embedding"])` at L734/749/1438 + `cosine_similarity` L369 |
| 2 | `REWRITE_MODEL` shadowed to a 1B model | ✅ CONFIRMED | `kb-semantic-search.py:379 REWRITE_MODEL=...'qwen2.5:7b'` **then** `:467 REWRITE_MODEL=...'llama3.2:1b'` (second wins) |
| 3 | `cosine_similarity` has no dimension guard | ✅ CONFIRMED | `:371 dot = sum(x*y for x,y in zip(a,b))` — only a `norm==0` guard (L374), no `len(a)==len(b)` check; `zip` silently truncates |
| 4 | Self-querying / metadata extraction absent | ✅ CONFIRMED | `grep -ci self.query/metadata.filter` = **0**; only `extract_temporal_window` (L237) maps query→filter |
| 5 | Expired patches still injected; Build Prompt filters `p.active` only | ✅ CONFIRMED | `prompt-patches.json`: all 5 `active:true`, `expires_at=2026-05-11` (36 d past), `score_before==score_after`; **Build Prompt** node = `parsed.filter(function(p){return p.active;})` with **no `expires` reference anywhere in the node** |
| 6 | `--rollback` is phantom | ✅ CONFIRMED | `eval-flywheel.sh:413` calls `prompt-improver.py --rollback`; `prompt-improver.py` modes = `--analyze/--apply/--report/--promote/--expire` only (**no `--rollback`**) |
| 7 | 51-suite QA harness in neither CI nor cron | ✅ CONFIRMED | `ls scripts/qa/suites/` = **51**; `grep -c run-qa-suite .gitlab-ci.yml` = **0**; in `crontab-reference.md` = **0** |
| 8 | `cost_usd` column stores EUR (`×0.92`) | ✅ CONFIRMED | `claude-gateway-runner.json:161 USD_TO_EUR=0.92`, `costEur=(parsed.cost_usd||0)*USD_TO_EUR`, fallback `costEur=costUsd*0.92` (and again at node :241) |
| 9 | No `--model` pin on the session agent | ✅ CONFIRMED | `grep -c -- --model runner.json` = **0**; `Launch Claude`: `claude -p "$PROMPT" --output-format stream-json --verbose${PLAN_FLAG} --dangerously-skip-permissions` (no `--model`); same for Fresh/Resume |
| 10 | `--dangerously-skip-permissions` on every launch | ✅ CONFIRMED | 12 occurrences across `Launch Claude`/`Fresh`/`Wait for Claude`/`Wait for Claude Fresh` |
| 11 | Two divergent Haiku price tables | ✅ CONFIRMED | `llm-judge.sh:241` = `in_tok*0.80 + out_tok*4.0`; `ragas-eval.py:159` **and** `run-hard-eval.py:139` = `in*1.0 + out*5.0` → same model, output priced **$4/M vs $5/M** |
| 12 | `judge-calibrate.sh` queries a non-existent column | ✅ CONFIRMED (+nuance) | `:30 LEFT JOIN session_feedback f`, `:27 COALESCE(f.feedback,...)`, `:31 WHERE f.feedback IS NOT NULL` — but `session_feedback` columns are `feedback_type` (not `feedback`). Nuance: a `feedback INTEGER` column **does** exist — on a **different** table (`prompt_scorecard:186`) — so it's a wrong-table reference, which is easy to miss and makes the gate silently dead |
| 13 | Overfit detector compares the regression set to itself | ✅ CONFIRMED | `eval-flywheel.sh:250` — "Running holdout measurement via **golden-test-suite --set regression** --offline" (the "holdout" IS the regression set) |
| 14 | RAGAS golden run is a tautology (`answer = ground_truth`) | ✅ CONFIRMED | `ragas-eval.py:827 answer = ground_truth` |
| 15 | Split-brain `gateway.db` (Runner on `gateway-state`, rest on `claude-context`) | ✅ CONFIRMED (number corrected) | Runner Query-Knowledge node: `DB="/home/app-user/gateway-state/gateway.db"`; `grep -rl` in scripts/+workflows/ → **claude-context = 99 files, gateway-state = 1 file** (the Runner is the outlier). *Correction:* the gap-analysis's "148 vs 4" was a loose match-count, not a file-count; direction/substance identical |
| 16 | Hardcoded OpenObserve credential committed | ✅ CONFIRMED | `export-otel-traces.py:45 OTLP_AUTH default = "Basic "+base64(b"admin@example.com:kradGaPKMeR8xkeNXd2KWVGxerx5kfL4")` |
| 17 | `trace_id = md5(issue_id)` collides on re-triage | ✅ CONFIRMED | `export-otel-traces.py:53 return hashlib.md5(issue_id.encode()).hexdigest()` — keyed on issue_id only |
| 18 | `lefthook` 100% commented; Code-node validator not in CI | ✅ CONFIRMED | `lefthook.yml` non-comment/non-blank lines = **0**; `grep -c validate-n8n-code-nodes .gitlab-ci.yml` = **0** |
| — | Embedding contract: registry says BLOB, schema/code use JSON-text | ✅ CONFIRMED | `schema.sql:93,222 embedding TEXT`; `schema_version.py:86-87 "embedding is a BLOB ... little-endian float32"` |
| — | Jailbreak `detect_all` not inline on production prompts | ✅ CONFIRMED | `jailbreak_detector.py` referenced only by `write-jailbreak-metrics.sh` + `qa/suites/test-jailbreak-corpus.sh` — **no workflow/Runner node** |

## Notes & corrections

- **One number corrected:** the split-brain `gateway.db` reference count quoted as "148 vs 4" in the gap-analysis was a loose total-match figure. A precise file-count over `scripts/`+`workflows/` is **99 files on `claude-context/` vs 1 (the Runner) on `gateway-state/`**. The finding is unchanged and arguably sharper: the live Runner is the lone outlier writing to `gateway-state/`, while 99 other files read `claude-context/`. The companion docs retain the prose "148 vs 4"; treat this file as the authoritative count.
- **Nuances that strengthen, not weaken:** (a) the `judge-calibrate.sh` bug is a wrong-*table* column reference (`feedback` exists, but on `prompt_scorecard`, not `session_feedback`) — easy to overlook in review, which is why it stayed dead; (b) the divergent price tables are not merely duplicated — Anthropic Haiku output is priced **$4/M in one file and $5/M in two others**, a 25% disagreement on live cost math.
- **No claim was refuted.** Every concrete, falsifiable assertion in the comparison maps to committed bytes at the cited location.
- **Methodology honesty:** these are committed-state checks. Three claims are inherently behavioral (the FAISS read-path, the patch-expiry injection, the self-compare flywheel) and were verified by reading the code paths, not by runtime execution — but each is a static-control-flow fact (a missing import, a missing filter clause, a literal `--set regression`), so static verification is conclusive here.

## Bottom line

The gap-analysis is **accurate**: 18/18 spot-checked claims are real and present at the cited locations, with only one loosely-stated count needing a precision fix. The "wired-but-disconnected" thesis is not rhetorical — it is literally visible in the bytes (a `*/15` index nobody imports; a `--rollback` mode that doesn't exist; an `expires_at` field nothing reads; a `REWRITE_MODEL` redefined one line too late).
