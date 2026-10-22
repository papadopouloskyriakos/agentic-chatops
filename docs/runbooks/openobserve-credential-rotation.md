# OpenObserve credential rotation (IFRNLLEI01PRD-1082)

## Status
- **De-hardcode: DONE (2026-06-16).** The OTLP ingest secret is no longer in source
  (`scripts/export-otel-traces.py` reads `OTLP_AUTH` from the gitignored `.env`).
  Verified: ingest returns 200; `grep admin@example.com export-otel-traces.py` = 0.
- **Rotation: operator-coordinated (NOT auto-rotated).** See why + how below.

## Why rotation was not auto-performed
`admin@example.com` (role **root**) is the **only** OpenObserve user, and OpenObserve
OSS **refuses to create additional root users via the API** (`POST /api/default/users`
→ `400 Not allowed`, confirmed 2026-06-16). So there is **no recovery path** if a
sole-root password change misbehaves — a botched rotation locks all UI/admin access
with no second admin to recover, recoverable only by editing the container env and
restarting OpenObserve. Doing that blind on a live observability system (especially
during an incident) is an unrecoverable-lockout risk, so rotation is handed to the
operator who can confirm UI access and edit the container env.

The leaked value is in git history + the public GitHub mirror, so rotation still
matters: `admin@example.com:kradGaPKMeR8xkeNXd2KWVGxerx5kfL4`.

## Rotation procedure (operator, ~3 min, zero ingest downtime)
1. **Pick a new strong password**, e.g. `openssl rand -base64 24`.
2. **Set it** the safe way — via the OpenObserve container env (survives restart):
   on the OpenObserve host (nlopenobserve01, LXC VMID_REDACTED on nl-pve03) set
   `ZO_ROOT_USER_PASSWORD=<new>` in the compose/env and `docker compose up -d`
   (root password is re-applied from env on boot). Confirm UI login with the new
   password BEFORE step 3.
3. **Update ingest auth** on nl-claude01:
   ```
   NEW=$(printf 'admin@example.com:<new>' | base64 -w0)
   sed -i "s|^OTLP_AUTH=.*|OTLP_AUTH=Basic $NEW|" ~/gitlab/n8n/claude-gateway/.env
   ```
4. **Verify ingest** still 200:
   ```
   python3 - <<'PY'
   import importlib.util; s=importlib.util.spec_from_file_location("e","scripts/export-otel-traces.py")
   m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
   import urllib.request
   r=urllib.request.Request(m.OTLP_ENDPOINT, b'{"resourceSpans":[]}', {"Authorization":m.OTLP_AUTH,"Content-Type":"application/json"}, method="POST")
   print(urllib.request.urlopen(r,timeout=8).status)
   PY
   ```
5. Optionally invalidate the old value's exposure note in the gap-analysis.

Once rotated, the new secret lives only in `.env` (gitignored) — the de-hardcode
ensures it never re-enters source/the public mirror.
