---
name: proactive-scan
description: Daily proactive health scan for pre-alert conditions. Checks disk space, certificate expiry, stale YT issues, VPN status, and SeaweedFS health. User-invocable via /proactive-scan.
allowed-tools: Bash
user-invocable: true
metadata:
  openclaw:
    always: false
---

# Proactive Health Scan

Runs pre-alert health checks to discover degradation before it triggers alert thresholds.

## WHEN to use this skill

- Automatically triggered daily at 06:00 UTC via cron (posts to #chatops)
- User can invoke manually: `/proactive-scan` or `/proactive-scan --site gr`
- "run a health check", "proactive scan", "any pre-alert issues?"

## HOW to use

```bash
# Scan NL site (default)
./skills/proactive-scan/proactive-scan.sh --site nl

# Scan GR site
./skills/proactive-scan/proactive-scan.sh --site gr

# Scan both sites
./skills/proactive-scan/proactive-scan.sh --site nl
./skills/proactive-scan/proactive-scan.sh --site gr
```

## What it checks

| Check | Warning | Critical |
|-------|---------|----------|
| PVE host disk space | >85% | >95% |
| K8s admin cert expiry | <30 days | <7 days |
| Stale YT issues (In Progress) | >7 days | >14 days |
| Stale YT issues (To Verify) | >3 days | >7 days |
| GR VPN tunnel status | — | ping fails |
| SeaweedFS volume count | mismatch | — |

## Output

Reports findings with severity. If critical findings exist, recommend creating a YT issue.
