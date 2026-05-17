# GR (Skagkia) Site Topology

> Compiled from 7 CLAUDE.md files + 46 memory files. 2026-05-06 00:48 UTC.

## CLAUDE.md Files

### CLAUDE.md

# CLAUDE.md - GR Site (gr) Production Infrastructure
## Repository Overview
This is the **production infrastructure-as-code repository** for the Greece (GR) Kubernetes cluster site (`gr`), part of a **two-site active-active architecture** with the Netherlands (NL) site (`nl`). Everything is managed via **OpenTofu + Atlantis** (infrastructure) and **Argo CD** (applications), with secrets in **OpenBao** via External Secrets Operator.
- **GitLab instance**: `https://gr-gitlab.example.net/` (GR site — separate instance from NL)
- **NL GitLab instance**: `https://gitlab.example.net/` (primary GitLab, hosts the NL site's repo)

### ci/CLAUDE.md

# CI/CD Pipeline — Claude Code Instructions
## Architecture
Main pipeline (`.gitlab-ci.yml`) defines 4 stages and includes 3 modular files:
```
drift-detection → validate → deploy → verify

### k8s/CLAUDE.md

# Kubernetes Infrastructure — Claude Code Instructions
## Architecture
- **Cluster**: `grcl01k8s` (ID: 2), API at `gr-api-k8s.example.net:6443`
- **Nodes**: 3 workers, IPs 10.0.58.X, .58.21, .58.22
- **CNI**: Cilium v1.18.4, eBPF, kubeProxyReplacement, VXLAN tunneling

### docker/CLAUDE.md

# Docker Services — Claude Code Instructions
## Deployment Model
- **Path convention**: `docker/<hostname>/<service>/docker-compose.yml` → deploys to `/srv/<service>/` on `<hostname>` via rsync + SSH
- **Pipeline**: Push to main triggers `ci/docker.yml` — rsync files, then `docker compose pull && docker compose up -d --remove-orphans`
- **Dockerfile changes**: Trigger `docker compose build --no-cache` instead of pull

### pve/CLAUDE.md

# Proxmox VE Infrastructure — Claude Code Instructions
## Hosts
| Host | Hardware | Purpose |
|------|----------|---------|
| gr-pve01 | TBD | Primary Proxmox host — K8s nodes, DMZ, FRR |

### network/CLAUDE.md

# Network Infrastructure — Claude Code Instructions
## Overview
GR has a **drift-sync CI pipeline** (`*/30 * * * *` schedule, `auto_detect_and_sync_drift` in `ci/cisco.yml`) landed via IFRNLLEI01PRD-700 + remediation MRs !63/!64/!65/!67 (2026-04-22 → 2026-04-24). Captures device drift via netmiko direct-SSH and auto-commits to `main` as `GitLab CI Auto-Sync`. Live device = source of truth (see `feedback_data_trust_hierarchy`); git tracks reality, it does not drive deployment.
**Not a deployment pipeline.** Unlike NL, GR does **not** have NAPALM/hier_config/v2 push-side automation. Config changes on GR devices are still made manually via SSH; the pipeline only captures the result. Do not edit `network/oxidized/**` files by hand — they are overwritten on the next drift-sync cycle (~30 min).
## Device Inventory

### edge/CLAUDE.md

# Edge Infrastructure — Claude Code Instructions
## Overview
GR's edge infrastructure is a subset of the organization-wide edge network documented in NL's `edge/CLAUDE.md`. This file covers GR-specific edge components: the ASA firewall, DMZ Docker host, FRR route reflectors, and K8s BGP peering.
**Important:** This directory contains **read-only config snapshots** — not deployed by CI/CD. There is no automated deploy pipeline for GR edge services.
**To update:** SSH to the host, make changes, copy updated config back, commit with `chore(edge): sync <service> config from <host>`.
