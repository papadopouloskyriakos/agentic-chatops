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

test_poll_detection() {
  # Test [POLL] block parsing
  local poll_text='[POLL] Which approach?
- Plan A: Restart (low risk, 5min)
- Plan B: Investigate further
CONFIDENCE: 0.7 — needs approval'

  has_poll=$(python3 -c "
REDACTED_a7b84d63
text = '''${poll_text}'''
m = re.search(r'\[POLL\]\s*(.+?)\n([\s\S]+)\$', text, re.MULTILINE)
if m:
    options = [l.strip() for l in m.group(2).split('\n') if l.strip().startswith('- ') and 'CONFIDENCE' not in l]
    print(f'FOUND:{len(options)}')
else:
    print('NOT_FOUND')
")
  if [[ "$has_poll" == "FOUND:2" ]]; then PASS=$((PASS + 1)); else echo "FAIL: poll detection = '$has_poll'"; FAIL=$((FAIL + 1)); fi
}

echo "=== Step-Level Evaluation ==="
echo ""
echo "--- Category Detection ---"
test_category_detection
echo "--- Confidence Extraction ---"
test_confidence_extraction
echo "--- Credential Redaction ---"
test_credential_redaction
echo "--- Poll Detection ---"
test_poll_detection
echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="
exit $((FAIL > 0 ? 1 : 0))
