"""Cross-encoder reranker microservice. BAAI/bge-reranker-v2-m3 on GPU.

POST /rerank  {"query":"...", "documents":["...",...], "top_k":5}
  -> {"ranked":[{"index":N,"score":float},...], "latency_ms":int}
GET  /health  -> "ok"   (200 whenever the process is alive; the model loads lazily)
GET  /stats   -> JSON   {loaded, idle_seconds, vram_allocated_mb, vram_reserved_mb, ...}

VRAM discipline (2026-08-26, nl-gpu01 VRAM-starvation RCA — see
docs/runbooks/rerank-service.md § Dynamic VRAM):
  * torch.cuda.empty_cache() after every request, so the PyTorch caching
    allocator hands activation blocks back to the driver instead of hoarding
    the historical peak forever (this service sat at 4.3 GB for a 2.2 GB model).
  * Idle unload: after IDLE_UNLOAD_SECONDS without a request the model is
    dropped from the GPU entirely (0 MB held) and lazily reloaded on the next
    /rerank (~3-8 s from the local HF cache). IDLE_UNLOAD_SECONDS=0 disables.
  * Eager load at startup is kept so a fresh container is warm immediately.
Rollback: restore server.py.pre-dynamic-<date> and `docker compose restart rerank`.
"""
import gc
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

print("[rerank] importing sentence_transformers...", flush=True)
import torch
from sentence_transformers import CrossEncoder

MODEL_NAME = os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
PORT = int(os.environ.get("PORT", "11436"))
IDLE_UNLOAD_S = int(os.environ.get("IDLE_UNLOAD_SECONDS", "900"))
EMPTY_CACHE = os.environ.get("EMPTY_CACHE_AFTER_REQUEST", "true").lower() == "true"
MAX_DOCS = int(os.environ.get("MAX_DOCS", "256"))

_lock = threading.Lock()
_model = None
_last_used = time.time()
_stats = {"requests": 0, "loads": 0, "unloads": 0, "started_at": time.time()}


def _vram():
    if not torch.cuda.is_available():
        return {"vram_allocated_mb": -1, "vram_reserved_mb": -1}
    return {
        "vram_allocated_mb": torch.cuda.memory_allocated() // 2**20,
        "vram_reserved_mb": torch.cuda.memory_reserved() // 2**20,
    }


def _load():
    """Load the model if it is not resident. Caller holds _lock."""
    global _model
    if _model is None:
        t0 = time.time()
        print(f"[rerank] loading {MODEL_NAME} ...", flush=True)
        _model = CrossEncoder(MODEL_NAME, max_length=512, device="cuda")
        _stats["loads"] += 1
        print(f"[rerank] loaded in {time.time() - t0:.1f}s, {_vram()}", flush=True)
    return _model


def _unload(reason):
    """Drop the model from the GPU. Caller holds _lock."""
    global _model
    if _model is None:
        return
    _model = None
    gc.collect()
    torch.cuda.empty_cache()
    _stats["unloads"] += 1
    print(f"[rerank] unloaded ({reason}); {_vram()}", flush=True)


def _reaper():
    while True:
        time.sleep(30)
        if IDLE_UNLOAD_S <= 0:
            continue
        with _lock:
            idle = time.time() - _last_used
            if _model is not None and idle > IDLE_UNLOAD_S:
                _unload(f"idle {int(idle)}s > {IDLE_UNLOAD_S}s")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code, payload):
        out = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        if self.path == "/stats":
            self._json(200, {
                "model": MODEL_NAME,
                "loaded": _model is not None,
                "idle_seconds": int(time.time() - _last_used),
                "idle_unload_seconds": IDLE_UNLOAD_S,
                "empty_cache_after_request": EMPTY_CACHE,
                **_stats, **_vram(),
            })
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global _last_used
        if self.path != "/rerank":
            self.send_response(404); self.end_headers(); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            query = body["query"]
            documents = body["documents"]
            top_k = int(body.get("top_k", 5))
            if len(documents) > MAX_DOCS:
                self._json(400, {"error": f"too many documents ({len(documents)} > MAX_DOCS={MAX_DOCS})"})
                return
            if not documents:
                payload = {"ranked": [], "latency_ms": 0}
            else:
                pairs = [[query, d] for d in documents]
                t0 = time.time()
                with _lock:
                    model = _load()
                    scores = model.predict(pairs, show_progress_bar=False).tolist()
                    _last_used = time.time()
                    _stats["requests"] += 1
                    if EMPTY_CACHE:
                        torch.cuda.empty_cache()
                dt = time.time() - t0
                ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
                payload = {
                    "ranked": [{"index": int(i), "score": float(s)} for i, s in ranked],
                    "latency_ms": int(dt * 1000),
                    "model": MODEL_NAME,
                }
            self._json(200, payload)
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": str(e)})


if __name__ == "__main__":
    with _lock:
        _load()
    threading.Thread(target=_reaper, name="idle-reaper", daemon=True).start()
    print(f"[rerank] ready on :{PORT} (idle_unload={IDLE_UNLOAD_S}s, empty_cache={EMPTY_CACHE})", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
