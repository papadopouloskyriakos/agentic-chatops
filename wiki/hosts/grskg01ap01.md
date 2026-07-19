# grap01

**Site:** GR (Skagkia)

## Knowledge Base References

**gr:CLAUDE.md**
- gr   skg01  ap    01     → grap01 (access point)

**gr:network/CLAUDE.md**
- | grap01 | Access-Point | — | cisco_ios | Wireless AP |
- │   ├── Access-Point/{grap01,grap02,gr2ap01,gr2ap02}

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-26 | Device Down! Due to no ICMP response. | recurred 4x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **grskg_mass_flap_20260511** (project): "GR site mass flap 02:08-02:14 UTC 2026-05-11 — 16 devices ICMP-down. RC CONFIRMED: gr-nms01 chronically over-budget poll cycles (518s vs 300s) + IO starvation (PSI io.full avg300=7.32%) + 6 concurrent zombie poller-wrapper.py + cororings device 9 pushed past cliff by nlpve04 6th-node add 2026-05-10."

*Compiled: 2026-07-03 04:30 UTC*