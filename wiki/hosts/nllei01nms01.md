# nl-nms01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- - **Monitoring**: Prometheus → Thanos (cross-site) → Grafana. Logs via syslog-ng → Loki. LibreNMS at nl-nms01 (API).
- | nl-nms01 | LibreNMS monitoring | `ssh nl-nms01` |
- "https://nl-nms01.example.net/api/v0/devices/<hostname-or-ip>?fields=hostname,sysName,os,type,hardware,status" | jq '.devices[0]'
- "https://nl-nms01.example.net/api/v0/alerts?state=1" | jq '.alerts[] | select(.hostname=="<hostname>") | .id'
- "https://nl-nms01.example.net/api/v0/alerts/<alert_id>"

**nl:network/CLAUDE.md**
- - Trap hosts: 10.0.181.X (nl-nms01), 10.0.181.X

**gateway:CLAUDE.md**
- - **LibreNMS (NL):** https://nl-nms01.example.net (API key in .env, self-signed cert)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-21 | Service up/down | recurred 7x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **When operator asks for "API", confirm API surface first — don't dive into source/DB until gap is proven** (feedback): When the operator says "use the API", the FIRST move is to GET the API root listing and grep for the relevant route. If the documented route exists, use it. If it doesn't, surface the gap to the operator and offer alternatives. Don't preemptively dive into source code, DB schema, or CLI tools until you've confirmed the REST surface can't do it.
- **LibreNMS port-utilisation alarm false-fires on asymmetric DSL/VDSL2** (feedback): On asymmetric DSL lines, Cisco IOS-XE sets BW = min(DS_sync, US_sync); LibreNMS pulls that into ifSpeed; rule 6 then false-fires whenever real traffic exceeds 90% of the LOWER sync rate.
- **LibreNMS REST API exposes no ifSpeed override endpoint** (feedback): The documented LibreNMS REST API has no PATCH/POST route for overriding port ifSpeed. Only update_port_description and update_device_port_notes are writable on ports. To override ifSpeed programmatically, use the WebUI ajax_form.php form, lnms CLI on the LibreNMS host, or direct DB write — not /api/v0/...
- **feedback_librenms_env_var_naming_variants** (feedback): "claude-gateway .env has 6 LibreNMS-related vars with overlapping names — use LIBRENMS_GR_API_KEY (GR) and LIBRENMS_API_KEY (NL). Stop guessing _TOKEN."
- **feedback_librenms_poller_stall_signature** (feedback): "Mass-flap pattern (broad ICMP wave + synchronized recovery + NO device-side eventlog) = LibreNMS poller-side stall, not real outage. Don't trigger device-side runbooks before checking the poller."
- **PVE-clone leaves snmpd.conf sysName pinned to the source host** (feedback): When a Proxmox node is cloned from another, /etc/snmp/snmpd.conf retains the source's sysName, blocking LibreNMS device add with "duplicate sysName"
- **freeipa01-httpd-scoreboard-outage-20260529** (project): "2026-05-29. nlfreeipa01 webui unreachable for 5d — httpd mpm_event scoreboard full since Sun May 24 00:00:11. Fixed short-term by LXC reboot. Two reusable findings — IPA host missing from LibreNMS (silent), chronic MPM tuning gap."
- **gpu01-nvml-stale-handles-20260514** (project): "nl-gpu01 CPU hammer (load 18-19, ollama 1277% CPU for 10h) — container's bind-mounted /dev/nvidia* nodes went stale after nvidia-persistenced restart at 07:01:54 CEST cycled the host device nodes. Different failure mode from 2026-05-13 (VRAM shortage). Fix: `docker restart ollama`. Hardening pending."
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **LibreNMS cororings threshold + nlpve04 onboarding 2026-05-10** (project): Bumped 5 cororings services from --rings 5 to 6 on NL+GR LibreNMS after nlpve04 onboarding. Also added nlpve04 itself as NL device 155 + cororings svc 40. snmpd-clone trap caught mid-flight.
- **nlrtr01 budget VDSL port-utilisation alarm during 2026-05-09 Freedom outage** (project): Diagnosed direction-mismatch artefact on Et0/1/0.6 (LibreNMS port_id 123127). Real DS sync 111 Mbps / US sync 33 Mbps; Cisco BW = 33 Mbps; LibreNMS ifSpeed = 33,000,000 → rule 6 false-fires. Operator chose Option A — override ifSpeed to 111,000,000.
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).
- **nl-pve03 capacity pressure (2026-04-22)** (project): nl-pve03 mirrors pre-remediation nl-pve01 pattern — no swap/zram, sustained 92%+ memory, hosts K8s ctrlr+NMS+GPU inference. Apply same zram fix; OOM blast radius is the K8s control-plane share + LibreNMS + Ollama inference simultaneously.

*Compiled: 2026-07-03 04:30 UTC*