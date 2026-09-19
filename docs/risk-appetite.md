# Operator Risk Appetite — Autonomous Remediation

**Status:** defined with the operator 2026-06-25 (IFRNLLEI01PRD-1408). This is the
source-of-truth statement of how much the gateway may do on its own. The classifier
(`scripts/classify-session-risk.py`), the gates, and the sentinels **derive from this** —
when they disagree with this document, the document is the intent and the code is the bug.

The operator is **out of the loop by design** (does not vote on Matrix approval polls). The
goal is therefore: act autonomously on everything that is *safe and recoverable*, page (SMS)
on the impactful-but-reversible, and hold for a human ONLY what is irreversible or a security
event. A growing POLL_PAUSE backlog of *reversible* work is a failure of this policy, not a
success.

---

## The four dials (what makes an action "risky")

1. **Reversibility** — does the system recover on its own / can it be undone? (a reboot
   recovers; `mkfs`/`dropdb`/`delete pvc` do not.)
2. **Blast radius** — how much does it affect? (one pod < one host's guests < a cluster < the
   gateway/VPN itself.)
3. **Statefulness** — can it lose data or quorum? (a stateless pod vs etcd/DB/SeaweedFS.)
4. **Prediction confidence** — did the infragraph predict the outcome and did the mechanical
   verdict confirm it? (necessary downstream of the band.)

---

## The bands (what the autonomy does)

| Band | Behaviour |
|---|---|
| **AUTO** | execute the conservative reversible fix, verify, auto-resolve. Silent. |
| **AUTO_NOTICE** | same, **plus a parallel SMS** so the operator is informed and can veto out-of-band (`!session abort`). |
| **POLL_PAUSE** | hold for a human. Posts the plan, pages SMS, does NOT proceed on timeout. |
| (gate-governed) | AUTO/AUTO_NOTICE **only if** the relevant territory `CLAUDE.md` was loaded this session **and** the infragraph verdict = match. |

Downstream of the band, two gates are unconditional: the **plan_hash prediction gate**
(fail-closed: no auto-resolve without a committed prediction) and the **mechanical verdict
gate** (a deviation never auto-resolves).

---

## NEVER auto — the hard floor (held regardless of any sentinel)

- **Irreversible data/state destruction:** `mkfs`, `*destroy` (zpool/qm/pct/terraform),
  `dropdb`, `delete pvc/pv/namespace/secret`, `docker volume|system|network prune`,
  **`zfs rollback`, `zpool offline`**, `rm -rf` of data.
- **Catastrophic, remotely-unrecoverable network:** `write erase`, `reload`, `no ip routing`,
  global `shutdown`, `default interface` (lockout / total outage; the network `CLAUDE.md`
  never-do list).
- **Config-file overwrites of system state:** `sed -i`/`tee`/`>` into `/etc/…`.
- **Code deploy & repo destruction:** `gh`/`glab` `pr|mr merge`, `release create`,
  `api … -X DELETE/PUT` (deploying unreviewed code / deleting refs is a human decision —
  the MR review flow exists for a reason).
- **P0-host reboot** — the 7 P0 hosts (below).
- **A real prompt-injection / jailbreak.**

---

## Tier A — silent AUTO (low risk, reversible, bounded blast)

Read-only investigation (`kubectl get`, `show run`, `df`); confirm-recovery; `systemctl
restart|reload`; `docker restart`; `docker image|builder prune`; `fstrim`; journal vacuum;
`drop_caches`; `certbot renew`; stale-lock `rm *.lock|*.pid`; `kubectl scale --replicas≥1`;
`kubectl delete pod` (reschedule); `terraform plan`; crowdsec decisions; containment verbs.
*This is the bulk of production — the self-resolving NL k8s/etcd flaps (58% of sessions).*

## Tier B — AUTO + SMS (reversible but impactful)

`kubectl rollout restart` (**incl. stateful etcd/DB/SeaweedFS — gate-governed** by
`k8s/CLAUDE.md` + verdict); guest reboot (`qm|pct reboot <id>`); **non-P0 host reboot**;
any reversible action **on a P0 host**; **network / firewall / BGP / AWX writes** — `iptables`,
ASA config (`conf t`/`send_config_set`/`copy run start`/`crypto map`), `swanctl`, FRR,
`awx launch` — **gate-governed** by the `network`/`edge` `CLAUDE.md` + verdict (operator
decision 2026-06-25: higher autonomy on network, bounded by the manual's never-do list which
stays on the floor above). `service stop`, `podman`/`nerdctl`/`lxc` stop/rm — gate-governed
like their docker/systemctl equivalents.

## Tier C — held (POLL_PAUSE + SMS)

Everything in the hard floor above, plus anything the classifier marks `high` that is not
gate-governed, deviation/partial verdicts, no-prediction (fail-closed), and ambiguous-risk.

---

## Blind-spot policy — "unrecognized mutation" is NOT "safe"

Decided 2026-06-25: the classifier's pattern set is not exhaustive, and an action that
matches no pattern must not silently AUTO by omission. Closed by risk:
`gh`/`glab` deploy+delete → floor; `zfs rollback`/`zpool offline` → floor;
`sed -i`/`tee` `/etc` + `write erase`/`reload` → floor; `conf t`/`copy run start` →
network gate-governed; `service stop` + `podman`/`lxc` stop/rm → gate-governed; benign reads →
AUTO. (Not chosen: a blanket default-deny on every unrecognized mutation — too broad for now;
revisit if new blind spots keep appearing.)

---

## The estate the dials map onto

**P0 hosts (reboot = POLL_PAUSE; reversible action = AUTO_NOTICE):** `nl-pve01`
(gateway+DNS+runs the pipeline), `nl-pve03` (monitoring+gpu01+the agent itself),
`nlpve04` (k8s-ctrl01/etcd + stateful guests), `nl-fw01` (NL VPN/alerting),
`gr-pve01` (most GR VMs + all GR control-plane), `gr-pve02` (GR k8s iSCSI storage),
`gr-fw01` (GR VPN — cross-site pipeline). Lockstep with `docs/host-blast-radius.md`
(`_P0_HOSTS_BASE`, enforced by test-1103). `nl-pve02` is deliberately NOT P0 — the
canonical "safe to reboot first."

**Stateful (reboot/restart = quorum/data risk → gate-governed/held):** all k8s control-plane
(`*k8s-ctrlr*`, etcd), DBs (`*postgres*`/`*mysql*`/`mariadb`/`mongo`/`percona`/…), storage
(SeaweedFS/synology/PBS), queues. (`percona`/`proxysql`/`graylog` added to `_STATEFUL_DENY_RE`
2026-06-25.)

---

## Enforcement (sentinels & gates — all currently ON)

`~/gateway.autonomy_forward` (bands), `~/gateway.conservative_remediation` (the reversible
carve), `~/gateway.territory_gate` (manual prerequisite + stateful/network relaxation),
`~/gateway.host_reboot_auto` (non-P0 host reboot). Any one `rm` reverts that layer instantly.

---

## Implemented 2026-06-25 (this revision)

- **Blind-spot closures + network-tier gate-governance** — live in `classify-session-risk.py`
  (`_AUTONOMY_BLINDSPOT_PATTERNS` + `_GATE_GOVERNABLE_HIGH` + the `_assign_bands` gate branch;
  REQ-014/015). Folded only under `AUTONOMY_FORWARD` (flag-off byte-identical). Suite
  `test-1408-blindspot-network.sh` (39 cases). `percona`/`proxysql`/`graylog` added to
  `_STATEFUL_DENY_RE`.
- **Scope note:** a bare Cisco `reload` is intentionally NOT pattern-matched (it collides with
  the conservative `systemctl reload`); a device reload via netmiko is caught as a gate-governed
  `network-config-write` and the loaded network `CLAUDE.md` forbids it. `podman/lxc rm` lands
  HELD (POLL_PAUSE) via the existing `fs-write` overlap — the conservative reading.

## Open / deferred (not yet built)

- **#2 Layer 2+3** — verdict blast-radius scoping + hard-alert floor (cut the remaining
  *same-site* coincidental deviation noise). Build behind a flag and **backtest against the
  prediction history** (prove zero recall loss) before enabling. The reboot-prediction model
  is only ~29% exact-match today, so this materially affects the auto-resolve rate.
