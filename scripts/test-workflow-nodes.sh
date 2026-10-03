#!/usr/bin/env bash
# Step-level evaluation — test individual n8n workflow nodes in isolation
# Tests: Build Prompt (category detection), Parse Response (confidence extraction),
#        Prepare Result (credential redaction), Query Knowledge (poll detection)
set -euo pipefail
source "$(dirname "$0")/eval-config.sh" 2>/dev/null || true

PASS=0; FAIL=0; SKIP=0

test_category_detection() {
  # Test that alert category regex works correctly
  # Input: summary text -> Expected: category
  local -A tests=(
    ["Device Down nl-pve01"]="availability"
    ["High CPU load on nl-gpu01"]="resource"
    ["iSCSI LUN latency on gr-pve02"]="storage"
    ["Interface down on nl-sw01 port Gi0/24"]="network"
    ["Pod OOMKilled in kube-system"]="kubernetes"
    ["Certificate expiring in 7 days"]="certificate"
    ["Scheduled maintenance on nl-pve02"]="maintenance"
    ["Correlated alert burst: 3 hosts"]="correlated"
  )
  for input in "${!tests[@]}"; do
    expected="${tests[$input]}"
    # Run the category detection regex from Build Prompt
    # Order matters: specific patterns (k8s, network) before broad ones (availability, resource)
    actual=$(python3 -c "
REDACTED_a7b84d63
combined = '''${input}'''.lower()
cat = 'general'
if re.search(r'correlated|burst|multiple', combined): cat = 'correlated'
elif re.search(r'maintenance|reboot|upgrade|firmware', combined): cat = 'maintenance'
elif re.search(r'cert|ssl|tls|expir', combined): cat = 'certificate'
elif re.search(r'cilium|k8s|pod|node|container|helm|argocd|etcd|oomkill', combined): cat = 'kubernetes'
elif re.search(r'interface|port|bgp|network|vlan|ospf|tunnel|vpn', combined): cat = 'network'
elif re.search(r'disk|storage|iscsi|lun|nfs|seaweedfs|synology', combined): cat = 'storage'
elif re.search(r'cpu|load|memory|ram|oom|swap', combined): cat = 'resource'
elif re.search(r'up/down|unreachable|ping|down|offline', combined): cat = 'availability'
print(cat)
")
    if [[ "$actual" == "$expected" ]]; then
      PASS=$((PASS + 1))
    else
      echo "FAIL: category_detection('$input') = '$actual', expected '$expected'"
      FAIL=$((FAIL + 1))
    fi
  done
}

test_confidence_extraction() {
  # Test CONFIDENCE regex extraction from responses
  local -A tests=(
    ["CONFIDENCE: 0.8 — Root cause confirmed"]="0.8"
    ["CONFIDENCE: 0.5 — Inconclusive"]="0.5"
    ["CONFIDENCE: 0.95 – Tests pass"]="0.95"
  )
  for input in "${!tests[@]}"; do
    expected="${tests[$input]}"
    actual=$(python3 -c "
REDACTED_a7b84d63
text = '''${input}'''
m = re.search(r'CONFIDENCE:\s*([\d.]+)\s*[\u2013\u2014\-]', text)
print(m.group(1) if m else 'NONE')
")
    if [[ "$actual" == "$expected" ]]; then PASS=$((PASS + 1)); else echo "FAIL: confidence('$input') = '$actual', expected '$expected'"; FAIL=$((FAIL + 1)); fi
  done
}

test_credential_redaction() {
  # Test credential patterns are detected
  local -a creds=(
    "Bearer REDACTED_JWT"
    "ghp_VMID_REDACTED0abcdefghijklmnopqrstuvwxyz"
    "REDACTED_7abe0759TED0"
    "sk-VMID_REDACTED0abcdefghijkl"
    "AKIAIOSFODNN7EXAMPLE"
    "REDACTED_5a44233c
  )
  REDACTED_6e626740
    REDACTED_dabf0ad0
    REDACTED_415c88e2
REDACTED_a7b84d63
REDACTED_4529f8c2
    REDACTED_1c9340cc
    REDACTED_2767e41a
    REDACTED_5f03360f
    REDACTED_89835a76
    REDACTED_138f8069
    REDACTED_8a73d801',
]
text = '''${cred}'''
for p in patterns:
    if re.search(p, text):
        print('MATCH')
        break
else:
    print('NO_MATCH')
")
    if [[ "$matched" == "MATCH" ]]; then PASS=$((PASS + 1)); else echo "FAIL: credential not detected: '$cred'"; FAIL=$((FAIL + 1)); fi
  done
}

_run_parse_poll_fixtures() {
  # Drive the *real* parsePoll() from a workflow node against bug fixtures.
  # $1 = path to workflow JSON, $2 = node name to find parsePoll in.
  # Cases include the historical Bug 1 (early-[POLL] hijack from quoted prompt
  # text — IFRNLLEI01PRD-734/-723) and Bug 2 (trailing-prose absorbed as
  # options — IFRNLLEI01PRD-731/-706/-728/-732/-620). A regression on either
  # fails CI.
  local wf="$1"
  local node="$2"
  if [ ! -f "$wf" ] || ! command -v node >/dev/null 2>&1; then
    echo "SKIP"; return
  fi
  WF="$wf" NODE="$node" node - <<'NODEEOF'
const fs = require('fs');
const wf = JSON.parse(fs.readFileSync(process.env.WF, 'utf-8'));
const targetNode = process.env.NODE;
let src = '';
for (const n of (wf.nodes || [])) {
  if (n.name === targetNode) { src = n.parameters.jsCode || ''; break; }
}
if (!src) { console.log('NO_NODE'); process.exit(0); }
const start = src.indexOf('function parsePoll(result) {');
let depth = 0, end = -1;
for (let i = start; i < src.length; i++) {
  if (src[i] === '{') depth++;
  else if (src[i] === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
}
if (start < 0 || end < 0) { console.log('NO_FN'); process.exit(0); }
eval(src.slice(start, end));

const cases = [
  { name: 'B1_early_poll_hijack', expQ: 'Choose how to handle:', expN: 4, text:
`Earlier prose mentioning the gateway: only [POLL] blocks for interactive approval. Plain text approval requests are invisible to the approval system.

Re-stating cleanly:

## Proposed Actions

[POLL] Choose how to handle:
- Plan A: Close as expected NMC watchdog reboot
- Plan B: Plan A + open a tracking YT issue
- Plan C: Plan A + suppress 'Device rebooted' alert rule
- Other: I'll reply with a different approach

CONFIDENCE: 0.9 - reasoning.` },
  { name: 'B2_awaiting_approval_swept', expQ: 'Which approach do you prefer?', expN: 4, text:
`[POLL] Which approach do you prefer?
- Plan A: qm resume
- Plan B: qm stop + qm start
- Plan C: qm stop + qemu-nbd inspect
- Other: I'll reply with a different approach

Awaiting approval to proceed. Reply "approved" to execute.

CONFIDENCE: 0.85.` },
  { name: 'B2_then_file_followup_swept', expQ: 'How to clear gemma3:12b?', expN: 3, text:
`[POLL] How to clear gemma3:12b?
- Plan A: Unload via API
- Plan B: Restart ollama container
- Plan C: Skip remediation
- Then file a follow-up task: pin GPULayers via Modelfile.

CONFIDENCE: 0.85.` },
  { name: 'B2_my_recommendation_swept', expQ: 'Which approach do you prefer?', expN: 4, text:
`[POLL] Which approach do you prefer?
- Plan A: Install Debian package
- Plan B: Run docker container
- Plan C: Remove from targets
- Plan D: Investigate further

My recommendation is Plan A.

CONFIDENCE: 0.9.` },
  { name: 'happy_path_no_fluff', expQ: 'Which approach do you prefer?', expN: 3, text:
`[POLL] Which approach do you prefer?
- Plan A: Fix crontab line
- Plan B: Plan A + update docs
- Plan C: Investigate further

CONFIDENCE: 0.9.` },
  { name: 'numbered_options_strip', expQ: 'Choose a plan:', expN: 3, text:
`[POLL] Choose a plan:
1. Plan A: thing A
2. Plan B: thing B
3. Plan C: thing C

CONFIDENCE: 0.7.` },
  { name: 'spaced_markdown_options_no_break', expQ: 'Which?', expN: 3, text:
`[POLL] Which?

- **Plan A** — first description

- **Plan B** — second description

- **Plan C** — third description

My recommendation: Plan A.` },
  { name: 'nested_bullets_skip_subbullets', expQ: 'How?', expN: 2, text:
`[POLL] How?
- **Plan A** — title
  - sub bullet 1 of A
  - sub bullet 2 of A
- **Plan B** — title
  - sub bullet 1 of B
  - sub bullet 2 of B

My recommendation: Plan A.` },
  { name: 'horizontal_rule_terminates', expQ: 'How?', expN: 2, text:
`[POLL] How?
- Plan A
- Plan B
---
Not an option.` },
];
let pass = 0, fail = 0, errs = [];
for (const c of cases) {
  const p = parsePoll(c.text);
  const qOk = p && p.question === c.expQ;
  const nOk = p && p.answers && p.answers.length === c.expN;
  if (qOk && nOk) pass++;
  else { fail++; errs.push(c.name + ' (got Q=' + (p ? JSON.stringify(p.question) : 'null') + ' N=' + (p ? p.answers.length : 'n/a') + ')'); }
}
console.log('PASS:' + pass + ',FAIL:' + fail + (errs.length ? ',ERRS=' + errs.join(';') : ''));
NODEEOF
}

test_poll_detection_runner() {
  local wf="$(dirname "$0")/../workflows/claude-gateway-runner.json"
  local result; result="$(_run_parse_poll_fixtures "$wf" 'Prepare Result')"
  if [[ "$result" == "PASS:9,FAIL:0" ]]; then
    PASS=$((PASS + 1))
  elif [[ "$result" == "SKIP" ]]; then
    echo "SKIP: poll detection runner (need workflow file + node)"; SKIP=$((SKIP + 1))
  else
    echo "FAIL: runner poll detection = '$result'"
    FAIL=$((FAIL + 1))
  fi
}

test_poll_detection_bridge() {
  local wf="$(dirname "$0")/../workflows/claude-gateway-matrix-bridge.json"
  local result; result="$(_run_parse_poll_fixtures "$wf" 'Prepare Bridge Response')"
  if [[ "$result" == "PASS:9,FAIL:0" ]]; then
    PASS=$((PASS + 1))
  elif [[ "$result" == "SKIP" ]]; then
    echo "SKIP: poll detection bridge (need workflow file + node)"; SKIP=$((SKIP + 1))
  else
    echo "FAIL: bridge poll detection = '$result'"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Step-Level Evaluation ==="
echo ""
echo "--- Category Detection ---"
test_category_detection
echo "--- Confidence Extraction ---"
test_confidence_extraction
echo "--- Credential Redaction ---"
test_credential_redaction
echo "--- Poll Detection (Runner) ---"
test_poll_detection_runner
echo "--- Poll Detection (Bridge) ---"
test_poll_detection_bridge
echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="
exit $((FAIL > 0 ? 1 : 0))
