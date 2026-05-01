# NL-A2A Protocol v2 — Inter-Agent Communication Standard

**Version:** 2.0 (G6 upgrade — aligned with Google A2A spec)
**Date:** 2026-04-10
**Scope:** All inter-tier communication in the Example Corp ChatOps platform
**Spec reference:** [Google A2A](https://github.com/google-a2a/A2A/blob/main/docs/specification.md)

## Overview

NL-A2A v2 defines a standardized protocol for communication between the three agent tiers:
- **Tier 1 (OpenClaw/GPT-5.1):** L1/L2 triage, quick diagnostics, reviews
- **Tier 2 (Claude Code):** Deep analysis, code changes, infrastructure remediation
- **Tier 3 (Human):** Approval gates, plan selection, override

**v2 changes (G6):** Agent cards upgraded to Google AgentCard schema (name, skills, capabilities).
JSON-RPC 2.0 envelope available alongside v1 format. Task lifecycle aligned with Google A2A
(submitted → working → input-needed → done). NL-specific extensions in `_nla2a` namespace.
Fully backwards-compatible — v1 messages still accepted.

---

## Agent Cards

Each agent publishes a machine-readable capability card at a well-known path.
Cards are used by the Runner for capability-aware routing and by agents for
understanding what they can delegate to peers.

### Card Schema (v2 — Google A2A aligned)

```json
{
  "name": "agent-name",
  "description": "what the agent does",
  "url": "endpoint-url",
  "provider": {
    "organization": "Example Corp",
    "url": "https://example.net"
  },
  "version": "YYYY.M.D",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "authentication": {
    "schemes": ["bearer"],
    "credentials": "credential-reference"
  },
  "defaultInputModes": ["text/plain", "application/json"],
  "defaultOutputModes": ["text/plain", "application/json"],
  "skills": [
    {
      "id": "skill-id",
      "name": "Skill Name",
      "description": "what it does",
      "inputModes": ["application/json"],
      "outputModes": ["application/json"],
      "tags": ["category"],
      "examples": ["example usage"]
    }
  ],
  "_nla2a": {
    "tier": 1,
    "model": "model-id",
    "host": "hostname",
    "routing": { "escalateTo": "...", "acceptsFrom": [...] },
    "limits": { "maxConcurrent": 1, "timeout": 120 }
  }
}
```

**Migration notes:** Top-level fields follow Google AgentCard schema. NL-specific
extensions (tier, routing, limits, blocked commands) live under `_nla2a` namespace.
Old `capabilities` array → `skills` array. Old `agent` → `name`.

### Card Locations

| Agent | Card Path |
|-------|-----------|
| OpenClaw (T1) | `a2a/agent-cards/openclaw-t1.json` |
| Claude Code (T2) | `a2a/agent-cards/claude-code-t2.json` |
| Human (T3) | `a2a/agent-cards/human-t3.json` |

---

## Message Envelope

### v2 (JSON-RPC 2.0 — Google A2A aligned)

The preferred envelope for new implementations. Wraps NL-A2A messages in standard
JSON-RPC 2.0 format, enabling future interoperability with external A2A systems.

```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "uuid",
  "params": {
    "id": "task-uuid",
    "message": {
      "role": "agent",
      "parts": [
        {
          "type": "text",
          "text": "Triage findings: host unreachable via SSH..."
        }
      ],
      "metadata": {
        "issueId": "IFRNLLEI01PRD-123",
        "from": { "tier": 1, "agent": "openclaw" },
        "to": { "tier": 2, "agent": "claude-code" },
        "type": "escalation",
        "correlationId": "original-message-id",
        "context": {
          "completedSteps": ["step0_dedup", "step1_create_issue"],
          "confidence": 0.4,
          "promptVariant": "react_v1"
        }
      }
    }
  }
}
```

### v1 (legacy — still accepted)

```json
{
  "protocol": "nl-a2a/v1",
  "messageId": "uuid",
  "timestamp": "ISO-8601",
  "from": { "tier": 1, "agent": "openclaw" },
  "to": { "tier": 2, "agent": "claude-code" },
  "type": "escalation | review | completion | error | status | delegation",
  "issueId": "IFRNLLEI01PRD-123",
  "correlationId": "original-message-id (for replies)",
  "payload": { ... },
  "context": {
    "completedSteps": ["step0_dedup", "step1_create_issue", "step2_investigate"],
    "confidence": 0.4,
    "promptVariant": "react_v1"
  }
}
```

### Message Types

| Type | From → To | Purpose |
|------|-----------|---------|
| `escalation` | T1 → T2 | Triage complete, needs deeper analysis/fix |
| `review` | T1 → T2 (response) | Cross-tier review verdict (AGREE/DISAGREE/AUGMENT) |
| `completion` | T2 → T1/T3 | Session done, results available |
| `error` | Any → Any | Structured error with recovery hints |
| `status` | Any → Any | Progress update (in_progress, blocked, waiting_approval) |
| `delegation` | T2 → T1 | Claude delegates info gathering to OpenClaw |

---

## Task Lifecycle (v2 — Google A2A aligned)

Standard state machine aligned with Google A2A `TaskState`:

```
[submitted] → [working] → [input-needed] → [working] → [completed]
                  ↓              ↓                           ↓
             [canceled]     [canceled]                   [failed]
```

### State mapping (NL-A2A v1 → v2)

| v1 state | v2 state | Description |
|----------|----------|-------------|
| created | submitted | Task received, queued |
| triaging | working | Agent investigating |
| escalated | working | Handed to higher tier |
| in_progress | working | Active investigation/fix |
| waiting_approval | input-needed | Blocked on human input |
| blocked | input-needed | Blocked on external dependency |
| executing | working | Approved plan being executed |
| completed | completed | Task resolved |
| — | failed | Task failed (new in v2) |
| — | canceled | Task canceled by operator (new in v2) |

State transitions are recorded in the `a2a_task_log` SQLite table. The `state`
column accepts both v1 and v2 values during migration.

---

## Type-Specific Payloads

### Escalation (T1 → T2)

```json
{
  "type": "escalation",
  "payload": {
    "summary": "Alert: Devices up/down on nl-pve01",
    "hostname": "nl-pve01",
    "alertRule": "Devices up/down",
    "severity": "critical",
    "site": "nl",
    "triageFindings": "Host unreachable via SSH. LibreNMS confirms down. VMID VMID_REDACTED.",
    "relatedIssues": ["IFRNLLEI01PRD-100"],
    "escalationReason": ["critical", "recurring"]
  }
}
```

### Review (T1 → T2, response)

```json
{
  "type": "review",
  "payload": {
    "verdict": "DISAGREE",
    "confidence": 0.7,
    "reason": "Proposed restart would lose SeaweedFS volume — no PDB",
    "claimsVerified": 2,
    "alternativesConsidered": 1,
    "suggestedAction": "Drain node first, verify SeaweedFS placement"
  }
}
```

### Completion (T2 → system)

```json
{
  "type": "completion",
  "payload": {
    "outcome": "resolved",
    "resolution": "Staggered VM snapshot schedules, etcd fsync normalized",
    "confidence": 0.85,
    "costUsd": 1.23,
    "numTurns": 8,
    "durationSeconds": 340,
    "lesson": "Concurrent VM snapshots on same LVM cause etcd WAL fsync spikes",
    "promptVariant": "react_v2",
    "resolutionType": "approved"
  }
}
```

### Error (Any → Any)

```json
{
  "type": "error",
  "payload": {
    "failedAt": "step3_check_pve_status",
    "completedSteps": ["step0_dedup", "step1_create_issue", "step2_librenms_check"],
    "error": "SSH to nl-pve03 timed out after 10s",
    "partialFindings": "Device is LXC on pve03, LibreNMS shows status=down",
    "suggestedAction": "Check if pve03 itself is down via Proxmox MCP"
  }
}
```

### Delegation (T2 → T1)

```json
{
  "type": "delegation",
  "payload": {
    "command": "kubectl get pods -n monitoring -o wide",
    "purpose": "Check pod placement before drain",
    "expectFormat": "text",
    "timeout": 30
  }
}
```

---

## Bridge REVIEW_JSON Processing

When OpenClaw posts a review with `REVIEW_JSON:{...}`, the Bridge:

1. Parses the JSON from the message body
2. Records verdict in `a2a_task_log`
3. Takes automated action based on verdict:
   - **AGREE** (confidence >= 0.7): Auto-approves by resuming session with "Review: AGREED — proceed"
   - **AGREE** (confidence < 0.7): Posts notice, waits for human confirmation
   - **DISAGREE**: Pauses session, posts alert with reason, waits for human
   - **AUGMENT**: Resumes session with augmented context

---

## Capability-Aware Routing

The Runner's Derive Slot node uses agent cards to determine routing:

| Alert Type | T1 Capability | T2 Capability | Routing |
|------------|--------------|--------------|---------|
| LibreNMS infra | `infra-triage` | `infra-remediation` | T1 triage → T2 fix |
| K8s alert | `k8s-triage` | `k8s-remediation` | T1 triage → T2 fix |
| Maintenance | — | `maintenance-companion` | Direct T2 (bypass T1) |
| Code/feature | — | `code-implementation` | Direct T2 |
| Quick lookup | `youtrack-lookup`, `netbox-lookup` | — | T1 only |

---

## Backwards Compatibility

The envelope format wraps existing payloads. Old-format messages (plain text
CONFIDENCE lines, unstructured ERROR_CONTEXT blocks) continue to work — the
Runner falls back to regex parsing when no envelope is detected.
