# Example Corp Knowledge Base

> Auto-compiled wiki from 7+ knowledge sources. Last compiled: 2026-04-09 06:19 UTC.
> 44 articles across 8 categories.

## How This Works

This wiki is **compiled by `scripts/wiki-compile.py`** from:
- 70+ memory files (operational feedback, project knowledge)
- 55 CLAUDE.md files across 6 repos (per-host, per-service documentation)
- SQLite tables: incident_knowledge, lessons_learned, openclaw_memory
- docs/ directory (architecture, postmortems, audits)
- 15 OpenClaw skill scripts
- 5 Grafana dashboards
- 03_Lab reference library (~5,200 files manifest)

**Do not edit wiki files directly** — they are overwritten on each compilation.
Edit the source files instead.

## Operations & Runbooks

- [Data Trust Hierarchy](operations/data-trust-hierarchy.md)
- [Emergency Procedures](operations/emergency-procedures.md)
- [Operational Rules](operations/operational-rules.md)
- [Runbooks](operations/runbooks.md)

## Host Pages

- [Grskg01Fw01](hosts/gr-fw01.md)
- [Grskg01Pve01](hosts/gr-pve01.md)
- [Grskg01Pve02](hosts/gr-pve02.md)
- [Grskg02Cam01](hosts/gr2cam01.md)
- [Grskg02Sw01](hosts/gr2sw01.md)
- [My Awx Web](hosts/my-awx-web.md)
- [Nllei01Cl01Iot01](hosts/nlcl01iot01.md)
- [Nllei01Cl01Iot02](hosts/nl-iot02.md)
- [Nllei01Claude01](hosts/nl-claude01.md)
- [Nllei01Fw01](hosts/nl-fw01.md)
- [Nllei01Gpu01](hosts/nl-gpu01.md)
- [Nllei01Hpb01](hosts/nlhpb01.md)
- [Nllei01K8S Ctrlr01](hosts/nlk8s-ctrl01.md)
- [Nllei01Librespeed01](hosts/nl-librespeed01.md)
- [Nllei01Mealie01](hosts/nlmealie01.md)
- [Nllei01Myspeed01](hosts/nlmyspeed01.md)
- [Nllei01Nc02](hosts/nlnc02.md)
- [Nllei01Netvisor01](hosts/nlnetvisor01.md)
- [Nllei01Openclaw01](hosts/nl-openclaw01.md)
- [Nllei01Protonmail Bridge01](hosts/nlprotonmail-bridge01.md)
- [Nllei01Pve01](hosts/nl-pve01.md)
- [Nllei01Pve02](hosts/nl-pve02.md)
- [Nllei01Pve03](hosts/nl-pve03.md)
- [Nllei01Sw01](hosts/nl-sw01.md)
- [Nllei01Syno01](hosts/nl-nas01.md)
- [Prometheus Monitoring Kube Prometheus Prometheus 0](hosts/prometheus-monitoring-kube-prometheus-prometheus-0.md)

## Incidents

- [Index](incidents/index.md)

## Network Topology

- [Gr Site](topology/gr-site.md)
- [K8S Clusters](topology/k8s-clusters.md)
- [Nl Site](topology/nl-site.md)
- [Vpn Mesh](topology/vpn-mesh.md)

## Services & Architecture

- [Chatops Platform](services/chatops-platform.md)
- [Openclaw](services/openclaw.md)
- [Rag Pipeline](services/rag-pipeline.md)
- [Seaweedfs](services/seaweedfs.md)
- [Security Ops](services/security-ops.md)

## Decisions

- [Index](decisions/index.md)

## Physical Lab

- [Index](lab/index.md)

## Health & Coverage

- [Coverage Matrix](health/coverage-matrix.md)
- [Staleness Report](health/staleness-report.md)
