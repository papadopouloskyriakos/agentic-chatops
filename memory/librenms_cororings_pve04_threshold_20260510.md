---
name: LibreNMS cororings threshold + pve04 onboarding 2026-05-10
description: Bumped 5 cororings services from --rings 5 to 6 on NL+GR LibreNMS after pve04 onboarding. Also added pve04 itself as NL device 155 + cororings svc 40. snmpd-clone trap caught mid-flight.
type: project
originSessionId: bc4ef08e-03a1-4ff5-a229-bd5c6a7b14ed
---
## Trigger
2026-05-09 nlpve04 onboarded as 6th member of NL+GR PVE cluster. From 2026-05-10, both LibreNMS instances were firing 5 CRITICAL alerts: `check_cororings CRITICAL - Expected 5 connected nodes but found 6` (NL svc 9/10/16, GR svc 12/13).

## Root cause
LibreNMS `check_cororings` Nagios plugin at `/usr/lib/nagios/plugins/check_cororings` SSHes to the target PVE node, parses `corosync-cfgtool -s`, counts `nodeid: N: (connected|localhost)` lines, and asserts the count == `--rings N`. The `--rings` flag name is misleading — it's the expected cluster member count, not network ring count. Every PVE node has its own service with `--rings` hard-coded; **adding a node breaks every service**.

The alert itself fires under LibreNMS rule_id=9 "Service up/down" (`services.service_status != 0`). No rule edit needed — fix is in the per-service `service_param`.

## Decisions
1. **Bump --rings 5→6** on all 5 existing services (NL: 9, 10, 16; GR: 12, 13). User confirmed they want to keep the hard-coded pattern because it catches silent cluster-size drift; the cost is N service PATCHes on every cluster size change.
2. **Add pve04 as NL LibreNMS device** + cororings service for symmetry with pve01/02/03 (3 NL vantage points → 4). User explicitly approved.
3. **Skipped** changing to a size-agnostic check (dropping `--rings` flag, or writing a new `pvecm status`-based plugin) — operator chose the change-detection value.

## Commands run / results

```bash
# 1. Identified source: 5 services with type=cororings, --rings 5
curl -sk -H "X-Auth-Token: $KEY" "$URL/api/v0/services" \
  → svc_id={9,10,16} NL pve01/02/03 status=2 CRITICAL
  → svc_id={12,13} GR gr-pve01/02 status=2 CRITICAL

# 2. Bumped threshold (5 PATCHes)
PATCH /api/v0/services/{id} {"service_param":"check_cororings --host <host> --rings 6"}
  → all 5 returned {"status":"ok","message":"Service updated successfully"}

# 3. Forced re-poll on both nms hosts
ssh root@nl-nms01 'sudo -u librenms /opt/librenms/check-services.php'
ssh root@gr-nms01 'sudo -u librenms /opt/librenms/check-services.php'
ssh root@nl-nms01 'sudo -u librenms /opt/librenms/alerts.php'
  → all 5 services flipped to status=0 OK
  → alerts.php issued recovery transitions (state=0)

# 4. Added pve04 device — FIRST attempt rejected:
POST /api/v0/devices {"hostname":"nlpve04",...}
  → {"status":"error","message":"Already have device nlpve04 due to duplicate sysName: nl-pve02"}

# 5. Found cause: /etc/snmp/snmpd.conf on pve04 had `sysName nl-pve02`
#    (clone artifact from pve02 — corosync identity wipe didn't touch snmpd)
ssh root@nlpve04 "sed -i 's/^sysName nl-pve02$/sysName nlpve04/' /etc/snmp/snmpd.conf && systemctl restart snmpd"

# 6. Re-tried device add — succeeded
POST /api/v0/devices → device_id=155, sysName=nlpve04, os=proxmox

# 7. Added cororings service for pve04
POST /api/v0/services/nlpve04 {"type":"cororings","ip":"nlpve04","param":"check_cororings --host nlpve04 --rings 6","name":"Check the current corosync links"}
  → svc_id=40

# 8. Final re-poll → svc 40 status=0 OK, all 6 nodes connected
```

## Findings
- **No IaC manages LibreNMS services.** `find /app -name 'librenms'` returned nothing under `infrastructure/`. All changes are via the REST API. **Future cluster changes must mirror this — no Ansible/Atlantis pipeline will catch them.**
- **NL services as of 2026-05-10 EOD:**
  - svc_id 10 → nl-pve01 (--rings 6)
  - svc_id 9  → nl-pve02 (--rings 6)
  - svc_id 16 → nl-pve03 (--rings 6)
  - svc_id 40 → nlpve04 (--rings 6, NEW today)
- **GR services:** svc 12 → gr-pve01, svc 13 → gr-pve02 (both --rings 6)
- **NL pve04 device:** device_id=155, mgmt IP 10.0.181.X/24, corosync ring0 10.0.X.X/29, NFS .88.28
- **check_cororings perl plugin uses a hardcoded root password** (`REDACTED_PASSWORD`) inside `/usr/lib/nagios/plugins/check_cororings` to SSH to each target. Not in any vault. Worth noting if root passwords are ever rotated.
- **LibreNMS edit_service API accepts any column in the `services` table** — looked at `includes/services.inc.php:34` (`edit_service` just calls `Service::query()->where('service_id', $id)->update($update)`).

## Verification
- All 6 cororings services status=0 OK
- `corosync-cfgtool -s` on nl-pve01 returns nodeids 1-6 all connected, with localhost=4 — matches actual cluster
- Rule-9 (Service up/down) active alert count: 0 on NL, 0 on GR
- `/opt/librenms/alerts.php` issued recovery transitions for the 3 NL CRITICAL alerts

## Confidence: 0.95
- 0.95 for threshold fix being durable: API PATCH took, re-poll showed OK, alerts cleared with recovery notifications fired. Verified end-to-end.
- -0.05 for non-IaC fragility: nothing pins these service params; a future LibreNMS restore-from-backup older than today would re-introduce the alert. Recovery would be the same 5-PATCH sequence.

## Open questions / follow-ups
- **None blocking.** pve04 is now fully integrated into the NL+GR cluster monitoring posture.
- **Possible future improvement** (not pursued, by operator choice): replace the per-node `--rings N` hard-code with a single self-updating plugin that reads expected_votes from corosync.conf and asserts running quorum. Filed but unactioned.
- **Hidden root password in check_cororings** — separate vuln-class issue; not addressed today.
- **Knowledge captured** in two new feedback memories:
  - `feedback_pve_clone_drags_snmpd_sysname.md` — the snmpd clone trap (parallel to corosync clone trap, but covers a DIFFERENT file)
  - `feedback_librenms_cororings_hardcoded_per_node.md` — the per-node patching procedure with current svc_id table
