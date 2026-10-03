#!/usr/bin/env bash
# scripts/ipa.sh — run a FreeIPA `ipa` command with the gateway's long-living admin keytab.
#
# Auth is automatic and PASSWORDLESS: the svc-claude-gateway keytab (admins group) is
# kinit'd on the FreeIPA host before the command runs. claude01 is not an IPA client, so
# the command executes on $IPA_SERVER over SSH. No admin password is ever needed at runtime.
#
#   Usage:  scripts/ipa.sh <ipa-subcommand> [args...]
#   e.g.    scripts/ipa.sh dnsrecord-add example.net foo --a-rec=10.0.181.X
#           scripts/ipa.sh user-find svc-claude-gateway
#
# Credential provenance + rotation: scripts/ipa.sh self-test  (and docs/runbooks below).
# Break-glass admin password: ~/.config/gateway/ipa-admin-breakglass.cred (only if keytab lost).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.env" ] && { set -a; . "$ROOT/.env"; set +a; }

: "${IPA_SERVER:=nlfreeipa01.sec.example.net}"
: "${IPA_PRINCIPAL:=svc-claude-gateway}"
: "${IPA_KEYTAB_REMOTE:=/root/svc-claude-gateway.keytab}"
: "${IPA_SSH_KEY:=$HOME/.ssh/one_key}"

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -i "$IPA_SSH_KEY" "root@${IPA_SERVER}")

# self-test: prove passwordless keytab auth works and reports the bound principal
if [ "${1:-}" = "self-test" ]; then
  "${SSH[@]}" "kinit -k -t '${IPA_KEYTAB_REMOTE}' '${IPA_PRINCIPAL}' >/dev/null 2>&1 \
    && echo OK:\$(klist | awk '/Default principal/{print \$3}') \
    && ipa ping >/dev/null 2>&1 && echo 'ipa-reachable' || echo 'ipa-UNREACHABLE'"
  exit $?
fi

[ $# -ge 1 ] || { echo "usage: $0 <ipa-subcommand> [args...]   (or: self-test)" >&2; exit 2; }

# %q-quote each arg so it survives the remote bash re-parse intact
remote_args="$(printf '%q ' "$@")"
"${SSH[@]}" "kinit -k -t '${IPA_KEYTAB_REMOTE}' '${IPA_PRINCIPAL}' >/dev/null 2>&1 && ipa ${remote_args}"
