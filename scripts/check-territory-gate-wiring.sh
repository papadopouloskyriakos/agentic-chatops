#!/usr/bin/env bash
# Territory-gate WIRING watchdog (IFRNLLEI01PRD-1408, risk-appetite hardening 2026-06-25).
#
# The territory gate is enforced by a PreToolUse hook that runs ONLY if it is wired into the
# session settings. The hook itself now fails CLOSED when it RUNS-but-errors (commit d7e51bd),
# but it cannot detect being UNWIRED — if it is dropped from settings it simply never fires and
# nothing notices, silently reopening the gap (network/firewall writes auto-execute behind it).
# This EXTERNAL check asserts the invariant: ~/gateway.territory_gate ON  =>  the hook is
# referenced in BOTH session-settings surfaces AND the hook file parses. Emits a Prometheus
# textfile metric and exits non-zero on violation. Intended cron: */15.
#
# Env overrides (for tests): TERRITORY_GATE_SENTINEL, INTERACTIVE_SETTINGS, DISPATCHED_SETTINGS,
# PROM_TEXTFILE_DIR (set to a writable temp dir, or "" to skip metric emission).
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SENTINEL="${TERRITORY_GATE_SENTINEL:-$HOME/gateway.territory_gate}"
HOOK="${TERRITORY_HOOK:-$REPO/scripts/hooks/territory-gate.py}"
INTERACTIVE="${INTERACTIVE_SETTINGS:-$HOME/.claude/settings.json}"
DISPATCHED="${DISPATCHED_SETTINGS:-$REPO/config/dispatched-session-settings.json}"
PROM_DIR="${PROM_TEXTFILE_DIR-/var/lib/node_exporter/textfile_collector}"
PROM_FILE="${PROM_DIR:+$PROM_DIR/gateway_territory_gate_wiring.prom}"

wired_in() { grep -q "territory-gate.py" "$1" 2>/dev/null && echo 1 || echo 0; }

gate_on=0; [ -e "$SENTINEL" ] && gate_on=1
i_wired=$(wired_in "$INTERACTIVE")
d_wired=$(wired_in "$DISPATCHED")
hook_ok=0
[ -f "$HOOK" ] && python3 -c "import py_compile;py_compile.compile('$HOOK',doraise=True)" 2>/dev/null && hook_ok=1

# Violation only matters while the gate is ON (sentinel present). Gate OFF = enforcement
# intentionally disabled, wiring not required.
violation=0
if [ "$gate_on" = 1 ]; then
  { [ "$i_wired" = 1 ] && [ "$d_wired" = 1 ] && [ "$hook_ok" = 1 ]; } || violation=1
fi

if [ -n "${PROM_FILE:-}" ] && { [ -d "$PROM_DIR" ] || mkdir -p "$PROM_DIR" 2>/dev/null; }; then
  {
    echo "# HELP gateway_territory_gate_sentinel_on Territory gate sentinel present (1=enforcement enabled)."
    echo "# TYPE gateway_territory_gate_sentinel_on gauge"
    echo "gateway_territory_gate_sentinel_on $gate_on"
    echo "# HELP gateway_territory_gate_wired Hook referenced in a session-settings surface (1=wired)."
    echo "# TYPE gateway_territory_gate_wired gauge"
    echo "gateway_territory_gate_wired{surface=\"interactive\"} $i_wired"
    echo "gateway_territory_gate_wired{surface=\"dispatched\"} $d_wired"
    echo "# HELP gateway_territory_gate_hook_parses Hook file exists and parses (1=ok)."
    echo "# TYPE gateway_territory_gate_hook_parses gauge"
    echo "gateway_territory_gate_hook_parses $hook_ok"
    echo "# HELP gateway_territory_gate_wiring_violation Gate ON but wiring incomplete (1=violation)."
    echo "# TYPE gateway_territory_gate_wiring_violation gauge"
    echo "gateway_territory_gate_wiring_violation $violation"
    echo "# HELP gateway_territory_gate_wiring_last_run_timestamp Unix time of the last wiring check."
    echo "# TYPE gateway_territory_gate_wiring_last_run_timestamp gauge"
    echo "gateway_territory_gate_wiring_last_run_timestamp $(date +%s)"
  } > "$PROM_FILE.tmp" 2>/dev/null && mv "$PROM_FILE.tmp" "$PROM_FILE" 2>/dev/null
fi

if [ "$violation" = 1 ]; then
  echo "VIOLATION: territory gate ON but wiring incomplete (interactive=$i_wired dispatched=$d_wired hook_parses=$hook_ok)" >&2
  exit 1
fi
echo "OK: territory-gate wiring (gate_on=$gate_on interactive=$i_wired dispatched=$d_wired hook_parses=$hook_ok)"
exit 0
