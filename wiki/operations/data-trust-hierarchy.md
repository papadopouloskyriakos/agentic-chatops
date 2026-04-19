# Data Trust Hierarchy

> The foundational principle for all infrastructure decisions. Compiled 2026-04-11 14:13 UTC.

## The 4 Levels

1. **Running config on the live device** — SSH and check. This is the ONLY 100% truth.
2. **LibreNMS** — active monitoring, real-time status.
3. **NetBox** — CMDB inventory. Accurate but manually maintained.
4. **03_Lab, GitLab IaC, backups** — supplementary reference. Can be stale.

**If 03_Lab contradicts a live device, the live device wins. Always.**

## Data trust hierarchy

Data trust hierarchy — always follow this order when investigating or making claims:

1. **Running config on the live device** (SSH + `show run`, `ip a`, `pct config`, `kubectl get`) — the ONLY 100% truth
2. **LibreNMS** — active monitoring, shows what's happening NOW
3. **NetBox** — CMDB inventory, accurate but manually maintained — can drift if someone forgets to update
4. **03_Lab, GitLab IaC, backups** — supplementary reference, useful context but can be stale

**Why:** NetBox requires manual updates, so it can drift from reality. LibreNMS actively polls devices so it reflects current state. But even LibreNMS can lag or miss things. The only way to know what a device is actually running is to SSH in and check. 03_Lab xlsx files, IaC configs, and backups are all point-in-time snapshots that may not reflect recent changes.

**How to apply:** During triage, always verify critical facts by checking the live device. Never trust a stale xlsx entry or IaC config over what `show run` returns. When 03_Lab data contradicts live state, the live state wins — and flag the 03_Lab entry as potentially outdated.
