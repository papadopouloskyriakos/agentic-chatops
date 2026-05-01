# NL (Leiden) Site Topology

> Compiled from 26 CLAUDE.md files + 1 memory files. 2026-04-11 14:13 UTC.

## CLAUDE.md Files

### CLAUDE.md

# Example Corp Infrastructure — Claude Code Instructions
## Repository Purpose
Single source of truth for the Example Corp homelab infrastructure across 4 countries (NL, GR, CH, NO). Everything is deployed via GitLab CI/CD pipelines — never make changes directly on servers.
- **GitLab instance**: `https://gitlab.example.net/` (NL site — primary GitLab instance)
- **Repo path**: `infrastructure/nl/production`

### k8s/CLAUDE.md

# Kubernetes Infrastructure — Claude Code Instructions
## Architecture
- **Cluster**: `nlcl01k8s` (ID: 1), K8s v1.34.2, API at `api-k8s.example.net:6443`
- **Nodes**: 3 control-plane (4 CPU, 8GB — ctrl02 4GB on pve02, ctrl01+ctrl03 upgraded 4→8GB on 2026-03-15) + 4 workers (8 CPU, 8GB), all Ubuntu 24.04, IPs 10.0.X.X-12 (CP), .20-23 (workers)
- **CNI**: Cilium v1.18.4, eBPF, kubeProxyReplacement, VXLAN tunneling, MTU 1350

### network/CLAUDE.md

# Network Infrastructure — Claude Code Instructions
## Device Inventory
| Device | Model | OS | IP | Role | Deploy Method |
|--------|-------|----|----|------|---------------|
| nl-fw01 | ASA 5508-X | ASA 9.16(4) | 10.0.181.X | Core firewall, NAT, VPN, BGP | Netmiko (ASA prompts incompatible with NAPALM) |

### ci/CLAUDE.md

# CI/CD Pipeline — Claude Code Instructions
## Architecture
Main pipeline (`.gitlab-ci.yml`) defines 5 stages and includes 8 modular files:
```
drift-detection → validate → pre-deploy → deploy → verify

### edge/CLAUDE.md

# Edge Infrastructure — BGP, IPsec, DMZ & Public Services
## Overview
The edge layer handles all public-facing traffic for Example Corp. It forms a geographically distributed anycast network: external VPS nodes terminate BGP and TLS, then forward traffic over IPsec tunnels to DMZ Docker hosts at each site. Internal FRR route reflectors distribute routes between all participants.
**AS Number:** AS64512
**IPv6 prefix:** `2a0c:9a40:8e20::/48` (announced from both VPS nodes). Per-domain anycast `/128`s carved out of the prefix: `::1` (papadopoulos.tech, matrix, mattermost), `::2`/`::3` (reserved for future papadopoulos.tech multi-homing), `::4` (mulecube), `::5` (cubeos.app), `::6` (withelli), `::7` (meshsat.net), `::8` (meshsat.org). Next free: `::9`. When allocating a new slot, add it to both VPS netplans (reboot to apply — never `netplan apply` on the VPS), add matching `bind [::N]:80` and `bind [::N]:443` lines in `frontend http_redirect` and `frontend tls_in` on both VPS's haproxy.cfg, then add the Cloudflare AAAA record for the service.

### images/CLAUDE.md

# CI Runner Images — Claude Code Instructions
## Purpose
Build contexts for CI runner images used by GitLab pipelines. These are **build-only** — they get pushed to the private registry, not deployed as running services. Never place these under `docker/` (that directory triggers the deployment pipeline).
## Registry
All images push to: `registry.example.net/infrastructure/nl/production/<name>:<tag>`

### native/CLAUDE.md

# Native Services — Non-Docker Installations
Services installed directly on VMs (not containerized with Docker). This directory tracks their configuration files as **read-only snapshots** for reference, drift detection, and disaster recovery.
## Directory Convention
```
native/<project>/

### native/fcksns/CLAUDE.md

# FCKSNS — Open-Source Speaker Fleet (openSYMF)
Open-source conversion of IKEA SYMFONISK and Sonos speakers to Raspberry Pi-based audio players, escaping Sonos vendor lock-in while keeping original hardware (power supplies, speaker drivers, buttons, LEDs).
## Architecture
```
                    +-----------------------+

### native/librenms/CLAUDE.md

# LibreNMS — Network Monitoring System
Two LibreNMS instances monitoring the Example Corp infrastructure across NL and GR sites.
## Hosts
| Host | Site | URL | PVE Host | VMID | IP | Role |
|------|------|-----|----------|------|----|------|

### native/synology/CLAUDE.md

# Synology NAS Fleet — nl-nas01 / nl-nas02
## Audit Report (2026-03-17)
### Fleet Overview
| Property | nl-nas01 (Primary) | nl-nas02 (Secondary) |
|----------|------------------------|--------------------------|

### native/pve/CLAUDE.md

# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
## Scope
Hypervisor-level (PVE host OS) config snapshots for all 5 Proxmox nodes. Initial snapshot taken 2026-04-06.
### Per-Host Contents

### native/servarr/CLAUDE.md

# SERVARR — Media Stack
Media acquisition, management, and streaming services. Consolidated from 16 individual LXCs into a single Docker Compose stack on nlservarr01 (IFRNLLEI01PRD-202). GPU-accelerated services (Plex, Jellyfin, xxxfin, Jellyswarrm) remain on nl-gpu01.
## Planned: K8s Migration (2026-04-06)
**Status:** Planned — Docker Compose on servarr01 is current production.
**Motivation:** Operational consistency — one deployment model (K8s/OpenTofu/Argo CD) instead of three. Not for resource savings (VM uses 2.5 GB actual, K8s adds per-pod overhead).

### native/fisha/CLAUDE.md

# FISHA — File Server High Availability
3-node DRBD + OCFS2 + Pacemaker storage cluster providing shared NFS for NCHA (Nextcloud HA) and HAHA (Home Assistant HA) projects.
## Hosts
| Host | VMID | PVE Host | Type | IP (VLAN 10) | IP (VLAN 88) | Role | CPU | RAM |
|------|------|----------|------|--------------|--------------|------|-----|-----|

### native/habitica/nlhabitica01/CLAUDE.md

# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
# Habitica — Self-Hosted Habit Tracking RPG
Self-hosted instance of [Habitica](https://habitica.com), an open-source gamified task manager. Runs as a full-stack Node.js application on a Proxmox LXC container, with a custom-built Android app pointing at the self-hosted server.
## Architecture

### native/openvpnas/CLAUDE.md

# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
# OpenVPN Access Server (OAS) — Remote Access VPN
6 OpenVPN Access Server v3.1.0 instances across 2 sites (NL + GR), providing remote access VPN for family/friends. Each site has 3 instances on different ports/protocols for maximum reachability across restrictive networks.
## Host Inventory

### native/syncthing/CLAUDE.md

# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
## What This Directory Is
Read-only config snapshots for the Syncthing file synchronization infrastructure. No deploy pipeline — changes are made on servers and snapshotted back here. See `native/CLAUDE.md` for the general native service conventions.
## Architecture

### native/ncha/CLAUDE.md

# Nextcloud HA Cluster (NCHA) — Complete Architecture
## Traffic Flow
```
INTERNET
    │

### native/haha/CLAUDE.md

# Home Assistant HA (HAHA) — Complete Architecture
## Overview
Fault-tolerant smart home automation cluster. Active/standby Pacemaker cluster with STONITH fencing. All services run as Pacemaker-managed Docker containers on the active node, with automatic failover to the standby. Shares the DRBD+OCFS2+NFS storage backend with the Nextcloud cluster (file01/file02).
Project page: https://kyriakos.papadopoulos.tech/projects/home-assistant-ha/
## Traffic Flow

### docker/CLAUDE.md

# Docker Services — Claude Code Instructions
## Deployment Model
- **Path convention**: `docker/<hostname>/<service>/docker-compose.yml` → deploys to `/srv/<service>/` on `<hostname>` via rsync + SSH
- **Pipeline**: Push to main triggers `ci/docker.yml` — rsync files, then `docker compose pull && docker compose up -d --remove-orphans`
- **Dockerfile changes**: Trigger `docker compose build --no-cache` instead of pull

### docker/nl-gpu01/ollama/CLAUDE.md

# Ollama — local LLM serving + Anthropic-compat shim
Ollama LLM server plus a small Python sidecar (`anthropic-shim`) that patches Claude Code's requests into a form Ollama's `gpt-oss:20b` chat template can handle. Primary consumer: Elli on her laptop (`fouska`, 10.0.181.X), running Claude Code against a local model for her `withelli.com` blog work.
## Architecture
```
Elli's laptop (fouska)  ──►  anthropic-shim :11435  ──►  ollama :11434

### docker/nlfrigate01/frigate/CLAUDE.md

# Frigate NVR Infrastructure
## Project Overview
This project manages **Frigate NVR**, a self-hosted network video recorder with AI object detection, running on a dedicated Proxmox LXC. Frigate processes 8 RTSP camera feeds across two locations (Netherlands and Greece), performing real-time object detection via Google Coral USB EdgeTPU, with recordings stored on a Synology NAS via NFS.
**Primary Goal**: Reliable 24/7 video surveillance with AI-powered detection of 20 object classes including person, car, animals, and security-relevant items (knife, baseball bat).
## Server Access

### docker/nlservarr01/servarr/pinchflat/CLAUDE.md

# Pinchflat Self-Healing Infrastructure
## Session Protocol
**On session start**: Read `PROJECT_STATE.md` to understand current system status, recent changes, and known issues before doing any work.
**Before session end / on user request**: Offer to update `PROJECT_STATE.md` with:
- Any changes made during the session

### docker/nl-matrix01/matrix/CLAUDE.md

# CLAUDE.md — Matrix Stack (nl-matrix01)
## Session Protocol
**At the start of every session**, read `PROJECT_STATE.md` to understand current state.
**At the end of every session** (or when significant changes are made), update:
1. `PROJECT_STATE.md` — reflect current state, recent changes, open issues

### docker/nlprotonmail-bridge01/protonmail-bridge/CLAUDE.md

# Protonmail Bridge — Claude Code Instructions
## Overview
Protonmail Bridge exposes a Proton Mail account as local IMAP/SMTP, allowing standard mail clients to connect. Runs on `nlprotonmail-bridge01` (10.0.181.X), a Debian 12 LXC container (VMID 201101201, pve01).
## Architecture
Two Docker containers plus a native Postfix MTA:

### docker/nlmattermost01/mattermost/CLAUDE.md

# CLAUDE.md — Mattermost Stack (nlmattermost01)
## Project Overview
Self-hosted **Mattermost Enterprise Edition** for `mattermost.example.net`, running on host `nlmattermost01` (LXC VMID_REDACTED on nl-pve01) at `/srv/mattermost/`. Deployed from this git directory via the standard Docker CI pipeline.
## Architecture
```

### pve/CLAUDE.md

# Proxmox VE Infrastructure — Claude Code Instructions
## Hosts
| Host | Hardware | CPU | RAM | Storage | LXC | QEMU |
|------|----------|-----|-----|---------|-----|------|
| nl-pve01 | Venus Series Mini PC | i9-12900H (20T) | 96 GB | NVMe ZFS | 75 | 8 |
