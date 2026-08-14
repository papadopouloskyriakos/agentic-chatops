---
name: healthchecks_langfuse_access_20260626
description: "STANDING access for the orchestrator brick-growth services — Healthchecks.io (ping-based never-ran detection) + Langfuse v2 (LLM/agent trace observability), both self-hosted Docker on nlopenobserve01. Operator-approved 2026-06-26."
metadata: 
  node_type: memory
  type: reference
  originSessionId: 446fe240-f009-4fd5-a87c-b8ecb446a101
---

**Both deployed 2026-06-26 (operator-approved orchestrator -1421 brick-growth) as Docker on the OpenObserve LXC** (nlopenobserve01 = 10.0.181.X, LXC VMID_REDACTED on nl-pve03; disk resized 10G→30G for headroom). SSH: `ssh -i ~/.ssh/one_key root@10.0.181.X`. Creds for both in the gitignored **.env**.

## Healthchecks.io (Brick 1 — catches "job never ran", which Prometheus absent() can miss)
- **http://10.0.181.X:8000** · `/opt/healthchecks/docker-compose.yml` (image healthchecks/healthchecks, SQLite at volume hc-data). `.env`: `HEALTHCHECKS_URL/USER(chatops@mail.example.net)/PASSWORD`.
- **GOTCHA: the image does NOT auto-create a superuser/project from SUPERUSER_* env here** — I created them via the Django ORM: `docker exec healthchecks python manage.py shell -c "<py>"`. User = chatops@mail.example.net; Project "gateway" (owner=that user). A Check needs a project (NOT NULL project_id) which needs an owner User — create the user FIRST.
- **Integration pattern**: create a `kind='cron'` Check (ORM: `Check.objects.get_or_create(name=..., project=p, defaults={'kind':'cron','schedule':'<cron>','grace':timedelta(seconds=N),'tz':'UTC'})`), ping URL = `http://10.0.181.X:8000/ping/<check.code>`, then append `&& curl -fsS -m 10 '<ping_url>'` to the cron line. **LIVE: the registry-check */30 cron pings check `gateway-registry-check`** (the who-watches-the-watcher; status went `up`). ROLLOUT: wire the other critical crons (holistic-agentic-health, gateway-watchdog) the same way.

## Langfuse v2 (Brick 2 — LLM/agent trace observability: sessions, model, cost, generations)
- **http://10.0.181.X:3000** · `/opt/langfuse/docker-compose.yml` (image langfuse/langfuse:**2** = Postgres-only; v3 needs ClickHouse+Redis = too heavy for this 8G LXC). Postgres in volume lf-pgdata. `.env`: `LANGFUSE_HOST/PUBLIC_KEY(pk-lf-…)/SECRET_KEY(sk-lf-…)/USER`. org=nl, project=chatops-gateway.
- Provisioned via `LANGFUSE_INIT_*` env (USER_EMAIL/PASSWORD + PROJECT_PUBLIC_KEY/SECRET_KEY — generate proper uuids: `uuidgen` is ABSENT on the host, use `python3 -c 'import uuid;print(uuid.uuid4())'`). Wipe+reinit (`docker compose down -v && up`) is safe while empty.
- **Ingestion**: `POST /api/public/ingestion` (HTTP Basic pk:sk) with a `{"batch":[{type:trace-create,...},{type:generation-create,...}]}` → **207** = accepted. **LIVE: scripts/lib/langfuse_export.py::send_session() wired into reconcile-completed-sessions.py _post_archive_side_effects** → every completed session becomes a trace (best-effort, never blocks). Proven: a real $2.17 claude-opus-4-8 session (IFRNLLEI01PRD-1403) landed.

Quick checks: HC `curl -s -o /dev/null -w '%{http_code}' http://10.0.181.X:8000/` →302; LF `curl -s http://10.0.181.X:3000/api/public/health` →200. [[orchestrator_control_plane_20260626]] [[openobserve_access_20260626]] [[feedback_use_api_not_direct_db]]