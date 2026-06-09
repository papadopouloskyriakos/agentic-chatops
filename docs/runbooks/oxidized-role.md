# Oxidized — role, scope, and divergence from IaC

Last updated: 2026-04-22 (IFRNLLEI01PRD-701)

## Current policy

**Oxidized runs on both sites as an independent config-backup tier.**
It is **not** part of the GitLab IaC flow. The GitLab CI
`auto_detect_and_sync_drift` job (netmiko-direct SSH, runs every 30
minutes on both NL and GR) is the single source of truth for git state.

## What Oxidized does today

- `nloxidized01` (LXC VMID_REDACTED) + `groxidized02` (LXC 201020802)
- Runs as root (`/usr/local/bin/oxidized`), config at `/root/.config/oxidized/config`
- Source list: `/root/.config/oxidized/router.db` (csv — device:ip:model:group)
- Output: one bare git repo per device-type under `/root/.config/oxidized/`
  (e.g. `Firewall.git`, `FRR-LXC.git`, `Access-Point.git`, `Switch.git`, …)
- Refresh cadence: Oxidized's internal scheduler fetches each device, commits
  the new `show run` into the type-specific repo only when content changed
- **Local-only.** No remote. No push.

Evidence it's working (2026-04-22):
- NL `Firewall.git` mtime `Apr 22 19:05` (captured rtr01 + fw01 changes from today)
- GR `Firewall.git` mtime `Apr 22 18:53` + matching syslog "Configuration
  updated for Firewall/gr-fw01" entries on `17:52:43` and `18:53:33`.

## What changed 2025-11-23

A separate shell script `/root/.config/oxidized/sync_oxidized_gitlab.sh`
(v2.0, ~10 KB, last touched 2025-11-21) used to push these local git
repos up to a central GitLab repo (`infrastructure/nl/oxidized`)
every 5 minutes via cron.

On 2025-11-23 someone commented out the cron on both hosts on the same day
(file mtimes: NL 13:39 CET, GR 13:44 CET). The push-target repo
`infrastructure/nl/oxidized` no longer exists on GitLab (404).

So the cron was stopped, the central repo was deleted, and Oxidized fell
off the GitOps story — but it never stopped being a functional backup tier
on its own filesystem.

## Why keep it

Layered defence:

1. **Live device** — source of truth.
2. **GitLab CI `auto_detect_and_sync_drift`** — captures drift every 30
   min, pushes to main. Subject to the layer-1 whitelist guardrail
   ([IFRNLLEI01PRD-699]). This is the IaC-relevant tier.
3. **Oxidized local git** — silent independent capture, no network
   dependency on GitLab, no credential-rot dependency on CI. If both
   the GitLab instance and the netmiko-CI-runner burn to the ground,
   Oxidized still has the last-known-good snapshot accessible via
   direct SSH to the oxidized LXC.

These layers fail independently. Keeping Oxidized is cheap (~56 MB RAM
per host) and the backup has demonstrated freshness.

## Policy invariants

- **Do NOT re-enable `sync_oxidized_gitlab.sh`.** The GitLab CI drift-sync
  is the gitops path; mixing would produce conflicting commits.
- **Do NOT recreate the `infrastructure/nl/oxidized` repo.** Same
  reason.
- **Do NOT treat Oxidized git as authoritative.** If it disagrees with the
  live device, the live device wins. Oxidized is a backup, not ground
  truth. Same with GitLab: GitLab is the IaC record; the device overrides.
- The `NL/GR Oxidized Bot` author-filters in `ci/cisco.yml` have been
  removed (NL MR !268, GR !62) — they were specifically for commits that
  Oxidized would push to GitLab, which is no longer the path.

## If Oxidized stops being useful

Re-evaluate at the 90-day mark (2026-07-20). Triggers for re-evaluation:

- Either LXC crashes or becomes a maintenance burden
- Oxidized upstream releases a breaking change
- GitLab CI drift-sync proves sufficiently reliable that the backup tier
  is unneeded (unlikely — we want both)

In that case: stop the service, archive the per-type git repos off-host,
retire the LXCs.

## Access for auditors / operators

To retrieve the last-known-good config for a device when GitLab is down:

```bash
# NL devices
ssh -i ~/.ssh/one_key root@nloxidized01 \
  "cd /root/.config/oxidized/Firewall.git && git log --oneline -5"

# Example: show the current backup of nl-fw01
ssh -i ~/.ssh/one_key root@nloxidized01 \
  "cd /root/.config/oxidized/Firewall.git && git show HEAD:nl-fw01"

# GR devices (same pattern, different host)
ssh -i ~/.ssh/one_key root@groxidized02 \
  "cd /root/.config/oxidized/Firewall.git && git show HEAD:gr-fw01"
```

## Changelog

- 2025-11-23 — cron `sync_oxidized_gitlab.sh` disabled on both hosts;
  central push repo deleted.
- 2026-04-22 — IFRNLLEI01PRD-701: initial proposal to decommission;
  investigation showed Oxidized is a healthy backup tier; decision revised
  to **keep as decoupled backup**. This runbook codifies that role.
  CI author-filters for Oxidized-bot commits removed (dead path).
