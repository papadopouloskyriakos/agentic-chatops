#!/usr/bin/env bash
# IFRNLLEI01PRD-1267 — D16 closed-loop self-improvement:
#   S1 architect decomposition (run_decomposition no longer a stub)
#   S2 holdout-regated human-review checkpoint on the live prompt self-mod loop
#   S3 failure->eval miner (loop closure back into the discovery eval set)
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1267-self-improvement"

PD="$REPO_ROOT/scripts/parallel-dev/planner-decompose.py"
BPD="$REPO_ROOT/bootstrap-pack/scripts/planner-decompose.py"
PPT="$REPO_ROOT/scripts/lib/prompt_patch_trial.py"
MINER="$REPO_ROOT/scripts/mine-failures-to-evals.py"
APPLY="$REPO_ROOT/scripts/apply-prompt-promotion.py"

# ─── S1: run_decomposition is implemented in BOTH lanes (no NotImplementedError) ─
for f in "$PD" "$BPD"; do
  start_test "run_decomposition_not_a_stub_$(basename "$(dirname "$f")")"
    out=$(python3 - "$f" <<'PY'
import importlib.util, sys, os
spec=importlib.util.spec_from_file_location("pd", sys.argv[1])
pd=importlib.util.module_from_spec(spec); sys.modules["pd"]=pd; spec.loader.exec_module(pd)
os.environ["PATH"]="/nonexistent"  # claude unavailable
try:
    pd.run_decomposition("F-1","/tmp","build a thing"); print("NORAISE")
except NotImplementedError: print("NOTIMPL")
except RuntimeError: print("RUNTIME_FAILSAFE")
except Exception as e: print("OTHER:"+type(e).__name__)
PY
)
    assert_eq "RUNTIME_FAILSAFE" "$out" "claude-missing yields RuntimeError fail-safe, not NotImplementedError"
  end_test
done

# ─── S1: extracts a fenced json DAG and validates it ────────────────────────
start_test "decomposition_extracts_and_validates_dag"
  out=$(python3 - "$PD" <<'PY'
import importlib.util, sys, json
spec=importlib.util.spec_from_file_location("pd", sys.argv[1])
pd=importlib.util.module_from_spec(spec); sys.modules["pd"]=pd; spec.loader.exec_module(pd)
reply='```json\n'+json.dumps({"tasks":[
 {"task_id":"T-1","title":"a","files_owned":["a.py"],"prompt":"p","acceptance_test":"t","dependencies":[],"parallelizable":True,"bounded_context":"c"},
 {"task_id":"T-2","title":"b","files_owned":["b.py"],"prompt":"p","acceptance_test":"t","dependencies":["T-1"],"parallelizable":False,"bounded_context":"d"}]})+'\n```'
tasks=pd._extract_tasks(reply)
errs=pd.validate_work_units("F",tasks)
print(f"{len(tasks)}|{len(errs)}")
PY
)
  assert_eq "2|0" "$out" "extracts 2 tasks, validates clean DAG"
end_test

# ─── S1: a cyclic / colliding decomposition is rejected ─────────────────────
start_test "decomposition_rejects_invalid_dag"
  out=$(python3 - "$PD" <<'PY'
import importlib.util, sys, json
spec=importlib.util.spec_from_file_location("pd", sys.argv[1])
pd=importlib.util.module_from_spec(spec); sys.modules["pd"]=pd; spec.loader.exec_module(pd)
cyclic=[{"task_id":"T-1","title":"a","files_owned":["a.py"],"prompt":"p","acceptance_test":"t","dependencies":["T-2"],"parallelizable":True,"bounded_context":"c"},
        {"task_id":"T-2","title":"b","files_owned":["b.py"],"prompt":"p","acceptance_test":"t","dependencies":["T-1"],"parallelizable":True,"bounded_context":"d"}]
print("HAS_ERRORS" if pd.validate_work_units("F",cyclic) else "NO_ERRORS")
PY
)
  assert_eq "HAS_ERRORS" "$out" "cyclic DAG is rejected by validate_work_units"
end_test

# ─── S2: promotion default = AUTONOMOUS (auto-promote, holdout-gated); review opt-in ─
start_test "promotion_checkpoint_default_is_autonomous_holdout_gated"
  out=$(python3 - "$PPT" <<'PY'
import importlib.util, sys, os
for k in ("PROMPT_PROMOTION_REVIEW","PROMPT_PROMOTION_HOLDOUT_GATE"): os.environ.pop(k,None)
spec=importlib.util.spec_from_file_location("ppt", sys.argv[1])
ppt=importlib.util.module_from_spec(spec); sys.modules["ppt"]=ppt; spec.loader.exec_module(ppt)
class C: category="triage"; instruction="x"; label="l"
class T: id=1; dimension="d"; baseline_mean=0.5; candidates=[C()]
apply_now,reason=ppt._promotion_checkpoint(T(),0)
# default is autonomous-with-rail: the decision is owned by the holdout integrity rail
print("HOLDOUT" if "holdout" in reason.lower() else "OTHER")
PY
)
  assert_eq "HOLDOUT" "$out" "default decision is owned by the holdout safety rail (autonomous)"
end_test

start_test "promotion_checkpoint_killswitch_is_pure_auto"
  out=$(python3 - "$PPT" <<'PY'
import importlib.util, sys, os
os.environ.pop("PROMPT_PROMOTION_REVIEW",None); os.environ["PROMPT_PROMOTION_HOLDOUT_GATE"]="0"
spec=importlib.util.spec_from_file_location("ppt", sys.argv[1])
ppt=importlib.util.module_from_spec(spec); sys.modules["ppt"]=ppt; spec.loader.exec_module(ppt)
class C: category="triage"; instruction="x"; label="l"
class T: id=1; dimension="d"; baseline_mean=0.5; candidates=[C()]
apply_now,_=ppt._promotion_checkpoint(T(),0)
print("AUTO" if apply_now else "HELD")
PY
)
  assert_eq "AUTO" "$out" "PROMPT_PROMOTION_HOLDOUT_GATE=0 disables the rail (pure legacy auto)"
end_test

start_test "promotion_checkpoint_review_holds"
  out=$(python3 - "$PPT" <<'PY'
import importlib.util, sys, os
os.environ["PROMPT_PROMOTION_REVIEW"]="1"
spec=importlib.util.spec_from_file_location("ppt", sys.argv[1])
ppt=importlib.util.module_from_spec(spec); sys.modules["ppt"]=ppt; spec.loader.exec_module(ppt)
class C: category="triage"; instruction="x"; label="l"
class T: id=1; dimension="d"; baseline_mean=0.5; candidates=[C()]
apply_now,_=ppt._promotion_checkpoint(T(),0)
print("AUTO" if apply_now else "HELD")
PY
)
  assert_eq "HELD" "$out" "PROMPT_PROMOTION_REVIEW=1 holds the self-modification for human review"
end_test

# ─── S3: failure->eval miner runs, is dry-run-safe, and dedups ──────────────
start_test "failure_miner_dry_run_safe_and_dedups"
  before=$(wc -c < "$REPO_ROOT/scripts/eval-sets/discovery.json")
  out=$(python3 "$MINER" --json 2>/dev/null)
  after=$(wc -c < "$REPO_ROOT/scripts/eval-sets/discovery.json")
  assert_eq "$before" "$after" "dry-run must not modify discovery.json"
  echo "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'count' in d and d['applied'] is False else 1)"
  assert_eq 0 "$?" "miner emits a JSON report, applied=false"
end_test

start_test "failure_miner_skips_existing_patterns"
  # Build a discovery file that already contains a host+rule, point the miner at it,
  # and confirm that exact pattern is reported as skipped (dedup).
  tmp=$(mktemp -d)
  cat > "$tmp/discovery.json" <<'JSON'
[{"id":"DS-X","name":"seed","category":"availability","site":"nl","payload":{"alert_type":"librenms","hostname":"nl-claude01","alert_rule":"ContainerOOMKilled","severity":"critical","state":"alert"},"expected":{}}]
JSON
  out=$(EVAL_DISCOVERY_FILE="$tmp/discovery.json" python3 "$MINER" 2>/dev/null)
  assert_contains "$out" "skip (already in discovery): nl-claude01 / ContainerOOMKilled"
  rm -rf "$tmp"
end_test

# ─── S2: operator circuit-breaker companion lists cleanly ───────────────────
start_test "promotion_companion_lists"
  out=$(PROMPT_PROMOTIONS_PENDING_FILE="$(mktemp -u)" python3 "$APPLY" --list 2>&1)
  assert_contains "$out" "No pending"
end_test
