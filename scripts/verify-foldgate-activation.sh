#!/usr/bin/env bash
# One-shot verification (idempotent): did the infragraph fold-gate auto-activate?
# Set live at family precision 0.80 on 2026-06-24 (IFRNLLEI01PRD-1040); was NO-GO
# only because days_observed 7.1 < 14, so it self-activates ~2026-07-01 once the
# v2 evidence window fills. Runs daily 2026-07-01..08 via cron; reports ONCE (to
# YouTrack -1040 + Matrix #infra-nl-prod) on activation, or a diagnosis at
# the 07-08 deadline. Marker ~/gateway.foldgate-verified prevents re-reporting.
# CANNOT run as a cloud agent — needs the live gateway.db + sentinel on this host.
set -u
REPO=/app/claude-gateway
LIVE=/app/cubeos/claude-context/gateway.db
MARKER=/home/app-user/gateway.foldgate-verified
DEADLINE=20260708
LOG=/home/app-user/logs/claude-gateway/foldgate-verify.log
cd "$REPO" || exit 1
[ -f "$MARKER" ] && exit 0
set -a; . "$REPO/.env" 2>/dev/null; set +a

# Refresh + read the scorecard and the authorization decision from the live db.
VERDICT=$(python3 - "$LIVE" "$REPO" <<'PY'
import json, os, sys, subprocess, importlib.util, datetime
live, repo = sys.argv[1], sys.argv[2]
sc_path = os.path.join(repo, "test-results", "infragraph-scorecard.json")
# regenerate fresh (also unblocks the autofold if today is the activation day)
subprocess.run(["python3", os.path.join(repo, "scripts", "infragraph-eval.py"),
                "--db", live, "--scorecard", "--no-notify", "--out", sc_path],
               capture_output=True)
d = json.load(open(sc_path))
g = (d.get("scorecard", d)).get("gate_b_to_c", {})
fc = g.get("fold_candidate", {})
spec = importlib.util.spec_from_file_location(
    "prop", os.path.join(repo, "scripts", "infragraph-propose-blast-radius.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ok, why = m._autofold_authorized()
# count infragraph-auto-approved fold rules
import sqlite3
n_rules = 0
try:
    c = sqlite3.connect(live)
    for (v,) in c.execute("SELECT value FROM openclaw_memory WHERE category='blast-radius'"):
        try:
            if json.loads(v).get("generated_by") == "infragraph":
                n_rules += 1
        except Exception:
            pass
except Exception:
    pass
print(json.dumps({
    "authorized": ok, "reason": why,
    "all_met_fold": fc.get("all_met_fold"),
    "precision": fc.get("precision_fold_family"),
    "days": d.get("days_observed"),
    "control_ratio": (g.get("control_ok")),
    "auto_rules": n_rules,
    "today": datetime.datetime.utcnow().strftime("%Y%m%d"),
}))
PY
)
echo "$(date -u +%FT%TZ) $VERDICT" >> "$LOG"

AUTHORIZED=$(echo "$VERDICT" | python3 -c "import json,sys;print(json.load(sys.stdin)['authorized'])")
TODAY=$(echo "$VERDICT" | python3 -c "import json,sys;print(json.load(sys.stdin)['today'])")

post() {  # $1=title $2=body
  local body="$1
$2"
  # JSON-encode the body string ONCE (handles quotes/newlines/emoji safely).
  local jbody
  jbody=$(python3 -c "import json,sys;print(json.dumps(sys.argv[1]))" "$body")

  # YouTrack -1040 — the reliable channel; log the HTTP code.
  local ytc
  ytc=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Authorization: Bearer ${YOUTRACK_API_TOKEN}" -H "Content-Type: application/json" \
    "${YOUTRACK_URL:-https://youtrack.example.net}/api/issues/IFRNLLEI01PRD-1040/comments" \
    -d "{\"text\":${jbody}}")
  echo "$(date -u +%FT%TZ) youtrack_post=${ytc}" >> "$LOG"

  # Matrix #infra-nl-prod (best-effort). Room ID URL-encoded per the Matrix
  # spec (!room:server -> %21room%3Aserver); log the code so a miss isn't silent.
  if [ -n "${MATRIX_CLAUDE_TOKEN:-}" ] && [ -n "${MATRIX_ROOM_INFRA:-}" ] && [ -n "${MATRIX_HOMESERVER:-}" ]; then
    local room_enc hs mxc
    room_enc=$(python3 -c "import urllib.parse,os;print(urllib.parse.quote(os.environ['MATRIX_ROOM_INFRA'], safe=''))")
    hs="https://${MATRIX_HOMESERVER#https://}"
    mxc=$(curl -s -o /dev/null -w "%{http_code}" -X PUT \
      -H "Authorization: Bearer ${MATRIX_CLAUDE_TOKEN}" -H "Content-Type: application/json" \
      "${hs}/_matrix/client/v3/rooms/${room_enc}/send/m.room.message/foldgate-$(date +%s%N)" \
      -d "{\"msgtype\":\"m.notice\",\"body\":${jbody}}")
    echo "$(date -u +%FT%TZ) matrix_post=${mxc}" >> "$LOG"
  fi
}

if [ "$AUTHORIZED" = "True" ]; then
  post "✅ Infragraph fold-gate ACTIVATED (IFRNLLEI01PRD-1040, verified $(date -u +%F))" \
       "The 0.80 fold-gate set live 2026-06-24 has self-activated — autonomous blast-radius folding is now authorized. Verdict: $VERDICT. Proposed fold rules will auto-approve. Kill if needed: rm ~/gateway.infragraph_autofold."
  touch "$MARKER"
elif [ "$TODAY" -ge "$DEADLINE" ]; then
  post "⚠️ Infragraph fold-gate did NOT activate by the 2026-07-08 deadline (IFRNLLEI01PRD-1040)" \
       "Expected self-activation ~2026-07-01. It has not. Diagnosis: $VERDICT. Likely causes: days_observed still <14, precision dropped <0.80, control_ratio>0.5, the sentinel ~/gateway.infragraph_autofold was removed, or the scorecard went stale. Operator review needed."
  touch "$MARKER"
else
  echo "$(date -u +%FT%TZ) not-yet — recheck tomorrow" >> "$LOG"
fi
