---
name: k8s-triage
description: Kubernetes alert triage — dedup via YT search, deep control plane investigation, auto-escalation for recurring/flapping/control-plane alerts.
allowed-tools: Bash
user-invocable: true
metadata:
  openclaw:
    always: true
---

# Kubernetes Alert Triage

When you see a message containing `k8s-triage.sh` in `#infra-nl-prod` or `#infra-gr-prod`, you MUST run it using the `exec` tool immediately. Do NOT ask questions.

## Usage

```bash
./skills/k8s-triage/k8s-triage.sh "<alertname>" "<severity>" "<namespace>" "<summary>" "<node>" "<pod>" [--site nl|gr]
```

Site is auto-detected from node name prefix (`grskg*` → GR, otherwise NL). Use `--site` to override.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `FORCE_ESCALATE=true` | Escalate regardless of severity (set by n8n for flapping alerts) |
| `EXISTING_ISSUE=ID` | Reuse this YT issue instead of creating new |
| `SKIP_ESCALATION=true` | Skip escalation step (for testing) |

## CRITICAL RULES

1. **ALWAYS use the `exec` tool** to run the script. Do NOT describe what to do.
2. **Do NOT make changes.** All investigation is READ-ONLY (kubectl get/describe/logs only).
3. **The script handles everything** — YT dedup, issue creation, investigation, findings, escalation.

## What's New (v2)

### Issue Deduplication (Step 0)
Before creating a new YT issue, the script searches YouTrack for existing open issues with the same Alert Rule created within 24h. If found, it reuses that issue instead of creating a duplicate. Also searches for **related** issues (same node or namespace within 12h) and lists them in the findings.

### Control Plane Deep Investigation
When the alert involves a control plane component (apiserver, etcd, controller-manager, scheduler), the script performs cross-component investigation:
- etcd pod status + logs (all members)
- apiserver pods + restart counts + error logs (all instances)
- controller-manager + scheduler status
- Control plane resource usage (kubectl top)

### Smart Escalation (Step 5)
Escalation is triggered by ANY of these conditions:
- **Critical severity** (unchanged)
- **Recurring alert** (reusing an existing issue)
- **Forced escalation** (`FORCE_ESCALATE=true`, set by n8n for flapping alerts)
- **Control plane warning** (all control plane alerts escalate regardless of severity)

## Integration Details

### Register Callback
After creating/reusing the YouTrack issue, the script POSTs a register callback to n8n so the Prometheus Alert Receiver can track the issue:
```
POST /webhook/prometheus-alert (or /webhook/prometheus-alert-gr for GR site)
{
  "action": "register",
  "alertKey": "<alertname>:<namespace>",
  "issueId": "<IFRNLLEI01PRD-NNN or IFRGRSKG01PRD-NNN>"
}
```

### YouTrack Custom Fields Set
The script sets 6 custom fields on newly created issues:
- **Hostname** — K8s node name (or "k8s-cluster" for cluster-wide alerts)
- **Alert Rule** — Prometheus alert name (e.g., `KubePodCrashLooping`)
- **Severity** — `critical` or `warning`
- **Namespace** — K8s namespace where the alert fired
- **Pod** — affected pod name (if applicable)
- **Alert Source** — `prometheus` (distinguishes from LibreNMS alerts)
