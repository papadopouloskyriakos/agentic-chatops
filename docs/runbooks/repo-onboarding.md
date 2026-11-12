# Runbook: onboard a new product repo into the ChatDevOps gateway

**Audience:** operator adding a NEW product/repo to the agentic-platform dispatch (e.g., when a new product project is created in GitLab and needs YouTrack-driven Claude sessions).

**Prerequisite:** the `IFRNLLEI01PRD-910` state-refactor cutover MUST be live (verify `/home/app-user/gateway-state/slot-config.json` exists). If not, this runbook does not apply — the old method of editing 12+ hardcoded paths in the Runner is required.

**Total time:** ~10 minutes per new repo.

---

## Step-by-step

### 1. Verify the repo exists on disk

```bash
# Replace <slug> with your new product slug (e.g. "newapp")
ls -d /app/products/<slug>
```

If missing, clone it first:

```bash
cd /app/products/
git clone git@gitlab.example.net:products/<slug>.git
```

### 2. Pick a YouTrack project prefix

By convention, ChatDevOps product issues use uppercase prefixes:

| Product | YouTrack prefix |
|---|---|
| CubeOS | `CUBEOS` |
| MeshSat | `MESHSAT` |
| Your new product | `NEWAPP` (choose) |

Create the YouTrack project (or reuse an existing one) and confirm the shortName matches your prefix.

### 3. Decide the Matrix room

Create a Matrix room (or reuse an existing one) and invite `@claude:matrix.example.net`. Capture the room ID (e.g. `!XXXXXXXX:matrix.example.net`).

### 4. Update `slot-config.json`

```bash
SLUG=newapp
PREFIX=NEWAPP
CWD=/app/products/newapp
ROOM='!YOURROOMID:matrix.example.net'

# Edit the slot-config.json — add the new slot before the "default" entry
vim /home/app-user/gateway-state/slot-config.json
```

Add:

```json
"newapp": {"cwd": "/app/products/newapp", "room": "!YOURROOMID:matrix.example.net"},
```

### 5. Update the n8n Derive Slot nodes

`slot-config.json` is the canonical config, but Derive Slot's JS in the Runner + Matrix Bridge workflows has the dict mirrored inline (n8n Code-node sandbox can't read fs, so the dict must be inline for runtime). Update BOTH:

- Runner workflow `qadF2WcaBsIR7SWG` — Derive Slot node
- Matrix Bridge workflow `QGKnHGkw4casiWIU` — Derive Slot node

Add the slot's prefix detection + dict entry (mirror exactly what's in slot-config.json). Use the `n8n-code-node-safety.md` runbook for the edit.

```js
// Inside the slotConfig dict:
'newapp':  { cwd: '/app/products/newapp',  room: '!YOURROOMID:matrix.example.net' },

// And in the slot-derivation if/else:
: (prefix === 'NEWAPP') ? 'newapp'
```

### 6. Validate

```bash
# Check resolve-slot.sh sees the new slot
/home/app-user/gateway-state/bin/resolve-slot.sh newapp cwd
# Expected: /app/products/newapp

/home/app-user/gateway-state/bin/resolve-slot.sh newapp room
# Expected: !YOURROOMID:matrix.example.net
```

### 7. Smoke-test with a YouTrack issue

Create a trivial NEWAPP-* test issue in YouTrack (e.g. "smoke test"). Watch:

- The YouTrack webhook fires the Receiver
- Receiver fires the Runner
- Runner's Derive Slot emits `slot=newapp, cwd=/home/.../newapp, room=!YOURROOMID`
- `Launch Claude` cd's into the newapp cwd
- Lock file appears at `/home/app-user/gateway-state/gateway.lock.newapp`
- Matrix message lands in the configured room

If all 6 work, you're done. Close the smoke-test issue.

### 8. Document the new slot

Add the new slot to `.claude/rules/references.md` Matrix Rooms table + CLAUDE.md if it's a permanently-tracked product.

---

## Rollback (if smoke-test fails)

1. Remove the slot from `slot-config.json`
2. Revert the Derive Slot edits in both workflows (use `n8n-code-node-safety.md` per-node procedure)
3. The repo on disk stays — that's not a refactor concern

---

## Why this is now 10 min instead of 1+ hour

Pre-refactor (before IFRNLLEI01PRD-910 cutover), adding a new repo required editing 12+ hardcoded `cubeos` references across:
- Runner workflow's `case "$PREFIX"` cwd dispatch
- Runner's `Build Prompt` projectPath if/else
- Matrix Bridge's 22 SSH nodes
- Session End's lockfile case statement
- ... and a Derive Slot ENUM in two places

Post-refactor: 1 entry in `slot-config.json` + 2 mirrored entries in the Derive Slot dicts + Matrix room + YouTrack project.

The "2 mirrored entries" is the only non-1-line cost. It exists because n8n Code-node sandbox blocks `fs.readFileSync`. A future enhancement could move slot-config loading to an upstream SSH node that cats it + emits the dict downstream — eliminating the dual-update requirement.
