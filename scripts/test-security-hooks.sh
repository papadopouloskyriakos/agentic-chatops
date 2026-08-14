#!/bin/bash
# Test suite for unified-guard hook security patterns
# Run directly (not via Claude Code) to avoid hook inception.
#
# unified-guard.sh reads its input as the Claude Code hook JSON protocol:
#   { "tool_name": "Bash", "tool_input": { "command": "..." } }        for Bash
#   { "tool_name": "Edit", "tool_input": { "file_path": "..." } }      for Edit/Write
# on stdin. Exit 0 = allow (silent), exit 2 = deny (stdout shown as error).
# The previous version of this harness invoked the hook with positional CLI
# args, so every test passed the hook without triggering any rule and
# registered as FAIL. This version pipes real hook JSON in.

set -euo pipefail

cd "$(dirname "$0")/.."
HOOK="scripts/hooks/unified-guard.sh"
PASS=0; FAIL=0

check() {
  local name="$1" result="$2"
  if [ "$result" = "PASS" ]; then
    echo "  [PASS] $name"
    PASS=$((PASS+1))
  else
    echo "  [FAIL] $name — $result"
    FAIL=$((FAIL+1))
  fi
}

# Build JSON payload safely (avoids shell quoting pitfalls in commands like
# "rm -rf /" by using jq for the encoding).
hook_input() {
  local tool="$1" key="$2" value="$3"
  jq -n --arg t "$tool" --arg k "$key" --arg v "$value" \
    '{tool_name: $t, tool_input: {($k): $v}}'
}

run_hook() {
  local tool="$1" key="$2" value="$3"
  local exit_code=0
  hook_input "$tool" "$key" "$value" | bash "$HOOK" >/dev/null 2>&1 || exit_code=$?
  echo "$exit_code"
}

test_block_bash() {
  local cmd="$1" name="$2"
  local ec=$(run_hook "Bash" "command" "$cmd")
  [ "$ec" = "2" ] && check "$name" "PASS" || check "$name" "exit=$ec (expected 2)"
}

test_allow_bash() {
  local cmd="$1" name="$2"
  local ec=$(run_hook "Bash" "command" "$cmd")
  [ "$ec" = "0" ] && check "$name" "PASS" || check "$name" "exit=$ec (expected 0)"
}

test_block_file() {
  local tool="$1" path="$2" name="$3"
  local ec=$(run_hook "$tool" "file_path" "$path")
  [ "$ec" = "2" ] && check "$name" "PASS" || check "$name" "exit=$ec (expected 2)"
}

test_allow_file() {
  local tool="$1" path="$2" name="$3"
  local ec=$(run_hook "$tool" "file_path" "$path")
  [ "$ec" = "0" ] && check "$name" "PASS" || check "$name" "exit=$ec (expected 0)"
}

echo "===== SECURITY HOOK TESTS ====="

# Destructive command blocks (base64-encoded to keep this file clean of the
# actual dangerous strings — unified-guard still sees the decoded command).
test_block_bash "$(echo 'cm0gLXJmIC8=' | base64 -d)"                    "G1 blocks destructive delete"
test_block_bash "$(echo 'ZGQgaWY9L2Rldi96ZXJvIG9mPS9kZXYvc2Rh' | base64 -d)" "G2 blocks dd to disk"
test_block_bash "$(echo 'a3ViZWN0bCBkZWxldGUgbmFtZXNwYWNlIGt1YmUtc3lzdGVt' | base64 -d)" "G3 blocks k8s ns delete"
test_block_bash "$(echo 'c3lzdGVtY3RsIHN0b3AgZG9ja2Vy' | base64 -d)"    "G4 blocks service stop"
test_block_bash "$(echo 'aXB0YWJsZXMgLUY=' | base64 -d)"                "G5 blocks firewall flush"
test_block_bash "$(echo 'Y2htb2QgNzc3IC9ldGMvc2hhZG93' | base64 -d)"    "G6 blocks chmod shadow"

# File protection blocks
test_block_file "Edit"  "/home/app-user/.env"               "G7 blocks .env edit"
test_block_file "Write" "/home/app-user/.ssh/id_rsa"        "G8 blocks SSH key write"
test_block_file "Edit"  "/etc/passwd"                            "G9 blocks passwd edit"

# Safe command allows
test_allow_bash "git status"           "G10 allows git status"
test_allow_bash "ls -la /tmp"          "G11 allows ls"
test_allow_bash "cat /etc/hostname"    "G12 allows cat"
test_allow_file "Read" "/app/claude-gateway/CLAUDE.md" "G13 allows CLAUDE.md read"

# Word-boundary precision — these should ALLOW (word appears only in prose /
# filename / commit message, not as a command).
test_allow_bash "git commit -m 'add passwd to PROTECTED list'"    "G15 allows 'passwd' in commit message"
test_allow_bash "cat /etc/passwd.backup | head"                   "G16 allows /etc/passwd.backup read"
test_allow_bash "grep userdel docs/notes.md"                      "G17 allows grep 'userdel' in docs"
test_allow_bash "echo 'reboot procedure documented'"              "G18 allows 'reboot' in echo string"

# Word-boundary precision — these should still BLOCK (word IS the command).
test_block_bash "passwd root"                    "G19 blocks passwd command"
test_block_bash "sudo useradd attacker"          "G20 blocks useradd command"
test_block_bash "shutdown -h now"                "G21 blocks shutdown command"
test_block_bash "echo y | halt"                  "G22 blocks halt via pipe"

# OpenClaw exec-approvals
ea=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i ~/.ssh/one_key root@nl-openclaw01 \
  'docker exec openclaw-openclaw-gateway-1 node -e "const d=JSON.parse(require(\"fs\").readFileSync(\"/home/app-user/.openclaw/exec-approvals.json\",\"utf8\")); const a=d.agents?.main?.allowlist||[]; console.log(a.length+\" \"+a.filter(p=>p.pattern===\"*\").length)"' 2>/dev/null)
ea_total=$(echo "$ea" | awk '{print $1}')
ea_wc=$(echo "$ea" | awk '{print $2}')
[ "$ea_total" = "36" ] && [ "$ea_wc" = "0" ] && check "G14 exec-approvals (36 patterns, 0 wildcard)" "PASS" || check "G14" "total=$ea_total wc=$ea_wc"

echo ""
echo "Category G: $PASS PASS / $FAIL FAIL out of $((PASS + FAIL))"

# Exit non-zero if any test failed — useful for CI
[ "$FAIL" -eq 0 ]
