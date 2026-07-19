# grpikvm01

**Site:** GR (Skagkia)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-07-02 | Device Down! Due to no ICMP response. | recurred 4x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **NEVER modify OOB/lifeline systems without explicit approval** (feedback): Critical lesson — PiKVM was bricked by package upgrades. OOB systems must be treated as untouchable.
- **feedback-yt-duplicate-close-auto-propagates** (feedback): "When closing a YouTrack issue with a \"duplicate of X\" comment that explicitly names X, YT workflow rules can auto-propagate the Done state to X (the parent). After any mass-close that involves duplicate-naming, re-verify the state of every parent issue you intended to keep open."
- **grskg_mass_flap_20260511** (project): "GR site mass flap 02:08-02:14 UTC 2026-05-11 — 16 devices ICMP-down. RC CONFIRMED: gr-nms01 chronically over-budget poll cycles (518s vs 300s) + IO starvation (PSI io.full avg300=7.32%) + 6 concurrent zombie poller-wrapper.py + cororings device 9 pushed past cliff by nlpve04 6th-node add 2026-05-10."
- **OOB Access via PiKVM + Cloudflare Tunnel** (project): BROKEN (2026-03-21) — PiKVM bricked by forced package upgrade. Requires physical access to GR site to recover. Cloudflare tunnel config still exists but PiKVM is offline.
- **PiKVM and LTE Gateway Audit** (project): Audit of grpikvm01 (PiKVM v3) and grlte01 (Cisco C819G LTE) — config, findings, OOB architecture rationale
- **session-thermal-and-gr-unreachable-20260616** (project): "2026-06-16 triage — NL \"thermal\" was stale phantom data; GR site was isolated ~06-15 22:58 → RECOVERED by 2026-06-17 (GR back online, reachable from NL)"
- **youtrack_infra_board_triage_20260627** (project): 2026-06-27 triage of open NL/GR infra YouTrack issues. NL=31 open (17 work / 14 alert-generated), GR=4 (1 work / 3 alert). Systemic gap = alert→YT issues auto-CREATE but never auto-CLOSE → noise accrues. 2 genuinely-real items: NL-1333 (pve01 rpool DEGRADED) + GR-85 (bricked PiKVM). ~9 done-this-session items still open.

*Compiled: 2026-07-03 04:30 UTC*