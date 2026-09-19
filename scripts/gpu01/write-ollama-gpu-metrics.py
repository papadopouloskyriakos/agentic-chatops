#!/usr/bin/env python3
"""
write-ollama-gpu-metrics.py — node_exporter textfile collector for
nl-gpu01 ollama loaded models.

Polls BOTH Ollama planes (2026-08-26 split, gpu01 VRAM-starvation RCA):
  http://127.0.0.1:11434/api/ps — embed plane (omoikane/tg01/agri/gateway embeds)
  http://127.0.0.1:11441/api/ps — generate plane (gateway LLM calls)
and emits per-model, labelled with plane="embed"|"gen":
  ollama_model_size_bytes{plane,model}      — total memory the model needs
  ollama_model_size_vram_bytes{plane,model} — portion resident on GPU
  ollama_model_gpu_only{plane,model}        — 1 if size_vram >= size, else 0
  ollama_loaded_models{plane}               — number of currently loaded models
  ollama_plane_up{plane}                    — 1 if the plane answered /api/ps
  ollama_metrics_last_run_timestamp         — Unix time of last successful run

Paired with the OllamaModelNotGpuOnly / OllamaMetricsExporterStale alerts in
infrastructure/nl/production/k8s/namespaces/monitoring/agentic-health-alerts.tf
and claude-gateway prometheus/alert-rules/agentic-health.yml.

Background: 2026-05-13 catastrophic-CPU incident on nl-gpu01 — ollama
silently fell back to CPU when gemma3:12b couldn't fit in VRAM, saturating
~15 cores at 1468% CPU. Fix was server-side baked `PARAMETER num_gpu 999`
on every Modelfile. This script is the drift-detection layer: if any model
loads with size_vram < size, the fix has regressed and the alert fires.
Runbooks: claude-gateway memory/ollama_gpu_only_lockdown_20260513.md,
docs/runbooks/rerank-service.md § Dynamic VRAM (plane split).
"""

import json
import os
import sys
import tempfile
import time
import urllib.request

TEXTFILE_DIR = "/var/lib/node_exporter/textfile_collector"
OUT_FILE = os.path.join(TEXTFILE_DIR, "ollama_gpu.prom")
PLANES = {
    "embed": "http://127.0.0.1:11434/api/ps",
    "gen": "http://127.0.0.1:11441/api/ps",
}


def fetch_ps(url: str) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def escape_label(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(planes: dict) -> str:
    lines = [
        "# HELP ollama_model_size_bytes Total memory the model needs incl. KV cache + compute graph.",
        "# TYPE ollama_model_size_bytes gauge",
        "# HELP ollama_model_size_vram_bytes Portion of the model resident on GPU.",
        "# TYPE ollama_model_size_vram_bytes gauge",
        "# HELP ollama_model_gpu_only 1 iff size_vram >= size (model fully on GPU), else 0.",
        "# TYPE ollama_model_gpu_only gauge",
        "# HELP ollama_loaded_models Number of currently loaded models per /api/ps.",
        "# TYPE ollama_loaded_models gauge",
        "# HELP ollama_plane_up 1 if the ollama instance for this plane answered /api/ps.",
        "# TYPE ollama_plane_up gauge",
        "# HELP ollama_metrics_last_run_timestamp Unix time of last successful metrics emission.",
        "# TYPE ollama_metrics_last_run_timestamp gauge",
    ]
    for plane, data in planes.items():
        pl = escape_label(plane)
        if data is None:
            lines.append(f'ollama_plane_up{{plane="{pl}"}} 0')
            continue
        lines.append(f'ollama_plane_up{{plane="{pl}"}} 1')
        models = data.get("models", [])
        lines.append(f'ollama_loaded_models{{plane="{pl}"}} {len(models)}')
        for m in models:
            name = escape_label(m.get("name", "unknown"))
            size = int(m.get("size", 0))
            vram = int(m.get("size_vram", 0))
            gpu_only = 1 if vram >= size and size > 0 else 0
            lines.append(f'ollama_model_size_bytes{{plane="{pl}",model="{name}"}} {size}')
            lines.append(f'ollama_model_size_vram_bytes{{plane="{pl}",model="{name}"}} {vram}')
            lines.append(f'ollama_model_gpu_only{{plane="{pl}",model="{name}"}} {gpu_only}')
    lines.append(f"ollama_metrics_last_run_timestamp {int(time.time())}")
    return "\n".join(lines) + "\n"


def main() -> int:
    planes = {}
    ok = 0
    for plane, url in PLANES.items():
        try:
            planes[plane] = fetch_ps(url)
            ok += 1
        except Exception as e:
            print(f"WARN: {plane} plane ({url}): {e}", file=sys.stderr)
            planes[plane] = None
    if ok == 0:
        # Nothing reachable: leave the previous file so *Stale fires, not a
        # misleading fresh file claiming zero models.
        return 1
    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ollama_gpu.", suffix=".prom", dir=TEXTFILE_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(render(planes))
        os.chmod(tmp, 0o644)
        os.replace(tmp, OUT_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
