# Security Operations (ChatSecOps)

> CrowdSec, scanners, MITRE ATT&CK. Compiled 2026-07-03 04:30 UTC.

## Security scan report — known-noise filter for our topology

When auditing weekly-scan reports, treat the following as **known noise** and do not propose action unless the underlying topology has changed.

**Why:** Re-deriving each of these from first principles burns 15-30 min per scan review. The signal/noise ratio of these reports is low; pre-filtering recovers it.

**How to apply:** Before opening the scan report, mentally subtract these. Then look at what's left.

### nmap NSE — always noise on our stack

| Finding | Why it's noise |
|---|---|
| `CVE-2007-6750` Slowloris "LIKELY VULNERABLE" | nmap heuristic that any nginx/OpenResty trips. Our edge is nginx/OpenResty everywhere; `client_header_timeout` + `worker_connections` mitigate the actual attack. |
| `CVE-2011-3192` Apache Range DoS "VULNERABLE" | Wrong product. We run nginx, not Apache httpd. nmap's check is banner-loose and false-positives on any server that handles `Range:` gracefully. |
| `http-csrf` / `http-stored-xss` / `http-dombased-xss` "Couldn't find" | These are clean signals (no finding); they show in the report only because nmap NSE prints status, not because anything is wrong. |

### Banner mis-identifications

- `203.0.113.X:2022` reports as `FortiSSH (protocol 2.0)`. **It is not Fortinet.** It's NAT'd to `nlsftpgo01`; nmap is confusing SFTPGo's Go-based SSH banner. Verify SFTPGo version when in doubt.

### testssl baseline-acceptable findings

The following 3-finding cluster is the OpenVPN-AS default self-signed cert at `nloas01` (203.0.113.X NAT). It's behind `WHITELIST_OAS`. Cosmetic only.
- `Serial NOT ok: length should be >= 64 bits entropy (is: 4 bytes)`
- `Chain of trust NOT ok (self signed CA in chain)`
- `Neither CRL nor OCSP URI provided`

If you want it gone from the baseline: install LE cert on `nloas01`. Otherwise: accept.

### testssl wording you must read carefully

- `BREACH (CVE-2013-3587) potentially NOT ok, "gzip" HTTP compression detected. - only supplied "/" tested` — this means *"compression detected; the actual attack requires CSRF-token-in-body reflection that I (testssl) cannot verify with one GET."* Do **not** treat this as "verified vulnerable." On our topology (Hugo static + allowlisted admin endpoints) it's not exploitable. Walk the BREACH preconditions per host before recommending action.

### What to DO check on every scan report

- New port appearing on a previously-filtered IP → real signal.
- Open port on a host that should be allowlist-only → check ACL (config drift).
- Nuclei finding count of 0: plausible for our patched surface, **but** confirm the scanner's cron PATH includes `/usr/local/bin` (`export PATH` in `weekly-scan.sh`) — silent-fail precedent on `nlsec01` 2026-05-04 (memory `scanner_nuclei_silently_broken_20260504`). The fix should be mirrored on `grsec01`; verify if you can reach the host.
- Cert expiry creeping inside 14 days on any LE-fronted host.

## security_alert_receivers

## Security Alert Receiver Workflows (created 2026-03-29)

**NL:** `pyIl40Qxj6BV5znI` — 25 nodes, webhook `/security-alert` → `#infra-nl-prod`, YT `IFRNLLEI01PRD`
**GR:** `HkiG8sPBWcX5tVy6` — 25 nodes, webhook `/security-alert-gr` → `#infra-gr-prod`, YT `IFRGRSKG01PRD`

### Architecture
- Webhook → Load State + Maint → Parse Scan → Save State → Has Findings? → Post Alert → [Needs YT + Should Escalate + Should Post Baseline Poll]
- **Repeat-action logic:** Fetch Issue State → Evaluate (comment/reopen/new) → Switch V3.2 → route
- **Baseline poll:** When register callback has `inBaseline=false`, posts MSC3381 poll asking operator to add to baseline
- **Triage lock:** `mkdir /tmp/sec-triage-lock-{target}` (300s TTL)
- **Set Security Fields node (added 2026-03-30):** POST `/api/commands` after Register Issue to set Hostname, Severity, Alert Source custom fields on YT issues
- **Register Issue guard (fixed 2026-03-30):** Validates `ytResponse.idReadable` before use — falls back to `'(creation failed)'` instead of `undefined`

### Scanner VMs (daily cron 03:00/03:15 UTC)
- nlsec01 (10.0.181.X): scans GR + VPS targets. SSH: `operator@` with one_key, sudo `REDACTED_PASSWORD`
- grsec01 (10.0.X.X): scans NL + VPS targets. Same credentials.
- 24 tools: nmap, nuclei (12,763 templates), testssl, nikto, sqlmap, ffuf, httpx, etc.
- **Scanner perspective bias:** Scanners traverse VPN, can see ACL-protected services (ASDM 8080/8443) that public internet cannot. Always verify from VPS before escalating.

### OpenClaw Integration (security-triage.sh — 10 steps)
1. NetBox CMDB lookup
2. Baseline check
3. Latest scan context
4. Quick service check (nmap -sV)
4b. CrowdSec local enrichment (4 hosts)
4c. CrowdSec CTI API (gated behind CROWDSEC_CTI_KEY, critical/high only)
4d. GreyNoise Community (free, no auth — mass scanner vs targeted)
4e. AbuseIPDB (gated behind ABUSEIPDB_KEY)
4f. Retroactive syslog hunt (if 2+ sources confirm malicious)
4g. EPSS scoring for CVE findings (FIRST.org API, free)
5. YT comment
6. Register callback (includes inBaseline, finding, port, scanner)
- **Step 3 fix (2026-03-30):** Moved python3 JSON parsing local (out of SSH+sudo nesting) to fix triple-escape failure
- **Output:** TRIAGE_JSON with mitreAttack, greynoise, abuseipdb, epssScore, baselineSuggestion, maliciousSources
- **Evidence:** Structured JSON per triage in `evidence/` dir with SHA-256 hash

## CrowdSec Alert Receiver Workflows (created 2026-03-29)

**NL:** `eJ0rX9um4jBuKBtn` — 22 nodes, webhook `/crowdsec-alert` → `#infra-nl-prod`
**GR:** `dr37fPJAZ9a3JRdT` — 22 nodes, webhook `/crowdsec-alert-gr` → `#infra-gr-prod`

### Architecture
- Webhook → Load State + Maint + Learning DB → Parse Alert (dedup, flap, cross-host, MITRE, auto-suppress) → Save State + Stats → Has Content? → Post Alert [with ATT&CK T-code] → [Needs YT + Should Escalate]
- **Learning loop:** `crowdsec_scenario_stats` SQLite table, `crowdsec-learn.sh` (6h cron) auto-suppresses noisy scenarios
- **MITRE ATT&CK:** `mitre-mapping.json` (45 scenarios → 21 techniques), T-code in Matrix messages
- **Persistence:** `active-crowdsec-alerts.json` (NL), `active-crowdsec-alerts-gr.json` (GR)

### CrowdSec Hosts (6 total)

| Host | Type | Status |
|------|------|--------|
| chzrh01vps01 | CH VPS | Running, /crowdsec-alert |
| notrf01vps01 | NO VPS | Running, /crowdsec-alert |
| nl-dmz01 | NL DMZ | Running, /crowdsec-alert |
| gr-dmz01 | GR DMZ | Running, /crowdsec-alert-gr |
| nlmattermost01 | NL LXC | Running, CAPI enrolled (fixed 2026-03-29) |
| nl-matrix01 | NL systemd | Running (dead docker block removed 2026-03-29) |

## Baseline Management
- **baseline-add.sh:** OpenClaw skill, SSHes to scanner, appends with 90-day expiry date
- **baseline-review.sh:** Weekly Monday 08:00 cron, checks expired entries, posts to Matrix
- **Baseline poll:** Security receiver posts MSC3381 poll on new findings for one-click approval

## ATT&CK Navigator
- Self-hosted at http://10.0.181.X:8080 (nlsec01 Docker)
- Public: https://attacknavigator.example.net/
- `mitre-mapping.json`: 45 scenarios → 21 ATT&CK techniques
- `sync-attack-navigator.sh`: 12h cron auto-syncs layer
- `export-attack-navigator.py`: generates Navigator layer JSON

## Industry Audit (2026-03-30)
- Overall: **A-** (was B+, all 18 sub-categories below B lifted to B+)
- Compliance mapping: `docs/compliance-mapping.md` (22 CIS v8 + 19 NIST CSF)
- SLAs: Critical 24h, High 7d, Medium 30d, Low 90d
- 21/21 agentic patterns at A/A+
- Golden tests: 67/67
- Prometheus: 12+ security metrics
- Report: `docs/chatsecops-industry-audit.md`

## Cron Jobs (security-specific)
- `*/5 * * * *` write-security-metrics.sh
- `0 */6 * * *` crowdsec-learn.sh
- `0 8 * * 1` baseline-review.sh
- `0 */12 * * *` sync-attack-navigator.sh

## chatsecops-industry-audit.md

# ChatSecOps — Industry Standards Compliance Audit

**Date:** 2026-03-30
**Scope:** Full ChatSecOps pipeline vs. 12 industry standard categories
**Methodology:** Compared against NIST CSF 2.0, SOAR platforms (XSOAR, Splunk SOAR, QRadar), MITRE ATT&CK, CIS Controls v8, commercial AI SOC platforms (Microsoft Copilot, CrowdStrike Charlotte AI, SentinelOne Purple AI), and production vulnerability management tools (Rapid7, Qualys, Nessus).

**Scoring:** A+ (exemplary) | A (strong) | B (adequate) | C 
