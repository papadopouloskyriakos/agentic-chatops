# Host Blast Radius — Infragraph Declared Edges (source of truth)

**Consumed by:** `scripts/infragraph-seed.py --declared` (IFRNLLEI01PRD-1032)
**Epic:** IFRNLLEI01PRD-1029 · Plan: [`docs/plans/infragraph-implementation-plan.md`](plans/infragraph-implementation-plan.md)

This file is the git-reviewed source of truth for **operator-declared** infragraph
edges — dependency knowledge that no automated seeder (NetBox, IaC,
`TUNNEL_GRAPH_EDGE`) can derive. The seeder parses every row of the table below
into `graph_relationships` + `infragraph_dynamics` with `source='declared'`.
The database is the runtime view; this file survives DB rebuilds.

Rules:

- **Edge direction: SOURCE depends on TARGET** (`vm runs_on pve_node`,
  `service depends_on vm`). Blast radius of a host = everything that reaches it
  transitively.
- Full site-prefixed hostnames only (`nl-pve01`, never `pve01`) — P0 rule.
- `entity:name` syntax. Entity types: `physical_host`, `pve_node`, `vm`, `lxc`,
  `service`, `network_device`, `tunnel`, `bgp_session`, `site`.
  Rel types: `runs_on`, `depends_on`, `routes_via`, `member_of`, `backs_up_to`,
  `peers_with`.
- `expected_alerts` is a `;`-separated list of alert rule names expected to fire
  **on the SOURCE side** when the TARGET fails (leave empty if unknown — the
  learners will fill dynamics in from chaos runs and incident history).
- Changes go through MR review like any other IaC.

## Declared edges

| source | rel_type | target | expected_alerts | notes |
|---|---|---|---|---|
| lxc:nl-n8n01 | runs_on | pve_node:nl-pve01 | Device Down;Service up/down | n8n LXC CT VMID_REDACTED; pve01 host-pressure history (IFRNLLEI01PRD-622/-692/-704) |
| vm:nl-gpu01 | runs_on | pve_node:nl-pve03 | Device Down | VM VMID_REDACTED; ZFS DIO + qcow2 io-error history (IFRNLLEI01PRD-900) |
| service:ollama | depends_on | vm:nl-gpu01 | | Ollama at nl-gpu01:11434; Tier-3 local models + judge/synth |
| service:rerank | depends_on | vm:nl-gpu01 | RAGRerankServiceDown | bge-reranker-v2-m3 at nl-gpu01:11436 |
| vm:nlk8s-ctrl01 | runs_on | pve_node:nlpve04 | Device Down;KubeAPIDown | VM VMID_REDACTED; etcd balloon incident (IFRNLLEI01PRD-863) — no balloon on control plane |

<!-- Seed pipeline: infragraph-seed.py --declared parses ONLY the table above.
     Add rows; do not change column order. Malformed rows are skipped loudly
     (non-zero exit) so CI catches typos. -->
