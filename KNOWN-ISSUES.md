## RESOLVED: Synology DSM Webhook Configuration

**Status:** Done (2026-03-18) — DSM webhooks configured on both NAS devices

### Why
The Synology I/O latency alert (04:32 UTC, 2026-03-18) that caused 6 hours of kube-apiserver restarts was only sent via email. LibreNMS cannot detect I/O latency via SNMP — it only sees disk state (healthy/failed) and temperature. DSM generates critical alerts that have no path into the automated triage pipeline.

### What to Configure

**Webhook URL:** `https://n8n.example.net/webhook/synology-alert`

Configure on **both** NAS devices via DSM → Control Panel → Notification → Webhook:

| Device | Hostname in payload |
|--------|-------------------|
| nl-nas01 (DS1621+) | `nl-nas01` |
| nl-nas02 (DS1513+) | `nl-nas02` |

Payload template:
```json
{
  "hostname": "<HOSTNAME>",
  "event": "@@EVENT@@",
  "message": "@@MESSAGE@@",
  "severity": "@@SEVERITY@@",
  "category": "@@CATEGORY@@"
}
```

### DSM Categories to Enable (LibreNMS blind spots)

**Must enable:**
- Storage I/O latency, iSCSI LUN errors, SMART disk warnings
- Storage pool scrub errors, Snapshot replication failures, Volume degraded/crashed

**Should enable:**
- UPS on battery / low battery, Network bond degraded

### Workflow
- **ID:** `osv5EJJWGsTETw18` (7 nodes, active)
- Flow: Parse → Actionable? → Matrix → High Urgency? → OpenClaw triage
- High urgency (I/O latency, degraded, SMART, UPS, iSCSI) → auto-triage via infra-triage.sh
- Info-level → silently dropped

---

## RESOLVED: LibreNMS REST Sensors in Home Assistant 2026.3.1

**Status:** Fixed (2026-03-16)

### Root Cause
In HA 2026.3.1, `platform: rest` under `sensor:` (legacy format) is silently ignored — no errors, no warnings. The top-level `rest:` integration format is required. Previous attempts to use `rest:` failed because the conflicting `platform: rest` entries in `sensors.yaml` were still being loaded simultaneously.

### Fix Applied
1. Added `rest: !include rest.yaml` to `configuration.yaml` (line 27)
2. Cleared `sensors.yaml` of `platform: rest` entries (replaced with empty `[]`)
3. `rest.yaml` uses the modern top-level format with `resource:` + nested `sensor:` list

### Result
- All 24 REST sensors loading and returning Active/Inactive states
- Template sensors `wlan_7/8/9_combined_active` aggregating correctly
- Room occupancy automations functional

### Files Changed
- `configuration.yaml`: added `rest: !include rest.yaml`
- `sensors.yaml`: cleared (was 24 `platform: rest` entries, now empty list)
- `rest.yaml`: unchanged (already had correct modern format)
- Backups: `configuration.yaml.bak.20260316`, `sensors.yaml.bak.20260316`

### Key Lesson
HA 2026.3.x silently drops `platform: rest` sensor entries loaded via `sensor: !include`. Use the top-level `rest:` integration key with nested `sensor:` lists instead. The config check (`hass --script check_config`) does NOT flag this as an error.
