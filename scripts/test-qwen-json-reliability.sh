#!/bin/bash
# IFRNLLEI01PRD-611 validation — qwen2.5:7b first-try JSON reliability.
#
# Runs a Python helper that:
#   - Exercises plan_traversal() (uses _qwen_json) 20x with varied questions
#   - Counts first-try JSON successes (parsed + required keys present)
#   - Target: >=98% (0-1 failures out of 20)
#
# Also smoke-tests the 2 prose callers (rewrite_query, generate_hypothetical_doc)
# to confirm they still return non-empty output after the qwen3->qwen2.5 swap.

set -u
cd "$(dirname "$0")/.."

python3 <<'PYEOF'
import os, sys, re
sys.path.insert(0, "scripts")
sys.path.insert(0, "scripts/lib")
import importlib.util

# Load kb-semantic-search as a module (filename has a hyphen, so importlib trick)
spec = importlib.util.spec_from_file_location("kbss", "scripts/kb-semantic-search.py")
kbss = importlib.util.module_from_spec(spec)
# Silence the caller's stderr for cleaner output — we'll track failures via return values.
import io, contextlib
spec.loader.exec_module(kbss)

# === JSON reliability: 20 varied plan_traversal queries ===
queries = [
    "which services depend on nl-pve01",
    "what incidents affected both sites during Freedom outage",
    "list chaos experiments on the VTI tunnels",
    "show hosts with memory pressure lessons",
    "what cascaded from the GR isolation",
    "incidents where BGP convergence was the root cause",
    "alert rules that fire on the RAG pipeline",
    "lessons from the 2026-04 ASA maintenance window",
    "services involved in dmz container restarts",
    "chaos experiments that verified Freedom failover",
    "which hosts are upstream of portfolio hosting",
    "incidents resolved by the iBGP full mesh fix",
    "hosts where kernel upgrades caused issues",
    "services impacted by the n8n SQLite mutex",
    "what alert rules track OpenClaw sync health",
    "lessons about Zigbee permit-join workflows",
    "chaos tests touching the CH VPS tunnel",
    "incidents where the scanner shun whitelist mattered",
    "services depending on seaweedfs cross-site sync",
    "hosts with recurring apiserver restart events",
]

# Track per-attempt success — re-run _qwen_json manually via plan_traversal
# but without the `attempts=3` ladder so we can measure first-try reliability.
original_qwen_json = kbss._qwen_json

attempt_log = []
def instrumented(prompt, schema_required=None, attempts=3):
    # Force attempts=1 so we observe pure first-try reliability
    result = original_qwen_json(prompt, schema_required=schema_required, attempts=1)
    attempt_log.append(result is not None)
    return result

kbss._qwen_json = instrumented

first_try_pass = 0
with contextlib.redirect_stderr(io.StringIO()) as suppressed:
    for i, q in enumerate(queries, 1):
        plan = kbss.plan_traversal(q)
        if plan is not None:
            first_try_pass += 1

n = len(queries)
rate = first_try_pass * 100.0 / n
print(f"=== _qwen_json first-try JSON reliability ===")
print(f"Successes: {first_try_pass}/{n} = {rate:.1f}%")
print(f"Target: >=98% (max 1 miss)")
print(f"Suppressed stderr ({len(suppressed.getvalue())} bytes)")

# Restore
kbss._qwen_json = original_qwen_json

# === Prose callers smoke ===
print()
print("=== prose callers smoke (rewrite_query + HyDE) ===")

with contextlib.redirect_stderr(io.StringIO()):
    rw = kbss.rewrite_query("pve01 memory pressure apiserver restart")
    hyde = kbss.generate_hypothetical_doc("Freedom ISP PPPoE outage")

print(f"rewrite_query -> {len(rw)} rewrites, sample: {(rw[0] if rw else '<empty>')[:60]!r}")
print(f"generate_hypothetical_doc -> {len(hyde or '')}B, sample: {(hyde or '')[:80]!r}")

# Ensure no <think> leakage in prose output
think_leak = any("<think>" in (r or "") for r in rw) or "<think>" in (hyde or "")
print(f"No <think> tag leakage: {'OK' if not think_leak else 'FAIL — tags present'}")

# === Exit criteria ===
ok = (rate >= 98.0) and (len(rw) > 0) and (hyde is not None) and (not think_leak)
print()
print(f"Overall: {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
PYEOF
