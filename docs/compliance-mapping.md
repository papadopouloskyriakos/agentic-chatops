# Compliance Control Mapping

**Date:** 2026-03-30
**Scope:** ChatSecOps platform controls mapped to CIS Controls v8 and NIST CSF 2.0

---

## CIS Controls v8 Mapping

| CIS Control | Safeguard | Our Implementation | Status |
|---|---|---|---|
| **1.1** Enterprise Asset Inventory | Maintain accurate inventory | NetBox CMDB: 113 devices, 197 VMs, 421 IPs, 6 sites | Implemented |
| **1.2** Address Unauthorized Assets | Detect rogue assets | Daily scanner port diff detects new services on public IPs | Implemented |
| **2.1** Software Inventory | Maintain software list | Scanner `nmap -sV` identifies services; nuclei detects technologies | Partial |
| **3.1** Data Protection | Establish data management | Credential scanning (10 regex patterns), exec blocklist, safe-exec.sh | Implemented |
| **4.1** Secure Configuration | Establish secure config | OpenTofu IaC, CrowdSec bouncer config, iptables persistence | Implemented |
| **4.7** Manage Default Accounts | Change defaults | ASA admin credentials documented, SSH key auth where possible | Implemented |
| **5.1** Account Inventory | Maintain account list | AUTHORIZED_SENDERS filter, NetBox device ownership | Partial |
| **7.1** Vulnerability Scanning | Automated scanning schedule | 2 scanner VMs, daily crons (03:00/03:15 UTC), 24 tools | Implemented |
| **7.2** Remediation Process | Establish remediation timeline | SLA definitions: Critical 24h, High 7d, Medium 30d, Low 90d | Implemented |
| **7.4** Vuln Exception Process | Formal exception workflow | MSC3381 baseline polls, baseline-add.sh, 90-day expiry, weekly review | Implemented |
| **7.5** Internal Vuln Scanning | Authenticated internal scans | External-only scanning via cross-site VPN. No internal auth scans. | Gap |
| **8.2** Collect Audit Logs | Centralized log collection | syslog-ng per host, triage.log, session_log, a2a_task_log | Implemented |
| **8.5** Access Log Collection | Log access attempts | CrowdSec alerts (SSH-BF, HTTP-BF), syslog-ng SSH logs | Implemented |
| **8.11** Log Retention | Retain logs per policy | syslog-ng retains by date/host. No formal retention policy. | Partial |
| **9.1** Web Application Firewalls | Deploy WAF | CrowdSec HTTP scenarios act as behavioral WAF on 6 hosts | Implemented |
| **10.1** Malware Defenses | Deploy anti-malware | CrowdSec detects malware distribution patterns. No EDR. | Partial |
| **12.1** Network Infrastructure | Secure management | ASA ACLs, VPN-only management access, scanner ACL awareness | Implemented |
| **13.1** IDS/IPS | Deploy intrusion detection | CrowdSec IPS (6 hosts, 38+ scenarios), LibreNMS SNMP alerting | Implemented |
| **13.3** Network Monitoring | Automated alerting | Prometheus + LibreNMS + CrowdSec + security scanners | Implemented |
| **13.6** IOC Collection | Collect threat indicators | CrowdSec CAPI blocklist, CTI API, GreyNoise, AbuseIPDB | Implemented |
| **16.1** Vulnerability Response | Structured response process | security-triage.sh (10 steps), 3-tier escalation, YT issue lifecycle | Implemented |
| **16.11** IR Lessons Learned | Capture post-incident learnings | Session End auto-populates incident_knowledge + lessons_learned | Implemented |
| **17.3** Security Awareness | Train personnel | SOUL.md instructions, scenario-aware routing, feedback memory | Partial (AI-trained, not human) |

---

## NIST CSF 2.0 Mapping

| NIST Function | Category | Our Implementation | CIS Control |
|---|---|---|---|
| **GV.OC** Organizational Context | Risk governance | AUTHORIZED_SENDERS, exec blocklist, READ-ONLY constraints | -- |
| **GV.RM** Risk Management | Risk strategy | SLA definitions, severity-based prioritization, baseline exceptions | -- |
| **ID.AM-1** Asset Inventory | Hardware inventory | NetBox CMDB (310 objects) | CIS 1.1 |
| **ID.AM-2** Software Inventory | Software inventory | Scanner service detection (nmap -sV) | CIS 2.1 |
| **ID.RA-1** Risk Assessment | Vulnerability identification | Daily scans, EPSS scoring, CVSS from nuclei | CIS 7.1 |
| **ID.RA-2** Threat Intelligence | Receive TI from sharing groups | CrowdSec CAPI (25M IPs community), GreyNoise, AbuseIPDB | CIS 13.6 |
| **PR.AC-1** Access Control | Identities/credentials managed | SSH key auth, ASA password auth, AUTHORIZED_SENDERS | CIS 4.7 |
| **PR.DS-1** Data Protection | Data at rest protected | Credential scanning prevents token leakage | CIS 3.1 |
| **PR.IP-1** Config Management | Baseline configs maintained | OpenTofu IaC, iptables-persistent, CrowdSec CAPI | CIS 4.1 |
| **DE.AE-1** Anomaly Detection | Baseline of operations established | Scanner baselines (ports, nuclei, TLS), CrowdSec scenario baselines | CIS 13.1 |
| **DE.AE-3** Event Correlation | Events correlated | Cross-host burst detection, multi-source TI correlation, flap detection | CIS 13.3 |
| **DE.CM-1** Network Monitoring | Network monitored | CrowdSec IPS, LibreNMS SNMP, Prometheus alerts | CIS 13.3 |
| **DE.CM-4** Malicious Code Detection | Malware detected | CrowdSec backdoor/exploit scenarios, nuclei CVE scanning | CIS 10.1 |
| **DE.CM-8** Vulnerability Scanning | Scans performed | Daily crons, 2 VMs, 24 tools, cross-site design | CIS 7.1 |
| **RS.AN-1** Investigation | Notifications investigated | security-triage.sh 10-step pipeline, 3-tier escalation | CIS 16.1 |
| **RS.MI-1** Incident Containment | Incidents contained | CrowdSec auto-ban, approval-gated remediation | CIS 16.1 |
| **RS.MI-2** Incident Mitigation | Incidents mitigated | YT issue lifecycle, SLA tracking, baseline management | CIS 7.2 |
| **RS.IM-1** Response Improvement | Lessons incorporated | Session End auto-populates KB, lessons pipeline, regression detection | CIS 16.11 |
| **RC.IM-1** Recovery Improvement | Recovery plans improved | incident_knowledge informs future triage, weekly lessons digest | CIS 16.11 |

---

## Architectural Decisions (documented justifications)

| Topic | Decision | Rationale |
|---|---|---|
| **STIX/TAXII** | Not implemented | Single operator, no CTI sharing partners. IOC data consumed via REST APIs. |
| **EDR** | Not deployed | 310 devices across 6 sites managed by solo operator. CrowdSec IPS + scanner coverage sufficient for infrastructure (not endpoint) focus. |
| **SIEM** | Prometheus + syslog-ng (not ELK/Splunk) | Resource-appropriate for scale. Prometheus for metrics, syslog-ng for log aggregation. |
| **Per-incident war rooms** | Per-project Matrix rooms | Solo operator — per-incident channels would be overhead with no collaboration benefit. |
| **Internal vulnerability scanning** | External-only (cross-site VPN) | Scanners traverse VPN to simulate external attack path. Internal auth scanning would require credential management at scale. |
