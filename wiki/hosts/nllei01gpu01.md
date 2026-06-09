# nl-gpu01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-gpu01 | GPU node (Ollama, RTX 3090 Ti) | `ssh nl-gpu01` |

**nl:native/servarr/CLAUDE.md**
- Media acquisition, management, and streaming services. Consolidated from 16 individual LXCs into a single Docker Compose stack on nlservarr01 (IFRNLLEI01PRD-202). GPU-accelerated services (Plex, Jellyfin, xxxfin, Jellyswarrm) remain on nl-gpu01.
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

**gateway:CLAUDE.md**
- - **Rerank service (bge-reranker-v2-m3 at nl-gpu01:11436)** — [`docs/runbooks/rerank-service.md`](docs/runbooks/rerank-service.md). Rollback via `RERANK_BACKEND=ollama` env, container restart, model cache rebuild. Prometheus alert: `RAGRerankServiceDown`.

**other:/app/n8n/social-media-autoposter/CLAUDE.md**
- - **Ollama** — local LLM (`qwen2.5:7b`) at nl-gpu01:11434
- - 2026-05-04 — switched from `gemma3:12b` → `qwen2.5:7b`. Cause: chronic kernel OOM-killing of model-loader workers on `nl-gpu01` during cold-load. The 7B Q4 model needs ~5 GB host RSS (vs ~9 GB for the 12B), which fits inside the host's available headroom even when other ML services are co-resident. Side-note: qwen2.5 sometimes returns 2 hashtags instead of 3 — tighten the prompt ("append exactly 3 hashtags") if strict 3-tag is required.

## Related Memory Entries

- **Ollama runs in Docker on nl-gpu01** (feedback): Ollama CLI is not on $PATH on nl-gpu01 — it runs as a Docker container under /srv/ollama. Use `docker exec` for ollama CLI operations.
- **Ollama "model failed to load" — check host RAM + OOM-killer FIRST, not GPU VRAM** (feedback): When Ollama returns "model failed to load, this may be due to resource limitations", the cause is most often host RAM + OOM-killer killing the model-loader worker mid-load — NOT GPU VRAM. Check `dmesg`/`journalctl` for "Out of memory: Killed process … (ollama)" before nvidia-smi.
- **Always set per-request num_ctx when using Ollama on gpu01** (feedback): OLLAMA_CONTEXT_LENGTH=65536 global on nl-gpu01 forces huge KV cache for every model, causing tiny models (1B-7B) to spill to CPU. Always pass num_ctx in per-request options.
- **haha_voice_pe_upgrade** (project): HA Voice PE firmware — v7 working (v6 upstream + Squeezebox routing), Ollama q4_0 fix, REST sensors FIXED, 2026-03-16 audit fixes
- **knowledge_injection** (project): Knowledge injection into triage pipelines. 51 CLAUDE.md + 200+ memories + compiled wiki (45 articles) surfaced at both tiers via 3-signal RRF. Repo sync cron on openclaw01.
- **OpenClaw → Ollama local triage (2026-04-29)** (project): Wired OpenClaw 4.26 to use local Ollama with qwen2.5:7b after failing to make the claude-cli OAuth path work post Anthropic April-4 OpenClaw policy. Working at ~3 min/call latency, $0 cost. Hardware caps model size at 7-12B on this GPU.
- **nl-pve03 capacity pressure (2026-04-22)** (project): nl-pve03 mirrors pre-remediation pve01 pattern — no swap/zram, sustained 92%+ memory, hosts K8s ctrlr+NMS+GPU inference. Apply same zram fix; OOM blast radius is the K8s control-plane share + LibreNMS + Ollama inference simultaneously.
- **rag_circuit_breakers** (project): IFRNLLEI01PRD-631 shipped 2026-04-19. 4 named breakers guard RAG external calls (rerank service, Ollama embed, Anthropic Haiku synth, Ollama qwen synth). SQLite-backed state shared across processes; Prometheus gauges + CircuitBreakerOpen alert.
- **Cross-encoder rerank service on nl-gpu01** (project): BAAI/bge-reranker-v2-m3 via sentence-transformers as dedicated microservice at nl-gpu01:11436. Replaces Ollama yes/no hack.

*Compiled: 2026-05-06 00:48 UTC*