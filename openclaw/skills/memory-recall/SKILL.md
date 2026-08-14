---
name: memory-recall
description: Query OpenClaw's episodic memory — past triage outcomes, host patterns, alert history. Use before triage to check if you've seen this host/alert before and what happened.
allowed-tools: Bash
user-invocable: false
metadata:
  openclaw:
    always: true
---

# Memory Recall

Query your own past triage outcomes to inform current investigations.

## WHEN to use

- Before starting a triage, check if you've handled this host or alert type before
- When you see a recurring alert, look up what happened last time
- When asked "have you seen this before?"

## HOW to use

```bash
./skills/memory-recall/memory-recall.sh <hostname|alertname|keyword>
```

Examples:
- `./skills/memory-recall/memory-recall.sh nl-pve01`
- `./skills/memory-recall/memory-recall.sh CiliumAgentNotReady`
- `./skills/memory-recall/memory-recall.sh etcd`

The output shows your past triage outcomes: what you found, whether you escalated, and at what confidence level.
