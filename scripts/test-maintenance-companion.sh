#!/bin/bash
# test-maintenance-companion.sh — E2E test for maintenance companion
# Tests the selfcheck + deps + checklist subcommands (read-only, safe to run anytime)
# Does NOT test start/end (those modify LibreNMS maintenance windows)
#
# Usage: ./scripts/test-maintenance-companion.sh [--site nl|gr]
#
# Prerequisites: Run from nl-claude01 as app-user

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPANION="$SCRIPT_DIR/maintenance-companion.sh"
SITE_FLAG="${1:-}"
SITE_ARG=""
if [ "$SITE_FLAG" = "--site" ] && [ -n "${2:-}" ]; then
  SITE_ARG="--site $2"
  SITE="${2}"
else
  SITE="nl"
fi

PASS=0
FAIL=0
TOTAL=0

pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  FAIL: $1"; }

echo "=== Maintenance Companion E2E Test (site: $SITE) ==="
echo ""

# --- T1: Selfcheck ---
echo "--- T1: selfcheck ---"
SELFCHECK=$($COMPANION selfcheck $SITE_ARG 2>&1)
if [ $? -eq 0 ] || echo "$SELFCHECK" | grep -q "available\|ok\|reachable"; then
  pass "selfcheck returned results"
else
  fail "selfcheck returned error"
fi
# Check that it tests key dependencies
for dep in "LibreNMS" "Matrix" "YouTrack" "n8n"; do
  if echo "$SELFCHECK" | grep -qi "$dep"; then
    pass "selfcheck tests $dep"
  else
    fail "selfcheck missing $dep check"
  fi
done

# --- T2: deps (NL: pve01 has many guests, GR: gr-pve01) ---
echo ""
echo "--- T2: deps ---"
if [ "$SITE" = "nl" ]; then
  TEST_HOST="nl-pve01"
else
  TEST_HOST="gr-pve01"
fi
DEPS_OUTPUT=$($COMPANION deps "$TEST_HOST" $SITE_ARG 2>&1)
if echo "$DEPS_OUTPUT" | grep -qiE "guest|vm|lxc|container|depend"; then
  pass "deps $TEST_HOST returned guest list"
else
  fail "deps $TEST_HOST returned no guests (output: ${DEPS_OUTPUT:0:200})"
fi

# --- T3: status (list active maintenance windows) ---
echo ""
echo "--- T3: status ---"
STATUS_OUTPUT=$($COMPANION status $SITE_ARG 2>&1)
if [ $? -eq 0 ]; then
  pass "status returned without error"
else
  fail "status returned error"
fi
# Status may show "no active maintenance" which is fine
if echo "$STATUS_OUTPUT" | grep -qiE "maintenance|window|none|no active"; then
  pass "status output is parseable"
else
  fail "status output unexpected: ${STATUS_OUTPUT:0:200}"
fi

# --- T4: check (poll a known-good host) ---
echo ""
echo "--- T4: check (read-only poll) ---"
if [ "$SITE" = "nl" ]; then
  CHECK_HOST="nl-n8n01"
else
  CHECK_HOST="gr-pve01"
fi
CHECK_OUTPUT=$($COMPANION check "$CHECK_HOST" $SITE_ARG 2>&1)
if echo "$CHECK_OUTPUT" | grep -qE "ping|responds|reachable|RECOVERY|running|✅|✓"; then
  pass "check $CHECK_HOST shows status"
else
  fail "check $CHECK_HOST unclear: ${CHECK_OUTPUT:0:200}"
fi

# --- T5: checklist (post-reboot verification, read-only) ---
echo ""
echo "--- T5: checklist ---"
CHECKLIST_OUTPUT=$($COMPANION checklist pve "$TEST_HOST" $SITE_ARG 2>&1)
if echo "$CHECKLIST_OUTPUT" | grep -qE "RESULT|CHECKLIST|✅|✓|✗|❌|pass|fail"; then
  pass "checklist pve returned results"
else
  fail "checklist pve unclear: ${CHECKLIST_OUTPUT:0:200}"
fi

# --- T6: Syntax check ---
echo ""
echo "--- T6: syntax validation ---"
if bash -n "$COMPANION" 2>&1; then
  pass "maintenance-companion.sh syntax valid"
else
  fail "maintenance-companion.sh syntax error"
fi

# --- Summary ---
echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed (total: $TOTAL)"
echo "============================================"

if [ "$FAIL" -gt 0 ]; then
  echo "WARNING: Some tests failed. Review output above."
  exit 1
else
  echo "All tests passed."
  exit 0
fi
