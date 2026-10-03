# omoikane ColBERT — BGE-M3 multi-vector encoder service.
#
# Wraps `BGEM3FlagModel` from FlagEmbedding (the canonical BGE-M3 inference
# library) to expose a small JSON HTTP API. The model produces THREE outputs
# from a single forward pass: dense (1024-dim CLS), sparse (lexical weights),
# and ColBERT-style multi-vector (one 1024-dim vector per token).
#
# Daemon's RAG client uses the multi-vector output to drive a Qdrant
# `MultiVectorConfig{comparator: max_sim}` collection — true late-interaction
# scoring, not the dense fallback the TEI service was producing.
#
# We deliberately load the model at startup so /healthz only succeeds
# once weights are resident — Docker healthcheck flips to healthy at that
# point. First load takes ~25-40s (CPU, fp32, 2.27 GB safetensors).
#
# VRAM discipline (2026-08-26, nl-gpu01 VRAM-starvation RCA — this
# service had grown to 10.2 GB of a 23 GB card for a 2.27 GB model):
#   * torch.cuda.empty_cache() after every /encode, so the PyTorch caching
#     allocator returns activation blocks to the driver instead of hoarding
#     the historical peak batch forever.
#   * Idle unload: after IDLE_UNLOAD_SECONDS without a request the model is
#     dropped from the GPU entirely and lazily reloaded on the next /encode
#     (~25-40 s cold). IDLE_UNLOAD_SECONDS=0 disables.
#   * MAX_LENGTH_CAP bounds the per-request max_length a client may ask for
#     (the peak activation footprint scales with inputs x max_length^2).
#   * GET /stats exposes loaded/idle/VRAM counters for monitoring.
# Rollback: restore server.py.pre-dynamic-<date> and `docker compose restart`.

import gc
import os
import threading
import time
from typing import Optional

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from FlagEmbedding import BGEM3FlagModel
from pydantic import BaseModel, Field

MODEL_PATH = os.environ.get("MODEL_PATH", "/data/bge-m3")
USE_FP16 = os.environ.get("USE_FP16", "false").lower() == "true"
MAX_LENGTH_DEFAULT = int(os.environ.get("MAX_LENGTH", "512"))
MAX_LENGTH_CAP = int(os.environ.get("MAX_LENGTH_CAP", "2048"))
IDLE_UNLOAD_S = int(os.environ.get("IDLE_UNLOAD_SECONDS", "1800"))
EMPTY_CACHE = os.environ.get("EMPTY_CACHE_AFTER_REQUEST", "true").lower() == "true"

app = FastAPI(title="omoikane-colbert", version="1.1.0")

_lock = threading.Lock()
MODEL: Optional[BGEM3FlagModel] = None
_last_used = time.time()
_stats = {"requests": 0, "loads": 0, "unloads": 0, "started_at": time.time()}


class EncodeRequest(BaseModel):
    inputs: list[str] = Field(..., min_length=1, max_length=64)
    return_dense: bool = True
    return_sparse: bool = False
    return_colbert_vecs: bool = True
    max_length: Optional[int] = None


class EncodeResponse(BaseModel):
    dense: Optional[list[list[float]]] = None
    sparse: Optional[list[dict[str, float]]] = None
    colbert: Optional[list[list[list[float]]]] = None
    dim: int
    n_inputs: int
    elapsed_ms: float


def _vram() -> dict:
    if not torch.cuda.is_available():
        return {"vram_allocated_mb": -1, "vram_reserved_mb": -1}
    return {
        "vram_allocated_mb": torch.cuda.memory_allocated() // 2**20,
        "vram_reserved_mb": torch.cuda.memory_reserved() // 2**20,
    }


def _load() -> BGEM3FlagModel:
    """Load the model if not resident. Caller holds _lock."""
    global MODEL
    if MODEL is None:
        t0 = time.time()
        print(f"[colbert] loading BGE-M3 from {MODEL_PATH} (fp16={USE_FP16}) ...", flush=True)
        MODEL = BGEM3FlagModel(MODEL_PATH, use_fp16=USE_FP16)
        _stats["loads"] += 1
        print(f"[colbert] model loaded in {time.time() - t0:.1f}s, {_vram()}", flush=True)
    return MODEL


def _unload(reason: str) -> None:
    """Drop the model from the GPU. Caller holds _lock."""
    global MODEL
    if MODEL is None:
        return
    MODEL = None
    gc.collect()
    torch.cuda.empty_cache()
    _stats["unloads"] += 1
    print(f"[colbert] unloaded ({reason}); {_vram()}", flush=True)


def _reaper() -> None:
    while True:
        time.sleep(30)
        if IDLE_UNLOAD_S <= 0:
            continue
        with _lock:
            idle = time.time() - _last_used
            if MODEL is not None and idle > IDLE_UNLOAD_S:
                _unload(f"idle {int(idle)}s > {IDLE_UNLOAD_S}s")


with _lock:
    _load()
threading.Thread(target=_reaper, name="idle-reaper", daemon=True).start()
print(f"[colbert] ready (idle_unload={IDLE_UNLOAD_S}s, empty_cache={EMPTY_CACHE}, max_length_cap={MAX_LENGTH_CAP})", flush=True)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "model_path": MODEL_PATH, "loaded": MODEL is not None}


@app.get("/readyz")
def readyz() -> dict:
    return {"status": "ok"}


@app.get("/stats")
def stats() -> dict:
    return {
        "model_path": MODEL_PATH,
        "fp16": USE_FP16,
        "loaded": MODEL is not None,
        "idle_seconds": int(time.time() - _last_used),
        "idle_unload_seconds": IDLE_UNLOAD_S,
        "empty_cache_after_request": EMPTY_CACHE,
        "max_length_cap": MAX_LENGTH_CAP,
        **_stats,
        **_vram(),
    }


@app.post("/encode", response_model=EncodeResponse)
def encode(req: EncodeRequest) -> EncodeResponse:
    global _last_used
    if not (req.return_dense or req.return_sparse or req.return_colbert_vecs):
        raise HTTPException(status_code=400, detail="at least one of return_dense/return_sparse/return_colbert_vecs must be true")
    max_length = min(req.max_length or MAX_LENGTH_DEFAULT, MAX_LENGTH_CAP)
    t0 = time.time()
    with _lock:
        model = _load()
        out = model.encode(
            req.inputs,
            return_dense=req.return_dense,
            return_sparse=req.return_sparse,
            return_colbert_vecs=req.return_colbert_vecs,
            max_length=max_length,
        )
        _last_used = time.time()
        _stats["requests"] += 1
        if EMPTY_CACHE:
            torch.cuda.empty_cache()
    elapsed_ms = (time.time() - t0) * 1000.0

    dense = None
    if req.return_dense and "dense_vecs" in out:
        dv = out["dense_vecs"]
        dense = dv.tolist() if isinstance(dv, np.ndarray) else [v.tolist() for v in dv]

    sparse = None
    if req.return_sparse and "lexical_weights" in out:
        sparse = [{str(k): float(v) for k, v in w.items()} for w in out["lexical_weights"]]

    colbert = None
    if req.return_colbert_vecs and "colbert_vecs" in out:
        colbert = [v.tolist() for v in out["colbert_vecs"]]

    dim = 1024
    if colbert and colbert[0]:
        dim = len(colbert[0][0])
    elif dense:
        dim = len(dense[0])

    return EncodeResponse(
        dense=dense,
        sparse=sparse,
        colbert=colbert,
        dim=dim,
        n_inputs=len(req.inputs),
        elapsed_ms=elapsed_ms,
    )
