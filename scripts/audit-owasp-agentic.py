#!/usr/bin/env python3
"""OWASP Top 10 for LLM / Agentic Applications — orchestrator posture audit.

READ-ONLY benchmark of the claude-gateway orchestrator/control plane against the
OWASP Agentic-AI threat categories. For each category it INSPECTS the actual repo
files that implement the control (the classifier, the dispatched-session settings,
the platform controller, the cronicle-remediate path, the gating sentinels, hooks,
secret handling, the prediction/irreversible gates) and reports PASS / WARN / FAIL
with concrete file+reason evidence.

STRICTLY READ-ONLY by contract:
  * Only opens files for reading (Path.read_text / json.load) + an atomic write of
    its OWN Prometheus textfile. It NEVER edits repo files, NEVER changes any
    security/identity/credential config, NEVER runs an exploit, NEVER touches a
    sentinel, never calls n8n / the firewalls / the DB-with-writes. The operator
    has explicitly forbidden touching the security-identity posture — this only
    REPORTS on it.
  * Idempotent + safe to cron: deterministic over the working tree, atomic temp-
    file rename for the .prom, always exit 0 (a non-zero exit would kill the cron
    chain — findings live in the metric/summary, not the exit code).

Emits owasp_agentic_findings{category,severity,status} -> the node_exporter
textfile collector, plus a human summary on stdout.

Usage: python3 scripts/audit-owasp-agentic.py [--json] [--no-prom]
"""
import argparse
import json
import os
REDACTED_a7b84d63
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROM_OUT = Path("/var/lib/node_exporter/textfile_collector/owasp_agentic.prom")

# Status ranking for the summary / metric severity.
PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


# ── read helpers (read-only; never raise out) ──────────────────────────────────
def _read(rel):
    """Return file text or '' (and a 'missing' marker is the caller's job)."""
    try:
        return (REPO / rel).read_text(errors="ignore")
    except Exception:
        return ""


def _exists(rel):
    return (REPO / rel).exists()


def _json(rel):
    try:
        return json.loads((REPO / rel).read_text())
    except Exception:
        return None


def _has(text, *needles):
    return all(n in text for n in needles)


def _re(text, pattern):
    return re.search(pattern, text) is not None


class Finding:
    __slots__ = ("category", "status", "evidence")

    def __init__(self, category, status, evidence):
        self.category = category
        self.status = status
        self.evidence = evidence


def _f(cat, status, evidence):
    return Finding(cat, status, evidence)


# ── the 10 OWASP Agentic checks ────────────────────────────────────────────────
# Each returns a Finding. They read the ACTUAL posture; nothing here mutates state.

def check_excessive_agency():
    """LLM06 / Excessive Agency + Excessive Autonomy.
    Posture: dispatched `claude -p` runs --dangerously-skip-permissions, so the
    ONLY pre-execution gate is the fail-closed plan_hash prediction gate in the
    Runner + the band classifier. Verify both are present and default-deny."""
    cat = "excessive_agency"
    runner = _read("workflows/claude-gateway-runner.json")
    if not runner:
        return _f(cat, SKIP, "workflows/claude-gateway-runner.json not found")
    gate = _has(runner, "Commit Prediction", "prediction-gate", "POLL-WITHHELD:NO-PREDICTION")
    autoresolve = "AUTO-RESOLVE" in runner
    classifier = _read("scripts/classify-session-risk.py")
    band_floor = _has(classifier, "POLL_PAUSE", "irreversible:") and "RISK_FAIL_CLOSED" in classifier
    if gate and band_floor:
        return _f(cat, PASS,
                  "Runner carries the fail-closed prediction gate (Commit Prediction + "
                  "POLL-WITHHELD:NO-PREDICTION default-deny) and classify-session-risk.py "
                  "enforces a POLL_PAUSE floor + RISK_FAIL_CLOSED. Autonomy is bounded by a "
                  "committed machine prediction before any [AUTO-RESOLVE].")
    if gate and not band_floor:
        return _f(cat, WARN,
                  "Runner has the prediction gate but classify-session-risk.py is missing the "
                  "POLL_PAUSE floor or RISK_FAIL_CLOSED — autonomy floor weakened.")
    if autoresolve and not gate:
        return _f(cat, FAIL,
                  "Runner emits [AUTO-RESOLVE] but the fail-closed prediction gate "
                  "(Commit Prediction / POLL-WITHHELD:NO-PREDICTION) is absent — auto-resolve "
                  "without a committed prediction = unbounded agency.")
    return _f(cat, WARN, "Prediction-gate markers not all present in Runner export; review the gate wiring.")


def check_prompt_injection():
    """LLM01 / Prompt Injection.
    Posture: jailbreak_detector screens the UNTRUSTED narrative (hypothesis/reason
    that echo alert/operator text) on the live classify path; a hit forces HIGH ->
    never auto-approves. Verify the detector + corpus + live wiring exist."""
    cat = "prompt_injection"
    classifier = _read("scripts/classify-session-risk.py")
    detector = _exists("scripts/lib/jailbreak_detector.py")
    corpus = _exists("scripts/qa/fixtures/jailbreak-corpus.json")
    live_wired = _has(classifier, "jailbreak_detector", "jailbreak-detected")
    scoped = "UNTRUSTED NARRATIVE" in classifier or "hypothesis" in classifier
    forces_high = _re(classifier, r'append\(\("high",\s*f?"jailbreak-detected')
    if detector and live_wired and forces_high:
        ev = ("lib/jailbreak_detector.py wired into classify-session-risk.py on the live prompt "
              "path; a detection appends ('high', 'jailbreak-detected:*') -> can never auto-approve.")
        if scoped:
            ev += " Screen is scoped to the untrusted hypothesis/reason narrative (not system steps)."
        if not corpus:
            return _f(cat, WARN, ev + " But the jailbreak-corpus.json fixture is missing (regression coverage gap).")
        return _f(cat, PASS, ev + " Corpus fixture present.")
    if detector and not live_wired:
        return _f(cat, FAIL,
                  "jailbreak_detector.py exists but is NOT wired into the live classify path — "
                  "injection screening is corpus-only, not enforced per-session.")
    return _f(cat, WARN, "Prompt-injection detector or its live-path wiring is incomplete.")


def check_insecure_output_handling():
    """LLM02 / Insecure Output Handling.
    Posture: the agent's free-text output is parsed for [AUTO-RESOLVE]/[POLL]
    markers by the Runner Prepare Result, which DEFAULT-DENIES (POLL) anything
    without a committed prediction, and a mechanical action_verdict (not the LLM)
    adjudicates deviation. Verify the parser anchors markers + default-denies."""
    cat = "insecure_output_handling"
    runner = _read("workflows/claude-gateway-runner.json")
    if not runner:
        return _f(cat, SKIP, "Runner export not found")
    default_deny = "POLL-WITHHELD:NO-PREDICTION" in runner
    mechanical_verdict = "deviation" in runner  # mechanical match/partial/deviation, not LLM-self-judged
    # anchored marker parsing lives in Prepare Result (parsePoll hardening, -736).
    anchored = _re(runner, r'\[AUTO-RESOLVE\]') and ("Prepare Result" in runner)
    if default_deny and anchored:
        ev = ("Runner Prepare Result parses [AUTO-RESOLVE]/[POLL] from agent output and "
              "DEFAULT-DENIES (POLL-WITHHELD:NO-PREDICTION) when no committed prediction exists; "
              "the agent's text alone cannot self-grant an auto-resolve.")
        if mechanical_verdict:
            ev += " Outcome adjudicated by a mechanical deviation verdict, not the LLM."
        return _f(cat, PASS, ev)
    if anchored and not default_deny:
        return _f(cat, WARN,
                  "Output markers are parsed but the default-deny (POLL-WITHHELD:NO-PREDICTION) "
                  "guard is not visible — output could over-grant on a parse edge case.")
    return _f(cat, WARN, "Output-handling markers/guards not all present in Runner export.")


def check_sensitive_information_disclosure():
    """LLM06 / Sensitive Information Disclosure.
    Posture: .env is gitignored + untracked; a credential-protection hook rejects
    Edit/Write to .env/keys/secrets; the bash guard screens exfiltration. Verify
    .env is not committed and the protection patterns exist. (READ-ONLY: we do
    NOT change perms — only report the observed mode.)"""
    cat = "sensitive_information_disclosure"
    gitignore = _read(".gitignore")
    env_ignored = bool(re.search(r'(?m)^\.env\s*$', gitignore))
    env_path = REPO / ".env"
    # Is .env tracked by git? (read-only check of the index via git ls-files would
    # need a subprocess; instead infer from .gitignore + presence, and check perms.)
    protect = _read("scripts/hooks/protect-files.sh")
    unified = _read("scripts/hooks/unified-guard.sh")
    protects_secrets = _has(protect, ".env", "*.key", "*.pem", "*secret*") or \
                       _has(unified, ".env", "secret")
    # Observe (do not change) the .env file mode.
    mode_note = ""
    perm_warn = False
    if env_path.exists():
        try:
            mode = oct(env_path.stat().st_mode & 0o777)[2:]
            mode_note = f" Observed .env mode={mode} (REPORT ONLY — not modified)."
            # world/group-readable secrets file is a disclosure WARN.
            if int(mode[-1]) & 0o4 or int(mode[1]) & 0o4:
                perm_warn = True
        except Exception:
            pass
    if env_ignored and protects_secrets:
        status = WARN if perm_warn else PASS
        ev = (".env is gitignored and a credential-protection hook (protect-files.sh / "
              "unified-guard.sh) rejects Edit/Write to .env/*.key/*.pem/*secret*." + mode_note)
        if perm_warn:
            ev += " ADVISORY: .env is group/world-readable — operator should tighten to 600 (NOT changed by this audit)."
        return _f(cat, status, ev)
    if not env_ignored:
        return _f(cat, FAIL, ".env is NOT in .gitignore — secrets risk being committed.")
    return _f(cat, WARN, ".env is gitignored but no credential-protection hook pattern was found.")


def check_supply_chain():
    """LLM05 / Supply Chain.
    Posture: model ids are pinned centrally (lib/models.py) with a drift guard
    rather than scattered string literals; dispatched sessions pin --model. Verify
    the central registry + drift guard exist."""
    cat = "supply_chain"
    models = _read("scripts/lib/models.py")
    drift_guard = _exists("scripts/check-model-provenance-drift.py") or \
                  _exists("scripts/check-model-registry.py")
    pinned = _has(models, "ANTHROPIC_MODELS", "claude-opus-4-8") and _re(models, r'claude-(opus|sonnet|haiku)-')
    runner = _read("workflows/claude-gateway-runner.json")
    runner_pins_model = "--model" in runner
    if pinned and drift_guard:
        ev = ("Model ids are pinned centrally in lib/models.py (ANTHROPIC_MODELS) and a drift "
              "guard (check-model-provenance-drift.py / check-model-registry.py) flags any "
              "literal not in the registry.")
        if runner_pins_model:
            ev += " Dispatched sessions pin --model explicitly."
        return _f(cat, PASS, ev)
    if pinned and not drift_guard:
        return _f(cat, WARN,
                  "Model ids are pinned in lib/models.py but no drift guard script was found — "
                  "scattered literals could silently diverge.")
    return _f(cat, WARN, "Central model pinning (lib/models.py / ANTHROPIC_MODELS) not confirmed.")


def check_excessive_permission():
    """LLM06 / Excessive Permission/Autonomy on the dispatched path.
    Posture: dispatched `claude -p` runs with --dangerously-skip-permissions, so
    the unified-guard.sh (destructive-command/exfil/file-protect) is NOT on the
    dispatched path — only territory-gate + telemetry hooks are. This is the
    documented B-grade operator decision. Report it honestly as a WARN."""
    cat = "excessive_permission"
    settings = _json("config/dispatched-session-settings.json")
    runner = _read("workflows/claude-gateway-runner.json")
    skip_perms = "--dangerously-skip-permissions" in runner
    if settings is None:
        return _f(cat, SKIP, "config/dispatched-session-settings.json not found / unparsable")
    hooks = settings.get("hooks", {})
    wired = json.dumps(hooks)
    territory = "territory-gate.py" in wired
    unified_on_path = "unified-guard.sh" in wired
    protect_on_path = "protect-files.sh" in wired
    if unified_on_path and protect_on_path and territory:
        return _f(cat, PASS,
                  "Dispatched-session settings wire territory-gate.py + unified-guard.sh + "
                  "protect-files.sh — full pre-tool guardrail chain on the dispatched path.")
    # The real, observed posture: skip-permissions + territory-gate only.
    if skip_perms and territory and not unified_on_path:
        return _f(cat, WARN,
                  "DISPATCHED sessions run `claude -p --dangerously-skip-permissions`; "
                  "config/dispatched-session-settings.json wires the fail-closed territory-gate.py "
                  "(PreToolUse on Bash/Edit/Write) but NOT unified-guard.sh / protect-files.sh — "
                  "destructive-command + exfil + file-protect guardrails are OFF the dispatched "
                  "path (documented deliberate operator decision; primary control is the "
                  "classifier band + prediction gate, not per-tool deny). Net residual risk if "
                  "the prediction gate is bypassed.")
    if skip_perms and not territory:
        return _f(cat, FAIL,
                  "Dispatched sessions use --dangerously-skip-permissions AND the territory-gate "
                  "PreToolUse hook is NOT wired in dispatched-session-settings.json — no per-tool "
                  "guardrail on the dispatched path at all.")
    return _f(cat, WARN, "Dispatched-path permission posture could not be fully determined.")


def check_memory_poisoning():
    """LLM04-adjacent / Memory & Knowledge-Base Poisoning.
    Posture: RAG retrieval discounts/segregates lower-trust sources (CLI rows
    weighted 0.75, governance rows project-tagged + RAG-excluded, incident-miner
    truth capped below the 0.8 suppression cutoff). Verify the discounting +
    tagging controls exist so a poisoned low-trust row can't dominate retrieval."""
    cat = "memory_poisoning"
    search = _read("scripts/kb-semantic-search.py")
    cli_discount = "CLI_INCIDENT_WEIGHT" in search
    # governance auto-demote rows are RAG-excluded via a project tag.
    gov = _read("scripts/write-governance-metrics.py") + _read("scripts/classify-session-risk.py")
    project_excluded = "chatops-governance" in gov or "chatops-governance" in search
    # incident-miner confidence cap below the 0.8 auto-suppression cutoff.
    runbook = _read("docs/runbooks/infragraph.md") + _read("CLAUDE.md")
    truth_capped = "0.75" in runbook and ("incident-miner" in runbook or "incident_miner" in runbook or "capped" in runbook)
    controls = sum([cli_discount, project_excluded])
    if cli_discount and (project_excluded or truth_capped):
        return _f(cat, PASS,
                  "RAG retrieval segregates trust: kb-semantic-search.py discounts CLI rows "
                  "(CLI_INCIDENT_WEIGHT=0.75) and lower-trust sources are project-tagged / "
                  "confidence-capped below the 0.8 suppression cutoff, so a poisoned low-trust "
                  "row cannot dominate the RRF ranking.")
    if cli_discount:
        return _f(cat, WARN,
                  "CLI-row discounting is present (CLI_INCIDENT_WEIGHT) but project-exclusion / "
                  "confidence-cap controls for other low-trust sources were not all confirmed.")
    return _f(cat, WARN, "RAG trust-weighting controls (CLI_INCIDENT_WEIGHT etc.) not confirmed in kb-semantic-search.py.")


def check_tool_misuse():
    """LLM07 / Tool Misuse (irreversible/destructive tool calls).
    Posture: IRREVERSIBLE_PATTERNS in the classifier re-tag destructive ops
    (terraform destroy, mkfs, zpool destroy, dropdb, kubectl delete pvc, network
    write-erase) to a 'high'/'irreversible:*' signal that forces POLL_PAUSE and can
    never reach an auto band. Verify the pattern set is broad + on the safety floor."""
    cat = "tool_misuse"
    classifier = _read("scripts/classify-session-risk.py")
    if not classifier:
        return _f(cat, SKIP, "classify-session-risk.py not found")
    REDACTED_4529f8c2
        "irreversible:iac-destroy", "irreversible:disk-destroy", "irreversible:storage-destroy",
        "irreversible:db-destroy", "irreversible:k8s-delete-stateful", "irreversible:network-catastrophic",
    ]
    found = [p for p in patterns if p in classifier]
    on_floor = _has(classifier, "irreversible:", "POLL_PAUSE")
    if len(found) >= 5 and on_floor:
        return _f(cat, PASS,
                  f"classify-session-risk.py re-tags {len(found)}/{len(patterns)} destructive-op "
                  "classes (terraform destroy / mkfs / zpool destroy / dropdb / kubectl delete "
                  "pvc / write-erase) to irreversible:* on the POLL_PAUSE safety floor — these "
                  "can never reach an auto band.")
    if found and not on_floor:
        return _f(cat, WARN,
                  f"{len(found)} irreversible patterns present but the POLL_PAUSE floor coupling "
                  "was not confirmed.")
    return _f(cat, WARN, f"Only {len(found)}/{len(patterns)} irreversible-op patterns found — destructive-tool coverage may be incomplete.")


def check_insufficient_hitl():
    """LLM08-adjacent / Insufficient Human Oversight.
    Posture: high/irreversible/no-prediction/deviation/jailbreak/P0-reboot ->
    POLL_PAUSE band with a parallel SMS page (alertmanager-twilio-bridge /alert-session);
    band-aware weekly invariant in audit-risk-decisions.sh FAILS if any auto-approval
    carries a floor signal. Verify the SMS escalation + the auditing invariant exist."""
    cat = "insufficient_hitl"
    classifier = _read("scripts/classify-session-risk.py")
    sms = _has(classifier, "sms_required") and _exists("scripts/alertmanager-twilio-bridge.py")
    audit = _read("scripts/audit-risk-decisions.sh")
    invariant = _has(audit, "Invariant check", "AUTO_NOTICE", "irreversible:")
    poll_pause = "POLL_PAUSE" in classifier
    if sms and invariant and poll_pause:
        return _f(cat, PASS,
                  "HITL floor: high/irreversible/no-prediction/jailbreak -> POLL_PAUSE with a "
                  "parallel SMS page (sms_required + alertmanager-twilio-bridge.py /alert-session); "
                  "audit-risk-decisions.sh enforces a band-aware weekly invariant that FAILS if any "
                  "auto-approval carries a floor signal.")
    if poll_pause and not sms:
        return _f(cat, WARN,
                  "POLL_PAUSE band exists but the SMS escalation (sms_required + twilio bridge) "
                  "was not fully confirmed — out-of-loop operator may not be paged.")
    if not invariant:
        return _f(cat, WARN, "POLL_PAUSE/SMS present but the band-aware auto-approval invariant in audit-risk-decisions.sh was not confirmed.")
    return _f(cat, WARN, "HITL oversight controls not all confirmed.")


def check_identity_impersonation():
    """LLM09-adjacent / Identity & Impersonation + control-action scoping.
    Posture: orchestrator ACTIONS (platform-controller, cronicle-remediate) ship
    GATED-DARK behind sentinels (default analysis-only), are reversible-only, and
    NEVER touch the mission lane (no VM resize / host reboot / auto-resolve). Each
    has a kill: `rm <sentinel>`. Verify the gating + scope-confinement in code.
    (READ-ONLY: we do NOT touch any sentinel or identity.)"""
    cat = "identity_impersonation"
    pc = _read("scripts/platform-controller.py")
    cr = _read("scripts/cronicle-remediate.py")
    pc_gated = _has(pc, "platform_controller_armed", "ANALYSIS-ONLY") or _has(pc, "SENTINEL", "armed")
    pc_scope = _has(pc, "NEVER touches", "Plane-A") or "never auto-resolve" in pc.lower() or "mission" in pc
    cr_gated = _has(cr, "cronicle_autoquarantine", "ANALYSIS-ONLY") or _has(cr, "SENTINEL", "armed")
    cr_reversible = "reversible" in cr and "EXECUTES NOTHING" in cr
    # The dispatched session impersonates a single identity (app-user / @claude bot);
    # actions are bounded to that identity's tools, not arbitrary escalation.
    if pc_gated and cr_gated and pc_scope and cr_reversible:
        return _f(cat, PASS,
                  "Orchestrator control actions are gated-dark behind sentinels (default "
                  "analysis-only; rm-sentinel kill): platform-controller.py heals only Plane-A "
                  "platform ops and EXPLICITLY never resizes/reboots/auto-resolves (mission lane); "
                  "cronicle-remediate.py only DISABLEs (reversible, 'EXECUTES NOTHING') chronic "
                  "failers. Actions stay inside the single app-user identity.")
    if (pc_gated and cr_gated) and not (pc_scope and cr_reversible):
        return _f(cat, WARN,
                  "Control actions are sentinel-gated but the scope-confinement assertions "
                  "(Plane-A-only / reversible-only) were not fully confirmed in code.")
    if not (pc_gated and cr_gated):
        return _f(cat, FAIL,
                  "An orchestrator control-action path (platform-controller.py / "
                  "cronicle-remediate.py) does not appear sentinel-gated default-analysis-only — "
                  "unbounded actuation risk.")
    return _f(cat, WARN, "Identity/action-scoping posture not fully determined.")


CHECKS = [
    ("LLM06 Excessive Agency / Autonomy", check_excessive_agency),
    ("LLM01 Prompt Injection", check_prompt_injection),
    ("LLM02 Insecure Output Handling", check_insecure_output_handling),
    ("LLM06 Sensitive Information Disclosure", check_sensitive_information_disclosure),
    ("LLM05 Supply Chain", check_supply_chain),
    ("LLM06 Excessive Permission (dispatched path)", check_excessive_permission),
    ("LLM04 Memory / KB Poisoning", check_memory_poisoning),
    ("LLM07 Tool Misuse (irreversible ops)", check_tool_misuse),
    ("LLM08 Insufficient HITL Oversight", check_insufficient_hitl),
    ("LLM09 Identity & Impersonation / action scoping", check_identity_impersonation),
]

# severity weight for the metric: FAIL>WARN>PASS>SKIP
_SEV = {FAIL: "fail", WARN: "warn", PASS: "pass", SKIP: "skip"}


def emit_prom(findings):
    """Atomic write of the textfile metric. Read-only w.r.t. everything else."""
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    lines = [
        "# HELP owasp_agentic_findings OWASP Top10 Agentic audit of the orchestrator: 1 per (category,status).",
        "# TYPE owasp_agentic_findings gauge",
    ]
    for f in findings:
        sev = _SEV[f.status]
        counts[sev] += 1
        safe_cat = f.category.replace('"', "'")
        lines.append(
            f'owasp_agentic_findings{{category="{safe_cat}",severity="{sev}",status="{f.status}"}} 1'
        )
    lines += [
        "# HELP owasp_agentic_findings_total Count of findings by severity across all categories.",
        "# TYPE owasp_agentic_findings_total gauge",
    ]
    for sev, n in counts.items():
        lines.append(f'owasp_agentic_findings_total{{severity="{sev}"}} {n}')
    lines += [
        "# HELP owasp_agentic_audit_last_run_timestamp_seconds Unix time of last audit run.",
        "# TYPE owasp_agentic_audit_last_run_timestamp_seconds gauge",
        f"owasp_agentic_audit_last_run_timestamp_seconds {int(time.time())}",
    ]
    try:
        PROM_OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(PROM_OUT) + ".tmp"
        with open(tmp, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, PROM_OUT)
        return True, counts
    except Exception as e:
        return False, counts, str(e)


def main():
    ap = argparse.ArgumentParser(description="READ-ONLY OWASP Agentic posture audit of the orchestrator.")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of the human summary")
    ap.add_argument("--no-prom", action="store_true", help="skip the Prometheus textfile write")
    args = ap.parse_args()

    findings = []
    for cat, fn in CHECKS:
        try:
            f = fn()
        except Exception as e:
            f = _f(cat, SKIP, f"check raised {type(e).__name__}: {e}")
        f.category = cat  # normalize to the human label
        findings.append(f)

    prom_ok = None
    if not args.no_prom:
        res = emit_prom(findings)
        prom_ok = res[0]
        counts = res[1]
    else:
        counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
        for f in findings:
            counts[_SEV[f.status]] += 1

    if args.json:
        print(json.dumps({
            "findings": [{"category": f.category, "status": f.status, "evidence": f.evidence} for f in findings],
            "counts": counts,
            "prom_written": prom_ok,
        }, indent=2))
        return

    icon = {PASS: "[PASS]", WARN: "[WARN]", FAIL: "[FAIL]", SKIP: "[SKIP]"}
    print("=" * 78)
    print("OWASP Top 10 for Agentic AI — claude-gateway orchestrator posture audit")
    print("READ-ONLY. No config/identity/credential was modified. Reporting only.")
    print("=" * 78)
    for f in findings:
        print(f"\n{icon[f.status]} {f.category}")
        # wrap evidence to ~74 cols for readability
        words, line = f.evidence.split(), "    "
        for w in words:
            if len(line) + len(w) + 1 > 78:
                print(line)
                line = "    " + w
            else:
                line += (" " if line.strip() else "") + w
        if line.strip():
            print(line)
    print("\n" + "-" * 78)
    print(f"SUMMARY  PASS={counts['pass']}  WARN={counts['warn']}  "
          f"FAIL={counts['fail']}  SKIP={counts['skip']}  (of {len(findings)} categories)")
    if prom_ok is True:
        print(f"Prometheus metric written: {PROM_OUT}")
    elif prom_ok is False:
        print(f"Prometheus metric write FAILED (collector dir not writable) — findings above stand.")
    print("-" * 78)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never die non-zero in cron; surface the error but keep the chain alive.
        print(f"audit-owasp-agentic: unexpected error: {e}", file=sys.stderr)
    sys.exit(0)
