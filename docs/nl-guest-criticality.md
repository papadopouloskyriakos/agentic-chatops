# NL guest criticality map (P0 / P1 / P2)

Standing reference, first built 2026-09-17 during the nl-pve01 rpool incident and updated the same night after the P0 evacuation. Regenerate the placement column from `pvesh get /cluster/resources --type vm`; the P0/P1/P2 ratings are judgement and must be edited by hand.

## Placement AFTER the 2026-09-17/18 evacuation (authoritative as of 01:20 NL)

| Guest | Pri | Was | Now |
|---|---|---|---|
| nlfreeipa01 | P0 | pve01 | **pve03** |
| nlnpm01 | P0 | pve01 | **pve03** |
| nl-matrix01 | P0 | pve01 | **pve03** |
| nlsmtp-gpg01 | P0 | pve01 | **pve03** |
| nlsmtp-dkim01 | P0 | pve01 | **pve03** |
| nlvaultwarden01 | P0 | pve01 | **pve03** |
| nl-pihole01 | P0 | pve01 | **pve04** |
| nloas01 | P1 | pve01 | pve03 |
| nlwg01 | P1 | pve01 | pve03 |
| nlnetbox01 | P1 | pve01 | pve04 |
| nlprotonmail-bridge01 | **P0** (operator reclassified 2026-09-18) | pve01 | **pve04** (landed 01:35 NL, 15 min copy) |
| nloas02 | P1 | pve01 | pve04 |
| nlhealthops01 | P1 | pve01 | pve01 (left: 64 G copy not worth the leg risk) |
| nllitellm01 | P1 | pve03 | **pve04** (NFS rootfs, zero-copy, 01:38 UTC) |
| nlopenobserve01 | P1 | pve03 | **pve04** (30 G, 01:42 UTC) |
| perplexica01 sftpgo01 actualbudget01 whiteboard01 wallos-mylab01 imaginary01 wallos01 pulse01 nc02 | P2 | pve03 | pve01 |
| servarr01 postiz01 | P2 | pve04 | pve01 — ⚠ servarr01 runs **Lyrion/LMS** (the house speakers depend on it; they reboot-loop while it is down). It went dark with pve01 on 2026-09-18; move it off with tg01 (IFRNLLEI01PRD-2871) |
| nlfrigate01 | P2 | pve03 | **pve04** (2026-09-18 14:02 NL, 30 G in 3m53s; software decode — pve04 has no iGPU; infra MR !573) |
| nltg01 | **P0 de-facto** (was rated P2) | pve01 | pve01 — **move pending, IFRNLLEI01PRD-2868** |

**nl-pve01 now holds ZERO P0.** Its rpool runs on a single leg (`7VS00ZJ8`); the returned `7VS00YN2` is OFFLINE by choice (came back at ~1 write/s). **Both FireCuda 530s are faulty** — the survivor stalled 3× in 45 min under ≤5 MB/s of writes (self-clearing, 1-5 min) — so pve01 is a **write-fragile host until re-drived**: k8s-node01 cordoned, GitLab runner 10 paused, no inbound copies of any size (IFRNLLEI01PRD-2864).

**Stopped + `onboot=0` by the operator 2026-09-18 (not consuming RAM) — 19:** openwebui01, code02, kiwix01 (pve03) · imaginary01, emailagent01, cloudbeaver01, code01, cubeos01, mealie01, netvisor01, perplexica01, sftpgo01, pulse01, ghostfolio01 (pve01) · cap01, screenity01, semaphore01, mattermost01 (pve04; mattermost.example.net down by choice), gitlabrunner02 (pve04, since 2026-09-19). The 11 of them monitored in NL LibreNMS are `ignore=1` — set `ignore=0` if one is revived.

**2026-09-19 swap (operator):** androidsdk01 was restarted on pve04 with 8 GiB (was 4; still `onboot=0`) and gitlabrunner02 (16 GiB) was stopped in its place, so the count stays 19. Neither VM is in LibreNMS or NetBox. With runner 10 paused and runner 13 (gitlabrunner04) stopped, runner 12 (gitlabrunner03, pve03) is the only online `omoikane-runner`.

**⚠ nltg01 is de-facto P0 and still on pve01 (found 2026-09-18).** It is the territory-grounder, **primary alert intake since the 2026-08-26 master-switch graduation** (NL LibreNMS transport 7 → `nltg01:8080`). This map rated it P2 on 09-17, so it was not evacuated. Move + reclassify: IFRNLLEI01PRD-2868.

**⚠ Backups follow the node, not the guest.** NL vzdump jobs are node-pinned VMID lists, so every move above silently dropped that guest out of backups until the lists were fixed on 2026-09-18 (26 running guests; see `.claude/rules/infrastructure.md` § NL backups). **After any migration, move the VMID into the target node's job.** What the obscure ones are: `memory/nl_guest_purposes_20260918.md`.

Built 2026-09-17 at the operator's request ("sort by estate importance… maybe migrate the
crucial ones off nl-pve01") after the second rpool NVMe loss in 34 h
(`incident-pve01-nvme-d3cold-single-leg-20260917`). Source: `pvesh get /cluster/resources
--type vm` on nl-pve03 + every `/etc/pve/nodes/*/{lxc,qemu-server}/*.conf` (cluster-
replicated, one node sees all). **149 guests: pve01 47 run / 18 stop · pve03 30 / 22 ·
pve04 29 / 3.** Offered to commit as `docs/nl-guest-criticality.md` — not yet answered.

## Criteria
- **P0** — estate-wide dependency with **no live peer**: losing it breaks auth, DNS, ingress,
  notification, backup, or the agentic control plane itself.
- **P1** — infrastructure **with** redundancy (losing one member is survivable) or important
  ops tooling.
- **P2** — apps, sandboxes, `dec`-tagged, templates, stopped.

## P0 — 14 (operator added protonmail-bridge01 on 2026-09-18; tg01 added the same day as de-facto P0)

| Host | Guest | RAM | Why |
|---|---|---|---|
| pve01 | nlfreeipa01 | 4G | DNS+Kerberos+LDAP authoritative, singleton |
| pve01 | nl-pihole01 | 4G | estate DNS resolver, singleton |
| pve01 | nlnpm01 | 4G | fronts `*.example.net`, singleton |
| pve01 | nl-matrix01 | 4G | ChatOps notification path, singleton |
| pve01 | nlsmtp-gpg01 | 1G | outbound mail relay (the alert emails), singleton |
| pve01 | nlsmtp-dkim01 | 1G | outbound mail signing, singleton |
| pve01 | nlvaultwarden01 | 6G | credential store, singleton |
| pve01→pve04 | nlprotonmail-bridge01 | 4G | Proton mail bridge — **P0 per operator 2026-09-18**, singleton |
| pve04 | nl-claude01 | 32G | the Claude Code host — every session runs here |
| pve04 | nl-n8n01 | 8G | orchestration engine |
| pve04 | nlyoutrack01 | 8G | trigger + sink for every incident |
| pve04 | nl-gitlab01 | 20G | all IaC + workflow repos, CI, Atlantis source |
| pve04 | nlpbs01 | 8G | backup server = the safety net in the no-fix posture |
| **pve01** | nltg01 | 8G | territory-grounder — PRIMARY alert intake since 2026-08-26; mis-rated P2 on 09-17, still on the fragile host (IFRNLLEI01PRD-2868) |

## ⛔⛔ CORRECTION 2026-09-18 00:53 NL (learned the hard way during the pve01 drain)
**`nlcl01iot01` and `nlcl01file01` are NOT P1-with-a-peer on pve01 — they behave as
P0.** Both HA pairs (HAHA = iot01/iot02/iotarb01, FISHA = file01/file02) fence with
`stonith:fence_pve`, which calls the Proxmox API **on the host of the VM being fenced**. When
pve01 is the thing that died, the fence target is unreachable → `fence_iot01 FAILED` →
Pacemaker (correctly) refuses to start the Filesystem/docker resources on the survivor →
**Home Assistant, zigbee2mqtt, esphome, nodered all Stopped; cl01file02 nfs-server stays
inactive.** Only the VIP + mosquitto moved. The "redundancy" routes its fence path through
the dead host. Unnoticed on 09-16 (8-min outage); visible tonight. **Ticket needed: second
fence path for both clusters (PDU / SBD watchdog, or fence_pve at the cluster API on a
surviving node).** Do NOT force `stonith_admin --confirm` minutes before the host returns —
split-brain risk on the NFS-backed HA config outweighs the wait.

## ⭐⭐ Headline findings

1. **The notification + diagnosis path for a pve01 failure lives ON pve01.** The ZFS-zed
   email that surfaced the 09-17 fault was generated on pve01 and relayed *through*
   nlsmtp-gpg01 (also pve01). Matrix, both DNS servers and NPM too. This is exactly
   why 09-16 ended on the AMT console.
2. **The two most-loaded hosts carry every P0.** pve01 (recurring storage fault) = 7 P0;
   pve04 (load 17-18, OOM-killed a VM 08-25) = 5 P0 = 76 G. pve03 (11 G free, load 7)
   carries none.
3. **Only 2 of pve01's 47 running guests can live-migrate** — nlcl01garbd01 (2G) and
   nlk8s-ctrl02 (8G), the only ones on shared `nlpvecl01-nfs`. Everything else is on
   `nl-pve01-local-zfs` (dir) or `local-zfs-native` → **offline migration + full disk
   copy, an outage each.** Every pve01 P0 is in this bucket.
4. **Replica stacking:** `nloas01/02/03` (`prod;vpn`, 2G each) — 3 replicas ALL on
   pve01 = fake redundancy. Also habitica01/02 + linkwarden01/02 (apps, tolerable).
   GR is worse: grk8s-ctrl01/02/03, k8s-node01/02/03 and oas01/02/03 ALL on
   gr-pve01 (out of scope 09-17, noted).
5. Genuinely well-spread (don't spend headroom here): k8s-ctrlr ×3 hosts, openbao ×3,
   redis ×3, haproxy/proxysql/k8s-haproxy/k8s-frr/cl01file/cl01iot ×2.

## Headroom (live 2026-09-17 ~19:40Z, NOT the 08-25 figures)
```
nl-pve01  total=94G  used=73G  avail=20G  load 10.0/7.5/7.8
nl-pve03  total=125G used=114G avail=11G  load 7.2/10.7/10.6
nlpve04  total=125G used=113G avail=11G  load 17.3/18.2/18.5
```
~22 G total elsewhere, realistically ~16 G safe. **Favour pve03**; pve04 should take nothing.
Full evacuation impossible without new capacity or reviving pve02 (IFRNLLEI01PRD-2646).

## Recommended move-set (value per GB), all offline+copy except where noted
1. **smtp-gpg01 + smtp-dkim01 — 2 G total** → independent alert path. Cheapest real win.
2. **oas02 (+oas03) — 2-4 G** → converts fake redundancy into real.
3. pihole01 — 4 G, then freeipa01 — 4 G (DNS/auth).
4. matrix01 — 4 G if headroom survives.
≈ 14-16 G. Not urgent to move: k8s-ctrl02 (1/3 across 3 hosts, live-migratable but fine).

## P1 — 41 (summary; full table was delivered in-session)
pve01: cl01file01, cl01iot01, cl01garbd01★live, haproxy01, proxysql01, redis01,
k8s-ctrl02★live, k8s-openbao01, k8s-haproxy01, k8s-frr01, k8s-node01, oas01/02/03, wg01,
healthops01, netbox01 (CMDB — degrades triage, breaks nothing live). protonmail-bridge01 → P0 (2026-09-18).
pve03: cl01file02, cl01iot02, cl01mariadb02, haproxy02, proxysql02, redis03, k8s-ctrl03,
k8s-openbao03, k8s-haproxy02, k8s-frr02, k8s-node02/03, **gpu01** (local LLM plane),
**litellm01**, **openobserve01**, **renovate01**.
pve04: cl01mariadb01, redis02, k8s-ctrl01, k8s-openbao02, k8s-node04, **nms01**,
**syslogng01**, **atlantis01**, **meshcentral01** (OOB path), sec01, dmz01; mattermost01 STOPPED 2026-09-18.

## P2 — 96
pve01 run: cloudbeaver01 code01 cubeos01 docuseal01 emailagent01 excalidraw01 gitlabrunner01
habitica01 librespeed01 linkwarden02 mealie01 myspeed01 netalertx01 netvisor01 omktst01
oxidized01 postiz01 reactive01 searxng01 slurpit01 stsrv01 twenty01 (tg01 → P0 de-facto, see above) · stop: backup01 baikal01
dmz02 ghostfolio01(-2854 disk full) goflow01 habitica02 heimdall01 inventaire01 linkwarden01
lxc-docker-tmpl-01(TEMPLATE) nextcloud01 openwebrx01 passbolt01 percona01 pialert01
viseron01 vpngw02 wireguard01.
pve03 run: actualbudget01 code02 gitlabrunner03 imaginary01 kiwix01 nc02
openwebui01 perplexica01 pulse01(dead since 04-30) sftpgo01 wallos01 wallos-mylab01
whiteboard01 · stop: VSPOCKNL attu01 bookwyrm01 calibre01 fail2ban01 firefly01 flowiseai01
gns01 graylog01 hpb01 ids01 imap01 k8s-node00(TEMPLATE) kasm01 koha01 librechat01 lyrion01
musicassistant01 nc04 nextcloud02 openwebui02 sagemath01.
pve04 run: androidsdk01 (8 GiB, restarted 2026-09-19) frigate01 (from pve03 2026-09-18) influxdb01 invoiceninja01 nc01
openarchiver01 syncthing01 · stop: cap01 screenity01 semaphore01 (2026-09-18) gitlabrunner02 (2026-09-19)
gitea01 gitlabrunner04 openclaw01. (postiz01 is on pve01, not pve04 — corrected 2026-09-19.)

## Side-finds
- `nlk8s-node01` is **running on pve01** although IFRNLLEI01PRD-2646 recorded it as
  deliberately left OFF after the 08-25 pve04 OOM. Unexplained drift.
- `nlcap01` (pve04, 8G, no tags) — purpose unknown, classified P2 by default.

## Confidence
0.85 on the classification — grounded in live configs + the replica-family scan, but the
P0/P1 line for netbox01, vaultwarden01, pbs01 and healthops01 is judgement, not measurement.
