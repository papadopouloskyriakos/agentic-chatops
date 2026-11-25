#!/usr/bin/env python3
"""Generate agentic stats JSON for portfolio widget."""
import json
import os
import sqlite3
import statistics
import datetime
import urllib.request
import ssl

# Env-overridable for testing (GATEWAY_DB is the repo-wide convention). IFRNLLEI01PRD-1048.
DB = os.environ.get("GATEWAY_DB", "/app/cubeos/claude-context/gateway.db")
TRIAGE_LOG = os.environ.get("TRIAGE_LOG", "/app/cubeos/claude-context/triage.log")
NETBOX_URL = "https://netbox.example.net"
NETBOX_TOKEN = "REDACTED_4bd0c65f"

# Tier-keyed substring map. The same model can carry different roles at different
# tiers (e.g. claude-sonnet-4-6 was the Tier 1 OpenClaw OAuth model briefly on
# 2026-04-29, and is also a rare Tier 2 Claude Code Sonnet fallback). Splitting by
# tier prevents the duplicate-dict-key bug that previously erased the Tier 1
# OpenClaw fallback labels for every Claude model. Order-sensitive within each tier:
# more specific patterns first.
#
# Post-2026-04-29 (cc-cc cutover) Tier 1 model is **Claude Code itself** — a single
# Claude Code session starts as Tier 1 (fast triage, cheap models) and escalates
# to Tier 2 (deep investigation, premium models) mid-session. The writer
# (poll-claude-usage.sh) hard-codes tier=2 for all Claude rows; CLASSIFY_OVERRIDE
# below re-attributes by model class at read time so the widget reflects the
# Tier 1 vs Tier 2 split the operator's mental model actually tracks.
ROLE_MAP = {
    0: {  # Local GPU — RAG pipeline components
        "nomic-embed-text": "RAG Embeddings",
        "bge-reranker": "Cross-Encoder Rerank",
        "Qwen3-Reranker": "Rerank (legacy Ollama)",
        "qwen2.5": "RAG Rerank + Synth Fallback",
        "qwen3:4b": "Query Rewriter (legacy, migrated to qwen2.5)",
        "qwen3": "Query Rewriter",
        "llama3.2": "Query Variant Generator",
    },
    1: {  # Tier 1 — fast triage. Today: Claude Code Haiku-class OR Z.ai GLM 4.7 (Sonnet/Haiku-tier). Pre-cc-cc: OpenClaw OpenAI.
        "glm-4.7": "Fast triage + synthesis (Z.ai GLM 4.7 Sonnet/Haiku-tier, Claude-Code plane since 2026-06-28)",
        "claude-haiku-4-5": "Fast triage + synthesis (Claude Code, current since cc-cc 2026-04-29)",
        "gpt-5.1": "Tier 1 OpenClaw Triage (legacy OpenAI, retired 2026-04-28)",
        "gpt-4o-mini": "Tier 1 OpenClaw Fallback (legacy OpenAI, retired)",
        "gpt-4o": "Tier 1 OpenClaw Triage (legacy OpenAI, retired)",
        "devstral": "Tier 1 OpenClaw Local Fallback (legacy, retired 2026-04-29)",
        "claude-opus-4-5": "Tier 1 OpenClaw Fallback (retired 2026-04-29 with cc-cc cutover)",
        "claude-sonnet-4-5": "Tier 1 OpenClaw Fallback (retired 2026-04-29 with cc-cc cutover)",
    },
    2: {  # Tier 2 — deep investigation, premium models (Anthropic Max OR Z.ai GLM Opus-tier)
        "claude-opus-4-8": "Tier 2 Investigation (Claude Code Opus, current)",
        "glm-5.2": "Tier 2 Investigation (Z.ai GLM 5.2 Opus-tier, Claude-Code plane default since 2026-06-28)",
        "claude-fable-5": "Tier 2 Investigation (Claude Code Fable, premium)",
        "claude-opus-4-7": "Tier 2 Investigation (legacy, primary 2026-04-19 → 2026-06-28)",
        "claude-opus-4-6": "Tier 2 Investigation (legacy, migrated to Opus 4.7 on 2026-04-19)",
        "claude-sonnet-4-6": "Tier 2 Sonnet Fallback (Claude Code)",
    },
}

# Read-side tier override: classify by model substring. Haiku-class Claude rows are
# re-attributed to Tier 1 (fast triage), Opus/Sonnet to Tier 2 (deep investigation).
# Matched against the raw model name from llm_usage *after* the writer's hard-coded
# tier. Substrings ordered most-specific-first.
CLASSIFY_OVERRIDE = [
    ("claude-haiku", 1),    # Tier 1 fast triage / synthesis
    ("claude-opus", 2),     # Tier 2 deep investigation
    ("claude-sonnet", 2),   # Tier 2 fallback
    ("glm-5.2", 2),         # Z.ai Opus-tier — Tier 2 deep investigation (Claude-Code plane)
    ("glm-4.7", 1),         # Z.ai Sonnet/Haiku-tier — Tier 1 fast triage (Claude-Code plane)
    ("gpt-",      1),       # legacy Tier 1 (OpenAI)
    ("devstral",  1),       # legacy Tier 1 local fallback
    ("deepseek-chat", 2),   # rare Tier 2 fallback experimentation
]

# Ollama/local-GPU model name substrings. These are ALWAYS Local GPU even when a
# writer mis-recorded a non-zero tier (e.g. the LLM judge stamped tier=2 on some
# gemma3:12b / qwen2.5:7b rows), which previously made one local model appear under
# both "Local Inference" AND "Tier 2" in the widget. Does not collide with any
# glm-/claude-/gpt- name.
LOCAL_MODEL_SUBSTRINGS = ("gemma", "qwen", "nomic-embed", "bge-reranker",
                          "llama", "-jury", "reranker")


def _classify_tier(model_name, default_tier):
    """Return the effective tier for `model_name`. Local models are pinned to
    Local GPU (tier 0) regardless of the writer's recorded tier; then
    CLASSIFY_OVERRIDE substrings win; else fall through to the writer's tier."""
    if default_tier == 0:
        return 0
    if any(s in model_name for s in LOCAL_MODEL_SUBSTRINGS):
        return 0
    for substr, tier in CLASSIFY_OVERRIDE:
        if substr in model_name:
            return tier
    return default_tier
NAME_MAP = {
    "claude-opus-4-7": "Claude Opus 4.7",
    "claude-opus-4-7[1m]": "Claude Opus 4.7 (1M ctx)",
    "claude-opus-4-6-20250514": "Claude Opus 4.6",
    "claude-opus-4-6": "Claude Opus 4.6",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-sonnet-4-6-20250514": "Claude Sonnet 4.6",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    "gpt-5.1": "GPT-5.1",
    "gpt-5.1-2025-11-13": "GPT-5.1",
    "gpt-4o-2024-08-06": "GPT-4o",
    "gpt-4o": "GPT-4o",
    "gpt-4o-mini": "GPT-4o Mini",
    "nomic-embed-text": "Nomic Embed Text",
    "qwen2.5:7b": "Qwen 2.5 7B",
    "qwen3:4b": "Qwen 3 4B",
    "qwen3:30b-a3b": "Qwen 3 30B A3B",
    "llama3.2:1b": "Llama 3.2 1B",
    "dengcao/Qwen3-Reranker-0.6B:F16": "Qwen3 Reranker 0.6B",
    "devstral-small-2": "Devstral Small 2",
    "bge-reranker-v2-m3": "BGE Reranker v2 M3",
    # Centralized Model Orchestration (2026-06-28, MRs !116-!120): the Claude-Code
    # plane defaults to Z.ai GLM (glm-5.2 = Opus-tier, glm-4.7 = Sonnet/Haiku-tier);
    # Anthropic Max subscription is the revert path. Verified live in llm_usage.model.
    "claude-opus-4-8": "Claude Opus 4.8",
    "claude-fable-5": "Claude Fable 5",
    "glm-5.2": "GLM 5.2 (Z.ai, Opus-tier)",
    "glm-4.7": "GLM 4.7 (Z.ai, Sonnet-tier)",
    "gemma3:12b+qwen2.5:7b-jury": "Gemma+Qwen Jury",
    "gemma3:12b": "Gemma 3 12B",
    "claude-sonnet-5": "Claude Sonnet 5",
    # API-plane paid per-token models via the shared LiteLLM (Mistral + DeepSeek).
    "gw-mistral-large": "Mistral Large (LiteLLM)",
    "mistral-large-latest": "Mistral Large (LiteLLM)",
    "deepseek-chat": "DeepSeek Chat",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
}

db = sqlite3.connect(DB)
models = {}

# Source 1: llm_usage — the single source of truth for all token data
# All tiers (0=local GPU, 1=OpenAI, 2=Claude) are tracked here
# NOTE: Claude poller rows (issue_id='') have inflated cache_read/cache_write
# from cumulative stats-cache.json values. For those rows, use input+output only.
# Runner rows (have issue_id) and non-Claude poller rows have correct cache values.
# models is keyed by (tier, model) so a single model used at two tiers (e.g.
# Sonnet 4.6 at Tier 1 OpenClaw briefly and Tier 2 Claude Code occasionally)
# stays as two distinct rows with distinct role labels.
for raw_tier, model, reqs, tokens in db.execute(
    """SELECT tier, model, COUNT(*),
       SUM(CASE
         WHEN issue_id != '' THEN input_tokens + output_tokens
           + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)
         WHEN model NOT LIKE 'claude-%' THEN input_tokens + output_tokens
           + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)
         ELSE input_tokens + output_tokens
       END)
       FROM llm_usage WHERE model != '' AND model IS NOT NULL
         AND model != '<synthetic>' GROUP BY tier, model"""
).fetchall():
    tier = _classify_tier(model, raw_tier)
    key = (tier, model)
    # CLASSIFY_OVERRIDE may map two raw_tier rows (legacy Tier 1 OpenClaw + current
    # Tier 2 Claude Code) of the same model into one effective tier — merge instead
    # of overwrite so we don't drop a row.
    if key in models:
        models[key]["requests"] += reqs
        models[key]["tokens"]   += tokens or 0
    else:
        models[key] = {"tier": tier, "requests": reqs, "tokens": tokens or 0, "sessions": 0}

# Source 2: sessions + session_log — session counts only (no token estimation).
# Sessions table has no tier column, so attach to the (tier, model) entry with
# the most tokens for that model. Defaults orphan sessions to tier=2 (Claude Code).
for model, sessions in db.execute(
    """SELECT model, COUNT(*) FROM (
         SELECT model FROM sessions WHERE model != '' AND model != '<synthetic>'
         UNION ALL
         SELECT model FROM session_log WHERE model != '' AND model != '<synthetic>'
       ) GROUP BY model"""
).fetchall():
    candidates = [k for k in models.keys() if k[1] == model]
    if candidates:
        best = max(candidates, key=lambda k: models[k]["tokens"])
        models[best]["sessions"] += sessions
        if models[best]["requests"] < sessions:
            models[best]["requests"] = sessions
    else:
        models[(2, model)] = {
            "tier": 2,
            "requests": sessions,
            "tokens": 0,
            "sessions": sessions,
        }

# Build model list — merge by (display, tier_label) so the same display name at
# different tiers stays as two visible widget rows under their respective tier
# sections. Role lookup is tier-scoped via ROLE_MAP[tier_id].
merged = {}
for (tier_id, model), data in models.items():
    display = NAME_MAP.get(model, model)
    role = next(
        (v for k, v in ROLE_MAP.get(tier_id, {}).items() if k in model),
        "General",
    )
    tier_label = "Local GPU" if tier_id == 0 else f"Tier {tier_id}"
    merge_key = (display, tier_label)
    if merge_key in merged:
        merged[merge_key]["requests"] += data["requests"]
        merged[merge_key]["tokens"] += data["tokens"]
    else:
        merged[merge_key] = {
            "model": display, "tier": tier_label, "role": role,
            "requests": data["requests"], "tokens": data["tokens"],
        }
model_list = sorted(merged.values(), key=lambda x: x["tokens"], reverse=True)

# Totals
# Exclude <synthetic> canary/probe rows (session_log carries ~77) so they don't
# inflate the public session/turn headline — same filter as the token aggregates.
total_sessions = db.execute(
    "SELECT (SELECT COUNT(*) FROM sessions WHERE COALESCE(model,'') != '<synthetic>')"
    " + (SELECT COUNT(*) FROM session_log WHERE COALESCE(model,'') != '<synthetic>')"
).fetchone()[0]
total_turns = db.execute(
    "SELECT COALESCE(SUM(num_turns),0) FROM sessions WHERE COALESCE(model,'') != '<synthetic>'"
).fetchone()[0]
total_turns += db.execute(
    "SELECT COALESCE(SUM(num_turns),0) FROM session_log WHERE COALESCE(model,'') != '<synthetic>'"
).fetchone()[0]
total_tokens = sum(m["tokens"] for m in model_list)
total_reqs = sum(m["requests"] for m in model_list)
avg_conf = db.execute(
    "SELECT ROUND(AVG(confidence),2) FROM sessions WHERE confidence >= 0"
).fetchone()[0] or 0
knowledge_entries = db.execute("SELECT COUNT(*) FROM incident_knowledge").fetchone()[0]

# NetBox device count (live)
devices_monitored = 309  # fallback (130 devices + 179 VMs; live NetBox query overrides)
try:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for endpoint in ["/api/dcim/devices/?limit=1", "/api/virtualization/virtual-machines/?limit=1"]:
        req = urllib.request.Request(
            NETBOX_URL + endpoint,
            headers={"Authorization": f"Token {NETBOX_TOKEN}"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            count = json.loads(resp.read()).get("count", 0)
            if endpoint.startswith("/api/dcim"):
                devices_monitored = count
            else:
                devices_monitored += count
except Exception:
    pass  # use fallback

# A2A stats
a2a_escalated = db.execute(
    "SELECT COUNT(*) FROM a2a_task_log WHERE message_type='escalation'"
).fetchone()[0]
a2a_reviews = db.execute(
    "SELECT COUNT(*) FROM a2a_task_log WHERE message_type='review'"
).fetchone()[0]

# Triage log stats. Parse once into a list of (ts_utc, outcome, issue_id) so the
# lifetime counters AND the new outcomes block (auto-resolve sparkline +
# closed-loop median) all read from the same source.
#
# Outcomes recognised (post-2026-05-11 Tier 1 suppression rollout):
#   resolved               : Tier 1 closed without escalation (deterministic suppression
#                            branch — maintenance / chaos / Freedom-down)
#   resolved-knownpattern  : Tier 1 suppression Phase 2 hit (transient-tagged incident match)
#   resolved-active-memory : Tier 1 suppression Phase 3 hit (operator-curated rule)
#   dedup                  : Tier 1 suppression Phase 1 hit (parent issue still open)
#   escalated              : Tier 2 (Claude Code) was spawned
#
# Auto-resolve % counts all three resolved-* outcomes (active resolutions). Dedup is
# tracked separately — it's work avoided on a duplicate, not an active resolve decision.
RESOLVE_OUTCOMES = ("resolved", "resolved-knownpattern", "resolved-active-memory")
DEDUP_OUTCOMES = ("dedup",)
ALL_KNOWN_OUTCOMES = RESOLVE_OUTCOMES + DEDUP_OUTCOMES + ("escalated",)

triage_events = []  # list of (datetime_utc, outcome, issue_id)
try:
    with open(TRIAGE_LOG) as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) < 5:
                continue
            outcome = parts[4]
            if outcome not in ALL_KNOWN_OUTCOMES:
                continue
            try:
                ts = datetime.datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
            except ValueError:
                continue
            issue_id = parts[7] if len(parts) >= 8 else ""
            triage_events.append((ts, outcome, issue_id))
except FileNotFoundError:
    pass

triage_resolved = sum(1 for _, o, _ in triage_events if o in RESOLVE_OUTCOMES)
triage_escalated = sum(1 for _, o, _ in triage_events if o == "escalated")
triage_dedup = sum(1 for _, o, _ in triage_events if o in DEDUP_OUTCOMES)

# Earliest record date for "since" field
since_date = db.execute(
    """SELECT MIN(d) FROM (
         SELECT MIN(started_at) AS d FROM sessions
         UNION ALL
         SELECT MIN(started_at) FROM session_log
         UNION ALL
         SELECT MIN(recorded_at) FROM llm_usage WHERE model != '' AND model IS NOT NULL
       )"""
).fetchone()[0]
since_str = since_date[:10] if since_date else datetime.datetime.utcnow().strftime("%Y-%m-%d")

# Time series: daily buckets for last 7 days
# Combine llm_usage (granular tokens) + sessions/session_log (estimated tokens from turns)
time_series_raw = {}
# Source A: llm_usage — real token counts per day per (effective tier, model).
# CLASSIFY_OVERRIDE re-attributes Claude Code rows: Haiku-class → Tier 1, Opus/Sonnet → Tier 2.
# Bucket key is (model, tier) so the widget can split a Claude Code session's
# Haiku synth turns (Tier 1) from its Opus deep-tooling turns (Tier 2).
for day, model_raw, raw_tier, reqs, tokens in db.execute(
    """SELECT DATE(recorded_at) AS day, model, tier, COUNT(*),
       SUM(CASE
         WHEN issue_id != '' THEN input_tokens + output_tokens
           + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)
         WHEN model NOT LIKE 'claude-%' THEN input_tokens + output_tokens
           + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)
         ELSE input_tokens + output_tokens
       END)
       FROM llm_usage
       WHERE model != '' AND model IS NOT NULL
         AND model != '<synthetic>'
         AND recorded_at >= DATE('now', '-6 days')
       GROUP BY day, model, tier"""
).fetchall():
    bucket = time_series_raw.setdefault(day, {})
    name = NAME_MAP.get(model_raw, model_raw)
    tier_id = _classify_tier(model_raw, raw_tier)
    tier_label = "Local GPU" if tier_id == 0 else f"Tier {tier_id}"
    key = (name, tier_label)
    if key in bucket:
        bucket[key]["tokens"]   += tokens
        bucket[key]["requests"] += reqs
    else:
        bucket[key] = {"tokens": tokens, "requests": reqs}

# No estimation sources — time_series uses only real llm_usage data

# Build the 7-day window and fill gaps
today = datetime.date.today()
target_days = [(today - datetime.timedelta(days=6 - i)).isoformat() for i in range(7)]
for day_str in target_days:
    time_series_raw.setdefault(day_str, {})

# Build sorted time_series array (only target days). Each per-day row now emits
# {model, tier, tokens, requests} so the frontend can group by tier without the
# fragile first-wins lookup that earlier shipped (and mis-attributed Haiku Tier 1
# rows to Tier 2 because of lifetime token order).
time_series = []
for day in target_days:
    bucket = time_series_raw.get(day, {})
    day_models = []
    for (mname, tier_label), mdata in sorted(bucket.items(), key=lambda x: x[1]["tokens"], reverse=True):
        day_models.append({
            "model": mname,
            "tier":  tier_label,
            "tokens":   mdata["tokens"],
            "requests": mdata["requests"],
        })
    time_series.append({
        "date": day,
        "tokens":   sum(m["tokens"]   for m in day_models),
        "requests": sum(m["requests"] for m in day_models),
        "models":   day_models,
    })

# === NEW: Operational depth metrics (from tool_call_log, execution_log, otel_spans) ===
tool_calls_total = db.execute("SELECT COUNT(*) FROM tool_call_log").fetchone()[0]
tool_unique = db.execute("SELECT COUNT(DISTINCT tool_name) FROM tool_call_log").fetchone()[0]
tool_errors = db.execute("SELECT COUNT(*) FROM tool_call_log WHERE error_type != ''").fetchone()[0]
tool_error_rate = round(tool_errors / max(tool_calls_total, 1), 4)
tool_avg_ms = db.execute("SELECT ROUND(AVG(duration_ms),0) FROM tool_call_log WHERE duration_ms > 0").fetchone()[0] or 0
tool_p50 = db.execute(
    "SELECT duration_ms FROM tool_call_log WHERE duration_ms > 0 ORDER BY duration_ms "
    "LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM tool_call_log WHERE duration_ms > 0)"
).fetchone()
tool_p50_ms = tool_p50[0] if tool_p50 else 0
tool_p95 = db.execute(
    "SELECT duration_ms FROM tool_call_log WHERE duration_ms > 0 ORDER BY duration_ms "
    "LIMIT 1 OFFSET (SELECT COUNT(*)*95/100 FROM tool_call_log WHERE duration_ms > 0)"
).fetchone()
tool_p95_ms = tool_p95[0] if tool_p95 else 0

# Top 10 tools by usage
top_tools = []
for name, cnt, errs, avg_ms in db.execute(
    """SELECT tool_name, COUNT(*) as cnt,
       SUM(CASE WHEN error_type != '' THEN 1 ELSE 0 END) as errs,
       ROUND(AVG(duration_ms),0) as avg_ms
       FROM tool_call_log GROUP BY tool_name ORDER BY cnt DESC LIMIT 10"""
).fetchall():
    top_tools.append({
        "tool": name, "calls": cnt, "errors": errs,
        "error_rate": round(errs / max(cnt, 1), 4),
        "avg_duration_ms": int(avg_ms or 0),
    })

# Execution log (infra commands)
exec_total = db.execute("SELECT COUNT(*) FROM execution_log").fetchone()[0]
exec_devices = db.execute("SELECT COUNT(DISTINCT device) FROM execution_log").fetchone()[0]
exec_failures = db.execute("SELECT COUNT(*) FROM execution_log WHERE exit_code != 0").fetchone()[0]

# OTel spans
otel_spans = db.execute("SELECT COUNT(*) FROM otel_spans").fetchone()[0] if db.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='otel_spans'"
).fetchone() else 0
otel_traces = db.execute("SELECT COUNT(DISTINCT trace_id) FROM otel_spans").fetchone()[0] if otel_spans else 0

# === NEW: Quality & evaluation metrics ===
sessions_judged = db.execute("SELECT COUNT(*) FROM session_judgment").fetchone()[0]
judge_avg_score = db.execute(
    "SELECT ROUND(AVG(overall_score),2) FROM session_judgment WHERE overall_score > 0"
).fetchone()[0] or 0
trajectories_scored = db.execute("SELECT COUNT(*) FROM session_trajectory").fetchone()[0]
avg_trajectory = db.execute(
    "SELECT ROUND(AVG(trajectory_score),0) FROM session_trajectory WHERE trajectory_score >= 0"
).fetchone()[0] or 0

# GraphRAG
graph_entities = db.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0]
graph_relationships = db.execute("SELECT COUNT(*) FROM graph_relationships").fetchone()[0]

# Session transcripts + agent diary
transcript_chunks = db.execute("SELECT COUNT(*) FROM session_transcripts").fetchone()[0]
diary_entries = db.execute("SELECT COUNT(*) FROM agent_diary").fetchone()[0]
diary_agents = db.execute("SELECT COUNT(DISTINCT agent_name) FROM agent_diary").fetchone()[0]

# === NEW: Security posture ===
credentials_tracked = db.execute("SELECT COUNT(*) FROM credential_usage_log").fetchone()[0]
crowdsec_scenarios = db.execute("SELECT COUNT(*) FROM crowdsec_scenario_stats").fetchone()[0]
crowdsec_suppressed = db.execute(
    "SELECT COUNT(*) FROM crowdsec_scenario_stats WHERE auto_suppressed = 1"
).fetchone()[0]

# === Platform inventory (computed at runtime so the Operational Depth tile can't drift) ===
# REPO_ROOT is the claude-gateway checkout (parent of this script's directory);
# sqlite_tables comes from the already-open gateway.db connection.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _count_files(root, *exts):
    """Recursive count of files ending in any of *exts beneath root (0 if absent)."""
    n = 0
    for _d, _, _fs in os.walk(root):
        for _f in _fs:
            if _f.endswith(exts):
                n += 1
    return n


def _count_panels(path):
    """Panel count in a Grafana dashboard JSON, descending into row sub-panels."""
    try:
        with open(path) as _fh:
            _stack = list(json.load(_fh).get("panels", []) or [])
    except (json.JSONDecodeError, OSError):
        return 0
    _n = 0
    while _stack:
        _p = _stack.pop()
        _n += 1
        _stack.extend(_p.get("panels", []) or [])
    return _n


_grafana_dir = os.path.join(REPO_ROOT, "grafana")
_workflows_dir = os.path.join(REPO_ROOT, "workflows")
# Top-level workflow JSONs only (excludes subdirs like parallel-dev/ which hold
# spawned sub-workflows, not separate exports) — matches the "27 exported" count.
workflow_count = sum(
    1 for _f in (os.listdir(_workflows_dir) if os.path.isdir(_workflows_dir) else [])
    if _f.endswith(".json")
)
# Live n8n workflow count across the whole instance (not just gateway exports),
# read from the orchestrator component registry (repo-local, refreshed by the
# registry crons — no external n8n API call on the webhook path). Falls back to
# the exported-file count if the registry is unreadable.
workflows_n8n = 0
try:
    with open(os.path.join(REPO_ROOT, "config", "component-registry.json")) as _rf:
        _reg = json.load(_rf)
    _comps = _reg.get("components", _reg) if isinstance(_reg, dict) else _reg
    if isinstance(_comps, dict):
        _comps = _comps.get("components", [])
    workflows_n8n = sum(1 for _c in _comps if str(_c.get("type", "")) == "n8n-workflow")
except (json.JSONDecodeError, OSError, AttributeError, TypeError):
    pass
if not workflows_n8n:
    workflows_n8n = workflow_count
scripts_count = _count_files(os.path.join(REPO_ROOT, "scripts"), ".py", ".sh")
grafana_dashboards = _count_files(_grafana_dir, ".json")  # custom, operator-built (grafana/*.json)
grafana_custom_panels = sum(
    _count_panels(os.path.join(_grafana_dir, _f))
    for _f in (os.listdir(_grafana_dir) if os.path.isdir(_grafana_dir) else [])
    if _f.endswith(".json")
)
# total_nodes = sum of node counts across all exported workflows.
total_nodes = 0
if os.path.isdir(_workflows_dir):
    for _wf in os.listdir(_workflows_dir):
        if _wf.endswith(".json"):
            try:
                with open(os.path.join(_workflows_dir, _wf)) as _fh:
                    total_nodes += len(json.load(_fh).get("nodes", []) or [])
            except (json.JSONDecodeError, OSError):
                pass
sqlite_tables = db.execute(
    "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
).fetchone()[0]
sqlite_total_rows = db.execute("""
    SELECT SUM(c) FROM (
        SELECT COUNT(*) c FROM sessions UNION ALL SELECT COUNT(*) FROM session_log
        UNION ALL SELECT COUNT(*) FROM llm_usage UNION ALL SELECT COUNT(*) FROM incident_knowledge
        UNION ALL SELECT COUNT(*) FROM wiki_articles UNION ALL SELECT COUNT(*) FROM session_judgment
        UNION ALL SELECT COUNT(*) FROM session_trajectory UNION ALL SELECT COUNT(*) FROM crowdsec_scenario_stats
        UNION ALL SELECT COUNT(*) FROM session_transcripts UNION ALL SELECT COUNT(*) FROM agent_diary
        UNION ALL SELECT COUNT(*) FROM graph_entities UNION ALL SELECT COUNT(*) FROM graph_relationships
        UNION ALL SELECT COUNT(*) FROM tool_call_log UNION ALL SELECT COUNT(*) FROM execution_log
        UNION ALL SELECT COUNT(*) FROM credential_usage_log UNION ALL SELECT COUNT(*) FROM session_quality
        UNION ALL SELECT COUNT(*) FROM prompt_scorecard UNION ALL SELECT COUNT(*) FROM lessons_learned
        UNION ALL SELECT COUNT(*) FROM a2a_task_log UNION ALL SELECT COUNT(*) FROM session_feedback
        UNION ALL SELECT COUNT(*) FROM openclaw_memory
    )
""").fetchone()[0]

# === Outcomes block ===
# Two derived metrics for the portfolio "Outcomes" tile:
#   1. Auto-resolve % — rolling 7-day rate, plotted daily for the last 56 days,
#      plus current 7d / prior 7d / delta in percentage points.
#   2. Closed-loop duration — for triage events in the last 7d, find each
#      escalated issue's session.duration_seconds; Tier 1 (resolved) closes at
#      the triage timestamp so contributes 0s. Median + p95. Same again for the
#      prior 7-day window. Sessions with duration_seconds == 0 (still mid-run)
#      are excluded from the closed pool and counted separately as "open".
OUTCOMES_TOTAL_DAYS = 56
OUTCOMES_WINDOW_DAYS = 7
_now_utc = datetime.datetime.now(datetime.timezone.utc)
# End-of-today, UTC midnight boundary (so today's window is [today-7d, today+1d) — inclusive of today).
_today_eod = _now_utc.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)

# Per-incident best-outcome ranking. Industry-standard SRE practice (Google SRE Book
# Ch 6, Datadog SRE Maturity Model, PagerDuty MTTR) treats the unit of measurement as
# the incident (one issue_id), not the alert event. Sustained outages spam dozens of
# repeat alerts on the same issue_id; event-based counting inflates the denominator
# 3-5× and tanks the headline rate. See [[feedback_count_incidents_not_events]].
#
# Ranking: resolved-* > dedup > escalated. An issue counts as "resolved" if ANY event
# in the window resolved it; falls through to "dedup" if at least one event was deduped
# (and none resolved); else "escalated".
def _window_counts(end_dt, days):
    """Return (resolved, escalated, dedup, rate) — per-incident counts.

    Events without an issue_id are excluded entirely (they never spawned a session).
    """
    start_dt = end_dt - datetime.timedelta(days=days)
    by_issue = {}  # issue_id → {"resolve", "dedup", "escalate"}
    for ts, o, iid in triage_events:
        if not iid:
            continue
        if not (start_dt <= ts < end_dt):
            continue
        rank = by_issue.setdefault(iid, {"resolve": False, "dedup": False, "escalate": False})
        if o in RESOLVE_OUTCOMES:
            rank["resolve"] = True
        elif o in DEDUP_OUTCOMES:
            rank["dedup"] = True
        elif o == "escalated":
            rank["escalate"] = True
    r = sum(1 for v in by_issue.values() if v["resolve"])
    d = sum(1 for v in by_issue.values() if not v["resolve"] and v["dedup"])
    e = sum(1 for v in by_issue.values() if not v["resolve"] and not v["dedup"] and v["escalate"])
    rate = (r / (r + e)) if (r + e) else None
    return (r, e, d, rate)


def _window_event_counts(end_dt, days):
    """Event-based counts (one row per triage.log entry) for transparency. The old
    pre-2026-05-12 metric definition. Exposed in outcomes.auto_resolve.event_based
    so reviewers can see both numbers and never accidentally chase a gameable one."""
    start_dt = end_dt - datetime.timedelta(days=days)
    r = sum(1 for ts, o, _ in triage_events
            if start_dt <= ts < end_dt and o in RESOLVE_OUTCOMES)
    e = sum(1 for ts, o, _ in triage_events
            if start_dt <= ts < end_dt and o == "escalated")
    d = sum(1 for ts, o, _ in triage_events
            if start_dt <= ts < end_dt and o in DEDUP_OUTCOMES)
    rate = (r / (r + e)) if (r + e) else None
    return (r, e, d, rate)


def _window_rate(end_dt, days):
    """Back-compat shim returning (resolved, escalated, rate) — per-incident.
    Excludes dedup (preserved from pre-2026-05-12 callers)."""
    r, e, _, rate = _window_counts(end_dt, days)
    return (r, e, rate)

_daily = []
for d in range(OUTCOMES_TOTAL_DAYS):
    _end = _today_eod - datetime.timedelta(days=(OUTCOMES_TOTAL_DAYS - 1 - d))
    r, e, dd, rate = _window_counts(_end, OUTCOMES_WINDOW_DAYS)
    _daily.append({
        "date": (_end - datetime.timedelta(days=1)).date().isoformat(),
        "resolved": r,
        "escalated": e,
        "dedup": dd,
        "rate": rate,  # may be None if no events in this 7d window
    })
_cur_r, _cur_e, _cur_d, _cur_rate = _window_counts(_today_eod, OUTCOMES_WINDOW_DAYS)
_pri_r, _pri_e, _pri_d, _pri_rate = _window_counts(_today_eod - datetime.timedelta(days=OUTCOMES_WINDOW_DAYS), OUTCOMES_WINDOW_DAYS)

# Event-based sibling counts. Exposed in outcomes.auto_resolve.event_based for full
# transparency; the headline rate (current_rate) is per-incident per industry standard.
_cur_ev_r, _cur_ev_e, _cur_ev_d, _cur_ev_rate = _window_event_counts(_today_eod, OUTCOMES_WINDOW_DAYS)
_pri_ev_r, _pri_ev_e, _pri_ev_d, _pri_ev_rate = _window_event_counts(
    _today_eod - datetime.timedelta(days=OUTCOMES_WINDOW_DAYS), OUTCOMES_WINDOW_DAYS)

# Per-phase breakdown within the current 7d window (helps the operator see which
# phase is contributing most). All counts are last 7d, event-based.
def _count_by_outcome(start_dt, end_dt, outcome):
    return sum(1 for ts, o, _ in triage_events if start_dt <= ts < end_dt and o == outcome)
_cur_window_start = _today_eod - datetime.timedelta(days=OUTCOMES_WINDOW_DAYS)
_breakdown_7d = {
    "resolved_deterministic": _count_by_outcome(_cur_window_start, _today_eod, "resolved"),
    "resolved_knownpattern": _count_by_outcome(_cur_window_start, _today_eod, "resolved-knownpattern"),
    "resolved_active_memory": _count_by_outcome(_cur_window_start, _today_eod, "resolved-active-memory"),
    "dedup": _count_by_outcome(_cur_window_start, _today_eod, "dedup"),
    "escalated": _count_by_outcome(_cur_window_start, _today_eod, "escalated"),
}

# Closed-loop durations. An escalated session's finalised duration lives in
# `sessions` while live and moves to `session_log` once archived (the
# reconcile-completed-sessions cron). Reading ONLY `sessions` missed every
# archived loop (357 vs 25) and starved the p95 (IFRNLLEI01PRD-1048). Union both,
# keeping the longest finalised duration per issue_id.
_session_dur: dict[str, int] = {}
for _tbl in ("sessions", "session_log"):
    try:
        for _iid, _dur in db.execute(
                f"SELECT issue_id, COALESCE(duration_seconds,0) FROM {_tbl}"):
            if _iid and (_dur or 0) > _session_dur.get(_iid, 0):
                _session_dur[_iid] = _dur
    except sqlite3.OperationalError:
        pass  # table absent in a minimal fixture

# An escalation left unfinalised longer than this is abandoned, not open — it
# must not sit in the n_open denominator forever (aligns with the reconcile
# cron's 48h orphan threshold). IFRNLLEI01PRD-1048.
STALE_OPEN_DAYS = 2

def _bucket(start_dt, end_dt):
    # Per-INCIDENT (issue_id), not per-event: repeat-alert escalations from a flap
    # storm share one loop. Event-based counting inflated n_open to 1142 phantoms.
    # Mirrors the auto_resolve per-incident semantics ([[feedback_count_incidents_not_events]]).
    by_issue: dict[str, dict] = {}
    instant_closes = 0  # Tier-1 resolves with no issue_id (no session) — close at 0s
    for ts, outcome, issue_id in triage_events:
        if not (start_dt <= ts < end_dt):
            continue
        if not issue_id:
            if outcome in RESOLVE_OUTCOMES:
                instant_closes += 1
            continue
        rec = by_issue.setdefault(
            issue_id, {"resolve": False, "dedup": False, "escalate": False, "last_esc": None})
        if outcome in RESOLVE_OUTCOMES:
            rec["resolve"] = True
        elif outcome in DEDUP_OUTCOMES:
            rec["dedup"] = True
        elif outcome == "escalated":
            rec["escalate"] = True
            if rec["last_esc"] is None or ts > rec["last_esc"]:
                rec["last_esc"] = ts
    closed, open_n = [0] * instant_closes, 0
    for iid, rec in by_issue.items():
        if rec["resolve"]:
            closed.append(0)            # Tier-1 closed the loop at triage time
        elif rec["escalate"]:
            # closure = the spawned Claude Code session's finalised duration
            # (sessions while live, session_log once archived).
            dur = _session_dur.get(iid, 0)
            if dur > 0:
                closed.append(dur)
            elif rec["last_esc"] and (_now_utc - rec["last_esc"]).total_seconds() <= STALE_OPEN_DAYS * 86400:
                open_n += 1             # genuinely still open (recent, unfinalised)
            # else: abandoned (old escalation, never finalised) — neither closed nor open
        # dedup-only incident: the parent incident owns the loop — skip
    return closed, open_n

def _pct(data, p):
    if not data:
        return None
    s = sorted(data)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]

def _med(data):
    return int(statistics.median(data)) if data else None

_last7_start = _today_eod - datetime.timedelta(days=OUTCOMES_WINDOW_DAYS)
_prior_start = _today_eod - datetime.timedelta(days=2 * OUTCOMES_WINDOW_DAYS)
_prior_end = _today_eod - datetime.timedelta(days=OUTCOMES_WINDOW_DAYS)

_closed_cur, _open_cur = _bucket(_last7_start, _today_eod)
_closed_prior, _ = _bucket(_prior_start, _prior_end)

_cur_med, _cur_p95 = _med(_closed_cur), _pct(_closed_cur, 95)
_pri_med, _pri_p95 = _med(_closed_prior), _pct(_closed_prior, 95)

# Tier-2 gate observability (IFRNLLEI01PRD-1102, autonomy-forward gate). DISTINCT
# from auto_resolve above: that measures Tier-1 deterministic suppression (an
# incident closed BEFORE a Claude session spawns). THIS measures, of the Tier-2
# sessions the classifier actually banded, how many the gate auto-resolved
# (AUTO / AUTO_NOTICE) vs sent to a human poll+pause (POLL_PAUSE). Reads
# session_risk_audit.band — populated reliably since the 2026-06-16 lock-robust
# write fix; sparse until rows accumulate. Empty -> auto_rate None (not 0%).
_gate = {"window_days": OUTCOMES_WINDOW_DAYS, "total_banded": 0,
         "bands": {}, "auto_rate": None, "sms_paged": 0,
         "note": "Tier-2 gate decisions; distinct from auto_resolve (Tier-1 pre-session suppression)."}
try:
    _grows = db.execute(
        "SELECT band, COUNT(*), COALESCE(SUM(sms_required), 0) "
        "FROM session_risk_audit "
        "WHERE classified_at >= datetime('now', ?) AND band IS NOT NULL "
        "GROUP BY band",
        (f"-{OUTCOMES_WINDOW_DAYS} days",),
    ).fetchall()
    _bands = {b: n for b, n, _ in _grows}
    _total_banded = sum(_bands.values())
    _auto = _bands.get("AUTO", 0) + _bands.get("AUTO_NOTICE", 0)
    _gate.update({
        "total_banded": _total_banded,
        "bands": _bands,
        "auto_rate": (round(_auto / _total_banded, 4) if _total_banded else None),
        "sms_paged": sum(s for _, _, s in _grows),
    })
except Exception:  # noqa: BLE001 — stats must never crash on an audit-table read
    pass

# Lifetime governed-decision tally for the hero KPI row — every banded Tier-2
# session on the tamper-evident audit trail (all-time, not windowed), and the
# fraction the gate approved without a human poll (AUTO / AUTO_NOTICE).
_governance = {"decisions_total": 0, "auto_pct": None}
try:
    _grow = db.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN band IN ('AUTO','AUTO_NOTICE') THEN 1 ELSE 0 END) "
        "FROM session_risk_audit WHERE band IS NOT NULL AND band != ''"
    ).fetchone()
    _gtot = _grow[0] or 0
    _gauto = _grow[1] or 0
    _governance = {
        "decisions_total": _gtot,
        "auto_pct": (round(100.0 * _gauto / _gtot) if _gtot else None),
    }
except Exception:  # noqa: BLE001 — stats must never crash on an audit-table read
    pass

# Causal infragraph (world-model) size for the hero KPI card — the source_table=
# 'infragraph' subset of graph_entities (nodes) and the graph_relationships rows
# with learned dynamics (edges). DISTINCT from the retrieval GraphRAG KG in
# quality.graph_* (which is the superset over all source tables). Matches
# infragraph-query.py health() exactly (365 / 507).
_infragraph = {"nodes": 0, "edges": 0}
try:
    _infragraph = {
        "nodes": db.execute(
            "SELECT COUNT(*) FROM graph_entities WHERE source_table='infragraph'"
        ).fetchone()[0],
        "edges": db.execute(
            "SELECT COUNT(*) FROM graph_relationships r "
            "JOIN infragraph_dynamics d ON d.rel_id = r.id"
        ).fetchone()[0],
    }
except Exception:  # noqa: BLE001 — stats must never crash on an audit-table read
    pass

# Daily rolling-7d Tier-2 auto-rate series for the gate sparkline (mirrors the
# auto_resolve.daily rolling semantics exactly: each row is the auto-rate over the
# 7d window ending that date). Sparse until session_risk_audit accrues — the
# autonomy-forward gate has only banded rows since 2026-06-16 — so the frontend
# plots just the trailing run with data. IFRNLLEI01PRD-1102.
_gate_daily = []
try:
    _gday = {}
    for _gd, _gband, _gn in db.execute(
            "SELECT date(classified_at) AS d, band, COUNT(*) "
            "FROM session_risk_audit "
            "WHERE classified_at >= datetime('now', ?) AND band IS NOT NULL "
            "GROUP BY d, band",
            (f"-{OUTCOMES_TOTAL_DAYS + OUTCOMES_WINDOW_DAYS} days",)):
        _slot = _gday.setdefault(_gd, {"auto": 0, "total": 0})
        _slot["total"] += _gn
        if _gband in ("AUTO", "AUTO_NOTICE"):
            _slot["auto"] += _gn
    for _gi in range(OUTCOMES_TOTAL_DAYS):
        _gend = _today_eod - datetime.timedelta(days=(OUTCOMES_TOTAL_DAYS - 1 - _gi))
        _grow = (_gend - datetime.timedelta(days=1)).date()
        _ga = _gt = 0
        for _gk in range(OUTCOMES_WINDOW_DAYS):
            _gslot = _gday.get((_grow - datetime.timedelta(days=_gk)).isoformat())
            if _gslot:
                _ga += _gslot["auto"]
                _gt += _gslot["total"]
        _gate_daily.append({
            "date": _grow.isoformat(),
            "auto_rate": (round(_ga / _gt, 4) if _gt else None),
        })
except Exception:  # noqa: BLE001 — stats must never crash on an audit-table read
    _gate_daily = []
_gate["daily"] = _gate_daily

outcomes = {
    "window_days": OUTCOMES_WINDOW_DAYS,
    "gate": _gate,
    "auto_resolve": {
        # Per-incident (industry-standard). Headline.
        "current_rate": _cur_rate,           # 0..1 or None — per-incident
        "prior_rate": _pri_rate,             # 0..1 or None — per-incident
        "delta_pp": (None if (_cur_rate is None or _pri_rate is None)
                     else round((_cur_rate - _pri_rate) * 100, 1)),
        "current_resolved": _cur_r,          # unique-issue count
        "current_escalated": _cur_e,         # unique-issue count
        "daily": _daily,                     # 56 rows of {date, resolved, escalated, dedup, rate}
        "counting_unit": "incident",         # explicit so reviewers see the unit
        # Event-based sibling for transparency (one row per triage.log entry).
        # Diverges from per-incident during repeat-alert storms (Freedom outage,
        # GR poller stall, K8s flap). Never use this as a headline — it is gameable
        # by suppression tactics. See [[feedback_count_incidents_not_events]] and
        # [[feedback_no_dedup_writes_to_pad_numerator]].
        "event_based": {
            "current_rate": _cur_ev_rate,
            "prior_rate": _pri_ev_rate,
            "delta_pp": (None if (_cur_ev_rate is None or _pri_ev_rate is None)
                         else round((_cur_ev_rate - _pri_ev_rate) * 100, 1)),
            "current_resolved": _cur_ev_r,
            "current_escalated": _cur_ev_e,
        },
    },
    "closed_loop": {
        "n_closed": len(_closed_cur),
        "n_open": _open_cur,
        "median_seconds": _cur_med,
        "p95_seconds": _cur_p95,
        "prior_n_closed": len(_closed_prior),
        "prior_median_seconds": _pri_med,
        "prior_p95_seconds": _pri_p95,
        "delta_median_seconds": (None if (_cur_med is None or _pri_med is None)
                                 else _cur_med - _pri_med),
        "delta_p95_seconds": (None if (_cur_p95 is None or _pri_p95 is None)
                              else _cur_p95 - _pri_p95),
    },
    "dedup": {
        # Phase 1 open-issue dedup — event-based (one count per suppression
        # decision). Not folded into auto_resolve numerator because the parent
        # incident IS the active work; dedup just avoids spawning a redundant
        # Tier 2 session. Event-based on purpose: each dedup decision is a unit
        # of work-avoided, distinct from the count of incidents that ended up
        # deduped at least once (which is in breakdown_7d_by_incident.dedup).
        "current_count": _cur_ev_d,
        "prior_count": _pri_ev_d,
        "delta": _cur_ev_d - _pri_ev_d,
    },
    "breakdown_7d": _breakdown_7d,           # per-outcome counts in the current 7d window
}

result = {
    "updated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "models": model_list,
    "totals": {
        "since": since_str,
        "sessions": total_sessions,
        "turns": total_turns,
        "tokens": total_tokens,
        "requests": total_reqs,
        "avg_confidence": avg_conf,
        "devices_monitored": devices_monitored,
        "knowledge_entries": knowledge_entries,
        "a2a_escalations": a2a_escalated,
        "a2a_reviews": a2a_reviews,
        "alerts_auto_resolved": triage_resolved,
        "alerts_escalated": triage_escalated,
        "alerts_deduplicated": triage_dedup,
    },
    "operational_depth": {
        "tool_calls_total": tool_calls_total,
        "tool_unique_types": tool_unique,
        "tool_error_rate": tool_error_rate,
        "tool_latency_p50_ms": int(tool_p50_ms),
        "tool_latency_p95_ms": int(tool_p95_ms),
        "infra_commands": exec_total,
        "infra_devices_reached": exec_devices,
        "infra_command_failures": exec_failures,
        "otel_spans": otel_spans,
        "otel_traces": otel_traces,
        "top_tools": top_tools,
    },
    "quality": {
        "sessions_judged": sessions_judged,
        "judge_avg_score": judge_avg_score,
        "trajectories_scored": trajectories_scored,
        "avg_trajectory_score": int(avg_trajectory),
        "graph_entities": graph_entities,
        "graph_relationships": graph_relationships,
        "transcript_chunks": transcript_chunks,
        "diary_entries": diary_entries,
        "diary_agents": diary_agents,
    },
    "security": {
        "credentials_tracked": credentials_tracked,
        "crowdsec_scenarios": crowdsec_scenarios,
        "crowdsec_auto_suppressed": crowdsec_suppressed,
    },
    "platform": {
        "workflows": workflow_count,
        "workflows_n8n": workflows_n8n,
        "workflow_nodes": total_nodes,
        "scripts": scripts_count,
        "grafana_dashboards": grafana_dashboards,
        "grafana_custom_panels": grafana_custom_panels,
        "sqlite_tables": sqlite_tables,
        "sqlite_total_rows": sqlite_total_rows,
    },
    "governance": _governance,
    "infragraph": _infragraph,
    "benchmark": {
        # Anthropic/OpenAI agent-engineering rubric; N of M dimensions at grade A.
        # Static benchmark result — bump here (single source of truth) on re-benchmark.
        "agent_guide_dims_at_a": 12,
        "agent_guide_dims_total": 14,
        "aggregate_grade": "A+",
    },
    "time_series": time_series,
    "outcomes": outcomes,
}

print(json.dumps(result))
db.close()
