#!/usr/bin/env bash
# claude-provider.sh — flip which backend ALL Claude Code (dispatched + auxiliary + interactive)
# uses, the easy way. ONE switch: it edits the env block of ~/.claude/settings.json, which Claude
# Code reads as its base environment for EVERY invocation of the `claude` binary (no per-script wiring).
#
#   scripts/claude-provider.sh zai        -> Z.ai GLM (glm-5.2=opus, glm-4.7=sonnet/haiku)
#   scripts/claude-provider.sh anthropic  -> Anthropic (Max subscription OAuth, default)  [revert]
#   scripts/claude-provider.sh status     -> show current
#
# Why settings.json and not a sentinel: Claude Code is invoked from MANY sites (Runner dispatch,
# agent_as_tool, mr-review, parallel-dev, interactive). settings.json env applies to all of them at
# once, so flipping it flips the whole estate uniformly. `rm`/`anthropic` restores the original block.
# Pure-API eval components (RAGAS/judge/frontier) are unaffected — they call REST directly via LiteLLM.
set -u
S="/home/app-user/.claude/settings.json"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ZK=$(grep -m1 '^ZAI_API_KEY=' "$REPO/.env" 2>/dev/null | cut -d= -f2-)

apply_block() {  # $1 = zai | anthropic
  python3 - "$S" "$1" "$ZK" <<'PY'
import json, sys
s, mode, zk = sys.argv[1], sys.argv[2], sys.argv[3]
d = {}
try: d = json.load(open(s))
except Exception: d = {}
env = d.get("env") or {}
# strip any keys we own
for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
          "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
          "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
    env.pop(k, None)
if mode == "zai":
    env["ANTHROPIC_BASE_URL"] = "https://api.z.ai/api/anthropic"
    env["ANTHROPIC_AUTH_TOKEN"] = zk
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "glm-5.2"
    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "glm-4.7"
    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = "glm-4.7"
d["env"] = env
json.dump(d, open(s, "w"), indent=2)
print("zai" if mode == "zai" else "anthropic")
PY
}

case "${1:-status}" in
  zai)
    [ -z "$ZK" ] && { echo "FATAL: ZAI_API_KEY not in $REPO/.env"; exit 1; }
    cp "$S" "$S.bak.$(date +%s)" 2>/dev/null || true
    echo "All Claude Code -> Z.ai (glm-5.2/glm-4.7). Effective next invocation.";;
  anthropic)
    cp "$S" "$S.bak.$(date +%s)" 2>/dev/null || true
    echo "All Claude Code -> Anthropic (Max OAuth default). Effective next invocation.";;
  status)
    cur=$(python3 -c "import json;d=json.load(open('$S'));print('zai' if d.get('env',{}).get('ANTHROPIC_BASE_URL','').find('z.ai')>=0 else 'anthropic')" 2>/dev/null || echo unknown)
    echo "current claude-code provider: $cur"; exit 0;;
  *) echo "usage: claude-provider.sh [zai|anthropic|status]"; exit 1;;
esac
apply_block "$1"