#!/usr/bin/env bash
# litellm-gateway-setup.sh — idempotently provision the gateway's models + virtual key on the
# EXISTING shared LiteLLM (nllitellm01, v1.85.0). The gateway does NOT run its own LiteLLM:
# gateway models (gw-*) + a gateway-scoped virtual key are added via the admin API into LiteLLM's
# postgres DB, so omoikane's config.yaml model_list is NEVER touched. Re-runnable (skips existing).
#
# The LiteLLM master key is fetched transiently over SSH (NEVER stored gateway-side); only the
# scoped virtual key lands in .env (LITELLM_GATEWAY_KEY, gitignored). Per-key/per-model spend is
# tracked in LiteLLM's postgres + exported to its Prometheus. This is Plane B of the model-
# orchestration design (Plane A = the dispatched-session Anthropic<->Z.ai switch, claude-provider.sh).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LL="${LITELLM_URL:-http://10.0.181.X:4000}"
LL_HOST="${LITELLM_HOST:-10.0.181.X}"
ENV_FILE="$REPO/.env"

MK=$(ssh -i ~/.ssh/one_key -o ConnectTimeout=8 -o StrictHostKeyChecking=no root@"$LL_HOST" \
  'docker exec litellm-litellm-1 env 2>/dev/null | grep "^LITELLM_MASTER_KEY=" | cut -d= -f2-' 2>/dev/null)
[ -z "$MK" ] && { echo "FATAL: could not fetch LiteLLM master key from $LL_HOST"; exit 1; }
ZK=$(grep '^ZAI_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)
DK=$(grep '^DEEPSEEK_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)
MSK=$(grep '^MISTRAL_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)

have=$(curl -s "$LL/v1/models" -H "Authorization: Bearer $MK" 2>/dev/null \
  | python3 -c "import json,sys;print(' '.join(m['id'] for m in json.load(sys.stdin).get('data',[])))" 2>/dev/null)

add(){ # name litellm_model api_base auth_key
  local n="$1" m="$2" base="$3" key="$4"
  echo " $have " | grep -qw "$n" && { echo "  = $n (exists)"; return; }
  local p="{\"model\":\"$m\",\"api_key\":\"$key\""; [ -n "$base" ] && p="$p,\"api_base\":\"$base\""; p="$p}"
  local r; r=$(curl -s "$LL/model/new" -H "Authorization: Bearer $MK" -H "Content-Type: application/json" \
    -d "{\"model_name\":\"$n\",\"litellm_params\":$p}")
  echo "  + $n: $(echo "$r" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('model_name',str(d.get('error',d))[:80]))" 2>/dev/null)"; }

# Gateway model catalog — provider-routed through the shared LiteLLM (Anthropic + Z.ai/GLM):
add gw-mistral-large "mistral/mistral-large-latest"        ""                               "$MSK"
add gw-deepseek      "deepseek/deepseek-v4-pro"            ""                               "$DK"
add gw-glm-opus      "anthropic/glm-5.2"                   "https://api.z.ai/api/anthropic" "$ZK"
add gw-glm-sonnet    "anthropic/glm-4.7"                   "https://api.z.ai/api/anthropic" "$ZK"

# Gateway-scoped virtual key (per-key spend) — only if not already provisioned:
if ! grep -q '^LITELLM_GATEWAY_KEY=' "$ENV_FILE"; then
  resp=$(curl -s "$LL/key/generate" -H "Authorization: Bearer $MK" -H "Content-Type: application/json" \
    -d '{"models":["gw-mistral-large","gw-deepseek","gw-glm-opus","gw-glm-sonnet"],"key_alias":"gateway-api-plane","metadata":{"project":"claude-gateway"}}')
  VK=$(echo "$resp" | python3 -c "import json,sys;print(json.load(sys.stdin).get('key',''))" 2>/dev/null)
  if [ -n "$VK" ]; then
    printf '\n# LiteLLM gateway-api-plane virtual key (scoped to gw-*, DB-stored on nllitellm01)\nLITELLM_GATEWAY_KEY=%s\n' "$VK" >> "$ENV_FILE"
    echo "  + virtual key 'gateway-api-plane' -> .env"
  else echo "  ! key gen failed: ${resp:0:100}"; fi
else echo "  = gateway-api-plane key (already in .env)"; fi
echo "done. (per-component spend: pass metadata {\"tags\":[\"<component>\"]} on requests, or mint a per-component key.)"
