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

- Service config: `/srv/rerank/app/server.py`, `/srv/rerank/docker-compose.yml` on gpu01
- Reference memory: `memory/rerank_service_crossencoder.md`
- Metrics: `kb_rerank_service_up`, `kb_rerank_probe_latency_ms` (see `docs/rag-metrics-reference.md`)
- Client code: `scripts/kb-semantic-search.py:_rerank_via_crossencoder`
