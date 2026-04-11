# nlk8s-ctrl01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:pve/CLAUDE.md**
- | nlk8s-ctrl01-03 | 1011006xx | QEMU | pve01+03 | 4C/8G | K8s control plane |

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-03-25 | KubePodCrashLooping | apiserver-ctrl01 crash looping (498 restarts) is a symptom  | Self-recovered when pve01 load dropped. All 3 apiservers Run | 0.9 |

## Related Memory Entries

- **alert_pipeline_v2_2026_03_18** (project): Major alert pipeline upgrade (2026-03-18): flap detection, issue dedup, confidence scoring, error propagation, CI/CD review, retry loops, few-shot prompts, context summarization
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **K8s Next Session Tasks** (project): Two pending tasks for K8s operational readiness — OpenClaw K8s access + Prometheus/Alertmanager/Gatus alert wiring

*Compiled: 2026-04-09 06:19 UTC*