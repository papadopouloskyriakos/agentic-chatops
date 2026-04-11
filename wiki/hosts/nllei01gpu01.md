# nl-gpu01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-gpu01 | GPU node (Ollama, RTX 3090 Ti) | `ssh nl-gpu01` |

**nl:native/servarr/CLAUDE.md**
- Media acquisition, management, and streaming services. Consolidated from 16 individual LXCs into a single Docker Compose stack on nlservarr01 (IFRNLLEI01PRD-202). GPU-accelerated services (Plex, Jellyfin, xxxfin, Jellyswarrm) remain on nl-gpu01. Quality profiles managed by Profilarr (Dictionarry/TRaSH Guides).
- nlservarr01 (10.0.181.X)         nl-gpu01
- ### Media Servers on nl-gpu01 (unchanged)
- ssh -i ~/.ssh/one_key root@nl-gpu01         # GPU host (Jellyfin, xxxfin, Plex)
- All servarr services are now on nlservarr01 (10.0.181.X). GPU services remain on nl-gpu01. All services are also proxied via NPM at `https://<service>.example.net`.

**nl:native/ncha/CLAUDE.md**
- | nl-gpu01 | VM | pve03 | 10.0.181.X | AI backends (Docker) | 5000 (facerecog), 24002 (chat), 24003 (LLM), 24004 (text2image) |

**nl:native/haha/CLAUDE.md**
- ssh -i ~/.ssh/one_key root@nl-gpu01 "

**nl:docker/CLAUDE.md**
- | nl-gpu01 | 21 services | GPU compute cluster (Ollama, Stable Diffusion, Immich ML, Whisper, Piper, Milvus, etc.) |
- ### GPU Services (nl-gpu01)
- - Do not add new services to `nl-gpu01` without checking GPU memory availability — 21 services share the GPU

**nl:docker/nl-gpu01/ollama/CLAUDE.md**
- Both containers run `network_mode: host` on `nl-gpu01`. Ollama state persists at `/srv/ollama/ollama_state`; the shim is stateless.
- Standard `ci/docker.yml` pipeline: push to `main`, CI rsyncs this directory to `/srv/ollama/` on `nl-gpu01`, runs `docker compose up -d`. The shim script is bind-mounted into a `python:3.12-slim` container, so a script edit + push + pipeline is the whole update flow (no image rebuild).

## Related Memory Entries

- **haha_voice_pe_upgrade** (project): HA Voice PE firmware — v7 working (v6 upstream + Squeezebox routing), Ollama q4_0 fix, REST sensors FIXED, 2026-03-16 audit fixes
- **knowledge_injection** (project): CLAUDE.md + memory knowledge injection into triage pipelines. 51 CLAUDE.md files + 200+ feedback memories now surfaced at both tiers. Repo sync cron on openclaw01.

*Compiled: 2026-04-09 06:19 UTC*