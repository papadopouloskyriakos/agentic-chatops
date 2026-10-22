"""Best-effort LLM-trace export to self-hosted Langfuse — orchestrator Brick 2 LLM/agent
observability (IFRNLLEI01PRD-1421, 2026-06-26). Sends a completed gateway session as a Langfuse
trace + generation so the LLM-specific view (sessions, model, cost, turns) is queryable.

NEVER raises — observability must not break reconcile. Reads LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY
from the environment or the repo .env. Returns True on send, False on any failure/missing-config.
Langfuse v2 self-hosted at nlopenobserve01:3000 (Docker, Postgres-only). See
memory/langfuse_access_20260626.
"""
import base64
import json
import os
import time
import urllib.request
import uuid
from pathlib import Path


def _cfg():
    cfg = {}
    for k in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    if len(cfg) < 3:
        try:
            env = Path(__file__).resolve().parent.parent.parent / ".env"
            for line in env.read_text().splitlines():
                if line.startswith("LANGFUSE_") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass
    return cfg


def send_session(issue_id, model=None, cost_usd=None, num_turns=None, confidence=None,
                 resolution_type=None, input_text="", output_text=""):
    try:
        c = _cfg()
        host, pk, sk = c.get("LANGFUSE_HOST"), c.get("LANGFUSE_PUBLIC_KEY"), c.get("LANGFUSE_SECRET_KEY")
        if not (host and pk and sk):
            return False
        tid = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        batch = {"batch": [
            {"id": str(uuid.uuid4()), "type": "trace-create", "timestamp": now,
             "body": {"id": tid, "name": "chatops-session", "timestamp": now,
                      "metadata": {"issue": issue_id, "resolution": resolution_type,
                                   "confidence": confidence}}},
            {"id": str(uuid.uuid4()), "type": "generation-create", "timestamp": now,
             "body": {"id": str(uuid.uuid4()), "traceId": tid, "name": "claude-session",
                      "model": model, "startTime": now, "endTime": now,
                      "input": input_text or f"[gateway session {issue_id}]",
                      "output": output_text or "[reconciled]",
                      "usage": {"totalCost": cost_usd},
                      "metadata": {"num_turns": num_turns}}},
        ]}
        auth = "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()
        req = urllib.request.Request(host.rstrip("/") + "/api/public/ingestion",
                                     data=json.dumps(batch).encode(), method="POST")
        req.add_header("Authorization", auth)
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception:
        return False
