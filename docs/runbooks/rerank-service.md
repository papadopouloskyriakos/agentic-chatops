# Runbook: Rerank Service Down

**Service**: bge-reranker-v2-m3 cross-encoder on `nl-gpu01:11436`
**Symptom**: Prometheus alert `RAGRerankServiceDown` firing; `kb_rerank_service_up == 0`
**Impact**: Retrieval still works via automatic Ollama yes/no fallback — quality degrades by ~15 points judge hit@5, but stays deterministic and functional. NOT a critical outage.

## Triage

1. **Check container status**
```bash
ssh -i ~/.ssh/one_key root@nl-gpu01 'docker ps --filter name=rerank --format "{{.Status}}"'
```

2. **Check logs**
```bash
ssh -i ~/.ssh/one_key root@nl-gpu01 'docker logs rerank --tail 50'
```

3. **Check health directly**
```bash
curl -sf --connect-timeout 5 http://nl-gpu01:11436/health && echo "ok" || echo "DOWN"
```

4. **Check GPU memory**
```bash
ssh -i ~/.ssh/one_key root@nl-gpu01 'nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader'
```
If VRAM is exhausted, the service can't load the model. Check `ollama ps` for memory hogs.

## Recovery

### A. Container restart (most common fix)
```bash
ssh -i ~/.ssh/one_key root@nl-gpu01 'cd /srv/rerank && docker compose restart rerank'
# Wait ~45s for model reload
sleep 45
curl -sf http://nl-gpu01:11436/health
```

### B. Full rebuild if model cache corrupted
```bash
ssh -i ~/.ssh/one_key root@nl-gpu01 'cd /srv/rerank && docker compose down && rm -rf hf_cache/models--BAAI* && docker compose up -d'
# First start re-downloads ~1.7 GB. Takes 2-3 min.
```

### C. Fallback to Ollama yes/no reranker (temporary)

If the service can't be restored quickly, switch callers to the fallback path:

```bash
# On nl-claude01, add to crontab env or relevant shell:
export RERANK_BACKEND=ollama
```

This routes through `rerank_candidates`'s Ollama qwen2.5:7b yes/no path. Works but:
- Loses ~15 points judge hit@5 quality
- Variance returns (±10% across runs)
- Latency +1-2s per query

Set `RERANK_BACKEND=crossencoder` (or unset) once the service is back up.

### D. Disable reranking entirely (worst case)

```bash
export RERANK_ENABLED=0
```

Retrieval returns raw RRF-fused top-K with no rerank. Expect ~20-25 point quality drop.

## Post-mortem

After recovery, check:
- Was it OOM? → `nvidia-smi --query-gpu=memory.used,memory.total` at failure time via Grafana history.
- Was it a model cache issue? → docker logs show "OSError loading model".
- Was it a shared-service collision with Ollama? → Check `docker stats rerank ollama` — the two share GPU.

File an incident at `incident_rerank_svc_YYYYMMDD.md` in memory if the root cause is non-trivial.

## Known failure modes

- **Cold start**: first request after restart takes 1.5-2s (JIT compile). Subsequent requests ~32ms warm.
- **GPU contention with Ollama**: at ~18GB+ combined VRAM usage, CUDA context allocation can fail. See `feedback_ollama_num_ctx_vram` — keeping `num_ctx` per-request low prevents this.
- **Model cache download**: first-time start from scratch needs ~1.7 GB download from HuggingFace. Offline = broken until restored.

## Related

- Service config: `/srv/rerank/app/server.py`, `/srv/rerank/docker-compose.yml` on nl-gpu01
- Reference memory: `memory/rerank_service_crossencoder.md`
- Metrics: `kb_rerank_service_up`, `kb_rerank_probe_latency_ms` (see `docs/rag-metrics-reference.md`)
- Client code: `scripts/kb-semantic-search.py:_rerank_via_crossencoder`

## Dynamic VRAM on nl-gpu01 (2026-08-26)

The RTX 3090 Ti (23,028 MiB) is shared by ~8 tenants. Until 2026-08-26 the two
PyTorch services hoarded their historical peak forever (rerank 4.3 GB for a
2.2 GB model, omoikane's `embed-bge-m3` 10.2 GB) and Ollama — the only tenant
that yields — was left ~2 GB, so every `/api/generate` (judge, RAG synth) failed
to load its model, thrashed the embed runner for ~22 s per attempt with
`OLLAMA_NUM_PARALLEL=1`, and finally wedged the Ollama scheduler (all generates
hang, embeds fine). RCA: `memory/gpu01_ollama_vram_starvation_judge_wedge_20260826.md`.

Both PyTorch services now run the same discipline (sources vendored in
`scripts/gpu01/`, deployed by hand to `/srv/<svc>/app/server.py`):

| Knob (env) | rerank `:11436` | embed-bge-m3 `:11437` | Effect |
|---|---|---|---|
| `EMPTY_CACHE_AFTER_REQUEST` | `true` | `true` | `torch.cuda.empty_cache()` after each request → resident ≈ weights + context (~2.2 GB fp32), peaks are transient |
| `IDLE_UNLOAD_SECONDS` | `900` | `1800` | model dropped from the GPU after idle (0 MB), lazily reloaded on next request (rerank ~1.5 s, bge-m3 ~2 s from cache); `0` disables |
| `MAX_DOCS` / `MAX_LENGTH_CAP` | 256 docs | 2048 tokens | bounds the per-request activation peak |
| `GET /stats` | ✓ | ✓ | `loaded`, `idle_seconds`, `vram_allocated_mb`, `vram_reserved_mb`, `requests/loads/unloads` |

`/health` (rerank) and `/healthz` (embed) stay 200 while the process is alive,
loaded or not — `kb_rerank_service_up` must not flap on idle-unload.

Ollama (`/srv/ollama/docker-compose.yml`) runs as **two planes** since
2026-08-26 (the 0.32.15 scheduler wedges when a generate that does not fit
tries to evict the embed runner, which never idles under the omoikane stream —
observed twice on 2026-08-26): **`ollama` :11434 = embed-only** (omoikane
notrf01dmz02/06, nltg01, defra01agri01, gateway embeds; never loads an
LLM, so it never has to evict) and **`ollama-gen` :11441 = gateway generates**
(judge, RAG synth/rewrite/json, teacher, extraction; evictions only ever hit
idle LLM runners). Gateway routing: `scripts/lib/rag_config.py` `OLLAMA_GEN_URL`
(env-overridable) + per-script defaults. Both planes: `OLLAMA_CONTEXT_LENGTH=4096`
(was 65536; a no-num_ctx gemma3:12b call is capped at ~7.7 GiB instead of 10.4+),
embed parallel 2 / gen parallel 1, `OLLAMA_MAX_LOADED_MODELS=3`, json-file
logging `100m × 5` (was 10m × 3 ≈ 3 h of history at llama-server's verbosity).
`write-ollama-gpu-metrics.py` polls both planes (`plane="embed"|"gen"` label +
`ollama_plane_up`); `ollama-nvml-selfheal.sh` heals both containers. Judge (`scripts/llm-judge.sh`): every
local curl has `--max-time`, batch runs take a flock and pre-flight the model
(primary → fallback → skip; jury only when both models co-reside), Cronicle
event `emqurqybr5j` has a 30-min timeout.

Budget after the change (nothing stopped): rerank 2.2 + embed 2.2 + whisper 2.1
+ tei-rerank 1.4 + agora 1.5 + sunshine 0.3 ≈ 9.7 GB resident, → the Ollama
planes share ~12 GB (embed plane: nomic ~0.65 GB; gen plane: gemma3:12b ~7.4 GB
or qwen2.5:7b ~4.7 GB, more once the PyTorch services idle-unload). Check: `curl nl-gpu01:11436/stats`,
`curl nl-gpu01:11437/stats`, `curl nl-gpu01:11434/api/ps`, `nvidia-smi`.

Rollback (per service): `server.py.pre-dynamic-20260826-1414` next to each
`server.py` → copy back + `docker compose restart`; Ollama:
`docker-compose.yml.pre-vram-20260826-1414` → `docker compose up -d ollama`;
selfheal: `/usr/local/bin/ollama-nvml-selfheal.sh.pre-3strike-20260826-1414`.
