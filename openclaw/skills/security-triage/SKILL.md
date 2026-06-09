# security-triage

Security scan finding triage — investigates findings from the daily vulnerability scanners.

## Usage

```
./skills/security-triage/security-triage.sh <target_ip> "<finding_title>" <severity> [scanner] [category] [port]
```

## Parameters

| Param | Required | Description |
|-------|----------|-------------|
| target_ip | Yes | Public IP that was scanned |
| finding_title | Yes | Short finding identifier (CVE-ID, "New open port", etc.) |
| severity | Yes | critical, high, medium |
| scanner | No | nlsec01 or grsec01 (auto-detected from target IP) |
| category | No | cve, port, tls, header, exposure (default: unknown) |
| port | No | Affected port number |

## What It Does

1. **NetBox lookup** — identifies which host/service maps to the target IP
2. **Baseline check** — verifies if finding is new vs already-known
3. **Scan context** — retrieves latest nmap/nuclei data from the scanner VM
4. **Quick service check** — for new port findings, identifies the service via nmap

## Scanner Mapping

- `nlsec01` (NL, 10.0.181.X) → scans GR + VPS targets
- `grsec01` (GR, 10.0.X.X) → scans NL + VPS targets

## Escalation

Deep verification (full nuclei re-scan, targeted nmap, testssl) is left to Claude Code (Tier 2).
Claude Code can SSH directly to the scanner VMs for extended investigation.
