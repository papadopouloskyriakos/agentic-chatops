#!/usr/bin/env bash
# test-1711-autoclose-toverify-readonly.sh — the To-Verify read-only-recovered carve-out
# (operator alert-automation directives #1/#2/#7, 2026-07-08). Verifies the SAFETY gate on
# an ISOLATED mktemp DB: only a risk=low/band=AUTO parked session (executed nothing) is
# closeable; mixed/high (real reversible/write actions) stay with the operator; a no-session
# issue is closeable ONLY for the hardware-bound control-plane host pattern (#7).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

TMPDIR_T=$(mktemp -d); trap 'rm -rf "$TMPDIR_T"' EXIT
DB="$TMPDIR_T/gw.db"
sqlite3 "$DB" < "$REPO_ROOT/schema.sql" 2>/dev/null
sqlite3 "$DB" "
  INSERT INTO session_risk_audit (issue_id, risk_level, band, auto_approved, signals_json, classified_at) VALUES
    ('P-LOW',   'low',   'AUTO',        1, '[\"read-only:diagnostic-read\"]', datetime('now')),
    ('P-MIXED', 'mixed', 'AUTO',        1, '[\"reversible:restart\"]',        datetime('now')),
    ('P-HIGH',  'high',  'POLL_PAUSE',  0, '[\"high:fs-write\"]',             datetime('now')),
    ('P-LOWNA', 'low',   'AUTO',        0, '[\"read-only:diagnostic-read\"]', datetime('now'));"

# _readonly_low_auto(issue) via the real module
gate() { GATEWAY_DB="$DB" python3 - "$1" <<'PY'
import importlib.util, sys, os
spec = importlib.util.spec_from_file_location("ac", os.path.join(os.environ.get("REPO_ROOT","."), "scripts/alert-yt-autoclose.py"))
# REPO_ROOT not exported into python; derive from this file's known path via env
PY
}

_gate() { REPO_ROOT="$REPO_ROOT" GATEWAY_DB="$DB" python3 - "$1" <<PY
import importlib.util, os
spec = importlib.util.spec_from_file_location("ac", "$REPO_ROOT/scripts/alert-yt-autoclose.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ok, why = m._readonly_low_auto("$1")
print(f"{ok}|{why}")
PY
}

start_test "readonly_low_auto_closes_only_low_band_auto"
  r=$(_gate P-LOW);   assert_contains "$r" "True|readonly-low-auto" "risk=low/AUTO/approved -> closeable"
  r=$(_gate P-MIXED); assert_contains "$r" "False|not-readonly:mixed" "mixed -> NOT closeable (real action)"
  r=$(_gate P-HIGH);  assert_contains "$r" "False|not-readonly:high" "high/POLL -> NOT closeable"
  r=$(_gate P-LOWNA); assert_contains "$r" "False|not-readonly" "low but auto_approved=0 -> NOT closeable"
  r=$(_gate P-NONE);  assert_contains "$r" "None|no-session" "no risk-audit row -> defer to ctrl-plane host test"
end_test

start_test "ctrlplane_regex_scopes_self_cleared_class"
  out=$(REPO_ROOT="$REPO_ROOT" python3 - <<PY
import importlib.util
spec = importlib.util.spec_from_file_location("ac", "$REPO_ROOT/scripts/alert-yt-autoclose.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
tests = [("nlk8s-ctrl02", True), ("nlk8s-node03", True), ("grk8s-ctrl01", True),
         ("nloas02", False), ("nl-pve01", False), ("nlghostfolio01", False)]
bad = [h for h,w in tests if bool(m.CTRLPLANE_RE.search(h)) != w]
print("ALL-OK" if not bad else "FAIL:"+",".join(bad))
PY
)
  assert_contains "$out" "ALL-OK" "CTRLPLANE_RE matches only k8s ctrlr/node hosts (self-cleared #7 scope)"
end_test

start_test "toverify_close_requires_both_sentinels_present"
  # source-level guard: the To-Verify close is gated by TOVERIFY_ARMED and ARMED together.
  grep -q "TOVERIFY_ARMED and ARMED and close(" "$REPO_ROOT/scripts/alert-yt-autoclose.py"
  assert_eq 0 "$?" "To-Verify close requires BOTH ~/gateway.alert_yt_autoclose_armed AND ~/gateway.autoclose_toverify_readonly"
  grep -q 'state not in ("Open", "To Verify")' "$REPO_ROOT/scripts/alert-yt-autoclose.py"
  assert_eq 0 "$?" "only Open + To Verify states are ever considered"
end_test
