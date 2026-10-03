---
name: openobserve_access_20260626
description: "STANDING access + OTLP trace-export setup for OpenObserve (nlopenobserve01) — the gateway's distributed-tracing sink. Admin creds in .env; the OTLP auth + 5h ingest-window gotchas."
metadata: 
  node_type: memory
  type: reference
  originSessionId: 446fe240-f009-4fd5-a87c-b8ecb446a101
---

**OpenObserve = the gateway's distributed-tracing sink** (the observability dimension's OTLP backend). Host **nlopenobserve01** = `10.0.181.X:5080`, LXC VMID_REDACTED on nl-pve03, runs as Docker container `openobserve` (+ watchtower). UI/API at http://10.0.181.X:5080.

**ACCESS (never ask operator again):** the only user is **admin@example.com** (role=root). The password lives in the container env (`docker inspect openobserve` → `ZO_ROOT_USER_EMAIL`/`ZO_ROOT_USER_PASSWORD`) and in the gateway **.env** as `OPENOBSERVE_USER`/`OPENOBSERVE_TOKEN` (operator-provided 2026-06-26). SSH to the host: `ssh -i ~/.ssh/one_key root@10.0.181.X`. API auth = HTTP Basic `base64(email:password)`. Org = `default`. OTLP traces endpoint = `http://10.0.181.X:5080/api/default/v1/traces`.

**GOTCHAS (cost a long debug 2026-06-26 — see [[autonomous_benchmark_mission_20260625]]):**
- **`_resolve_otlp_auth()` in scripts/export-otel-traces.py prefers a hardcoded `OTLP_AUTH` in .env OVER `OPENOBSERVE_USER/TOKEN`.** A STALE `OTLP_AUTH` (from IFRNLLEI01PRD-1082) was 401-ing every push since ~March → all spans died. Fix = comment out `OTLP_AUTH`, let it derive from USER/TOKEN. If you rotate creds, update `OPENOBSERVE_TOKEN` AND ensure no stale `OTLP_AUTH` shadows it.
- **`ZO_INGEST_ALLOWED_UPTO` default ~5 HOURS** — OpenObserve rejects spans whose timestamp is older than ~5h with **HTTP 206** `{"partialSuccess":{"rejectedSpans":N,"errorMessage":"exceeding the allowed retention period"}}`. So you can NOT backfill historical spans; only fresh ones ingest. The gateway exports spans on session-end via the `*/5` cron, minutes old, well within the window. `export-otel-traces.py` now has a **retention pre-filter** (spans >4h → marked state 2 expired, not retried) so the un-exportable tail stops churning.
- `otel_spans.exported_to_otlp`: **0=pending, 1=exported, 2=expired/skip**. The `--export` flush pushes state-0 only. `submit_otlp` treats anything not 200/204 (incl. 206) as failure.
- OSS OpenObserve allows only standard roles (admin/root/editor/user/viewer) — `member`/custom roles → 400 "Custom roles not allowed". Password policy: 8-128 chars, ≥1 each upper/lower/digit/special.
- Verify a push: `curl -X POST .../api/default/v1/traces -H "Authorization: Basic <b64>" -d '{"resourceSpans":[]}'` → expect 200 `{"partialSuccess":null}`.

Quick auth test: `curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Basic $(printf '%s' "$OPENOBSERVE_USER:$OPENOBSERVE_TOKEN" | base64 -w0)" http://10.0.181.X:5080/api/default/streams` → 200. [[feedback_use_api_not_direct_db]] [[feedback_verify_belief_not_rationalize_observation]]