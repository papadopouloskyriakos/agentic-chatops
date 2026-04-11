#!/usr/bin/env python3
"""Generate agentic stats JSON for portfolio widget."""
import json
import sqlite3
import datetime
import urllib.request
import ssl

DB = "/app/cubeos/claude-context/gateway.db"
TRIAGE_LOG = "/app/cubeos/claude-context/triage.log"
NETBOX_URL = "https://netbox.example.net"
NETBOX_TOKEN = "REDACTED_4bd0c65f"

ROLE_MAP = {
    "claude-opus-4-6": "Investigation",
    "claude-sonnet-4-6": "Investigation",
    "claude-haiku-4-5": "Quality Judge",
    "gpt-5.1": "Triage",
    "gpt-4o": "Triage",
    "gpt-4o-mini": "Triage Fallback",
    "nomic-embed-text": "RAG Embeddings",
    "qwen3": "Query Rewriting",
}
NAME_MAP = {
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
    "qwen3:4b": "Qwen3 4B",
}

db = sqlite3.connect(DB)
models = {}

# Source 1: llm_usage — the single source of truth for all token data
# All tiers (0=local GPU, 1=OpenAI, 2=Claude) are tracked here
# NOTE: Claude poller rows (issue_id='') have inflated cache_read/cache_write
# from cumulative stats-cache.json values. For those rows, use input+output only.
# Runner rows (have issue_id) and non-Claude poller rows have correct cache values.
for tier, model, reqs, tokens in db.execute(
    """SELECT tier, model, COUNT(*),
       SUM(CASE
         WHEN issue_id != '' THEN input_tokens + output_tokens
           + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)
         WHEN model NOT LIKE 'claude-%' THEN input_tokens + output_tokens
           + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)
         ELSE input_tokens + output_tokens
       END)
       FROM llm_usage WHERE model != '' AND model IS NOT NULL GROUP BY tier, model"""
).fetchall():
    models[model] = {"tier": tier, "requests": reqs, "tokens": tokens or 0, "sessions": 0}

# Source 2: sessions + session_log — session counts only (no token estimation)
for model, sessions in db.execute(
    """SELECT model, COUNT(*) FROM (
         SELECT model FROM sessions WHERE model != ''
         UNION ALL
         SELECT model FROM session_log WHERE model != ''
       ) GROUP BY model"""
).fetchall():
    if model in models:
        models[model]["sessions"] += sessions
        if models[model]["requests"] < sessions:
            models[model]["requests"] = sessions
    else:
        # Session exists but no llm_usage data — record session count only, no token guessing
        models[model] = {
            "tier": 2,
            "requests": sessions,
            "tokens": 0,
            "sessions": sessions,
        }

# Build model list (merge entries that map to the same display name)
merged = {}
for model, data in models.items():
    display = NAME_MAP.get(model, model)
    role = next((v for k, v in ROLE_MAP.items() if k in model), "General")
    tier_label = "Local GPU" if data["tier"] == 0 else f"Tier {data['tier']}"
    if display in merged:
        merged[display]["requests"] += data["requests"]
        merged[display]["tokens"] += data["tokens"]
    else:
        merged[display] = {
            "model": display, "tier": tier_label, "role": role,
            "requests": data["requests"], "tokens": data["tokens"],
        }
model_list = sorted(merged.values(), key=lambda x: x["tokens"], reverse=True)

# Totals
total_sessions = db.execute(
    "SELECT (SELECT COUNT(*) FROM sessions) + (SELECT COUNT(*) FROM session_log)"
).fetchone()[0]
total_turns = db.execute("SELECT COALESCE(SUM(num_turns),0) FROM sessions").fetchone()[0]
total_turns += db.execute("SELECT COALESCE(SUM(num_turns),0) FROM session_log").fetchone()[0]
total_tokens = sum(m["tokens"] for m in model_list)
total_reqs = sum(m["requests"] for m in model_list)
avg_conf = db.execute(
    "SELECT ROUND(AVG(confidence),2) FROM sessions WHERE confidence >= 0"
).fetchone()[0] or 0
knowledge_entries = db.execute("SELECT COUNT(*) FROM incident_knowledge").fetchone()[0]

# NetBox device count (live)
devices_monitored = 310  # fallback
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

# Triage log stats
triage_resolved = 0
triage_escalated = 0
try:
    with open(TRIAGE_LOG) as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 5:
                if parts[4] == "resolved":
                    triage_resolved += 1
                elif parts[4] == "escalated":
                    triage_escalated += 1
except FileNotFoundError:
    pass

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
# Source A: llm_usage — real token counts per day (same cache fix as main query)
for day, model_raw, reqs, tokens in db.execute(
    """SELECT DATE(recorded_at) AS day, model, COUNT(*),
       SUM(CASE
         WHEN issue_id != '' THEN input_tokens + output_tokens
           + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)
         WHEN model NOT LIKE 'claude-%' THEN input_tokens + output_tokens
           + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)
         ELSE input_tokens + output_tokens
       END)
       FROM llm_usage
       WHERE model != '' AND model IS NOT NULL
         AND recorded_at >= DATE('now', '-6 days')
       GROUP BY day, model"""
).fetchall():
    bucket = time_series_raw.setdefault(day, {})
    name = NAME_MAP.get(model_raw, model_raw)
    if name in bucket:
        bucket[name]["tokens"] += tokens
        bucket[name]["requests"] += reqs
    else:
        bucket[name] = {"tokens": tokens, "requests": reqs}

# No estimation sources — time_series uses only real llm_usage data

# Build the 7-day window and fill gaps
today = datetime.date.today()
target_days = [(today - datetime.timedelta(days=6 - i)).isoformat() for i in range(7)]
for day_str in target_days:
    time_series_raw.setdefault(day_str, {})

# Build sorted time_series array (only target days)
time_series = []
for day in target_days:
    bucket = time_series_raw.get(day, {})
    day_models = []
    for mname, mdata in sorted(bucket.items(), key=lambda x: x[1]["tokens"], reverse=True):
        day_models.append({"model": mname, "tokens": mdata["tokens"], "requests": mdata["requests"]})
    time_series.append({
        "date": day,
        "tokens": sum(m["tokens"] for m in day_models),
        "requests": sum(m["requests"] for m in day_models),
        "models": day_models,
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

# === NEW: Platform inventory ===
workflow_count = 25  # verified live
total_nodes = 475
scripts_count = 70  # 48 bash + 18 python + hooks
grafana_dashboards = 43  # 9 custom + 34 kube-prometheus defaults
grafana_custom_panels = 127  # 19+18+20+7 custom subsystem + 63 existing
sqlite_tables = 21
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
        "workflow_nodes": total_nodes,
        "scripts": scripts_count,
        "grafana_dashboards": grafana_dashboards,
        "grafana_custom_panels": grafana_custom_panels,
        "sqlite_tables": sqlite_tables,
        "sqlite_total_rows": sqlite_total_rows,
    },
    "time_series": time_series,
}

print(json.dumps(result))
db.close()
