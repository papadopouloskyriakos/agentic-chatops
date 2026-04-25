# Tool Risk Classification

**Date:** 2026-04-15
**Reference:** NIST AI RMF AG-MP.1 (Map -- Provider -- Tool & Resource Classification)
**Scope:** All 10 MCP servers (153 tools) across the claude-gateway agentic platform
**Related:** `docs/aci-tool-audit.md`, `docs/compliance-mapping.md`, `docs/agent-decommissioning.md`

---

## Overview

This document classifies every MCP tool available to the claude-gateway platform across
four risk dimensions defined by NIST AI RMF AG-MP.1. The platform operates 10 MCP servers
connected to Tier 2 (Claude Code) on nl-claude01, with a subset available to
Tier 1 (OpenClaw) via mcporter on nl-openclaw01.

The classification informs:
- Which tools require PreToolUse hook enforcement
- Which tools need audit logging in `tool_call_log`
- Which tools are gated by environment variables or approval workflows
- Which tool combinations create cascading risk through composition

---

## Classification Dimensions (NIST AG-MP.1)

### 1. Consequence Scope

| Level | Definition | Examples |
|-------|-----------|----------|
| **local** | Affects a single resource (one VM, one issue, one file) | Query a NetBox device, get a YT issue |
| **service** | Affects a running service (K8s deployment, n8n workflow) | Scale a deployment, update a workflow |
| **site** | Affects an entire site (NL or GR infrastructure) | Reboot a PVE node, stop a critical VM |
| **cross-site** | Affects multiple sites or the VPN mesh between them | Terraform apply on shared infra, delete cross-site resources |

### 2. Reversibility

| Level | Definition | Examples |
|-------|-----------|----------|
| **reversible** | Can be fully undone with no data loss | Read operations, stopped VM can be started |
| **partially-reversible** | Can be partially undone, some state may be lost | Rebooted VM loses in-memory state, patched resource needs manual revert |
| **irreversible** | Cannot be undone, data or state permanently lost | Deleted namespace, purged volumes, revoked credentials |

### 3. Authentication Level

| Level | Definition | Examples |
|-------|-----------|----------|
| **read-only** | Only retrieves data, no state changes | GET requests, list/describe/search operations |
| **read-write** | Can modify existing resources | PATCH, PUT, update operations |
| **admin** | Can create or delete resources, manage access | CREATE, DELETE operations |
| **lifecycle** | Can start, stop, reboot, or destroy compute resources | PVE start/stop, K8s node drain |

### 4. Compositional Risk

| Level | Definition | Examples |
|-------|-----------|----------|
| **standalone** | No meaningful side effects when combined with other tools | NetBox query, YT issue read |
| **chainable** | Can be combined in sequences that amplify impact | kubectl get -> kubectl patch -> kubectl rollout |
| **cascading** | Triggers downstream effects beyond the immediate action | PVE reboot drops VMs, K8s delete triggers pod rescheduling |

---

## Risk Tiers

| Tier | Criteria | Guardrail Requirements | Audit Level |
|------|----------|----------------------|-------------|
| **Low** | Read-only, local scope, reversible, standalone | None required | Sampled (10%) |
| **Medium** | Read-write local/service, reversible, standalone/chainable | tool_call_log entry | Full logging |
| **High** | Read-write service/site, partially-reversible, chainable | PreToolUse hook + tool_call_log | Full logging + alert |
| **Critical** | Lifecycle/admin, site/cross-site, irreversible/partially-reversible, cascading | PreToolUse hook + human approval + tool_call_log | Full logging + alert + audit trail |

---

## Per-Server Classification

### netbox (4 tools)

NetBox CMDB: 310 devices/VMs, 421 IPs, 39 VLANs across 6 sites. Read-only API token.

| Tool | Consequence | Reversibility | Auth | Compositional | Risk |
|------|------------|---------------|------|---------------|------|
| `netbox_get_objects` | local | reversible | read-only | standalone | **Low** |
| `netbox_search_objects` | local | reversible | read-only | standalone | **Low** |
| `netbox_get_object_by_id` | local | reversible | read-only | standalone | **Low** |
| `netbox_get_changelogs` | local | reversible | read-only | standalone | **Low** |

**Server risk summary:** All Low. No write capability. Safe for unrestricted use.

---

### kubernetes (23 tools)

K8s clusters at both NL and GR sites. ClusterMesh (Cilium) connects them. All K8s changes
MUST go through OpenTofu + Atlantis MR workflow (strict GitOps policy).

| Tool | Consequence | Reversibility | Auth | Compositional | Risk |
|------|------------|---------------|------|---------------|------|
| `kubectl_get` | local | reversible | read-only | standalone | **Low** |
| `kubectl_describe` | local | reversible | read-only | standalone | **Low** |
| `kubectl_logs` | local | reversible | read-only | standalone | **Low** |
| `kubectl_context` | local | reversible | read-only | standalone | **Low** |
| `kubectl_reconnect` | local | reversible | read-only | standalone | **Low** |
| `list_api_resources` | local | reversible | read-only | standalone | **Low** |
| `explain_resource` | local | reversible | read-only | standalone | **Low** |
| `ping` | local | reversible | read-only | standalone | **Low** |
| `kubectl_create` | service | reversible | read-write | chainable | **Medium** |
| `kubectl_generic` | service | partially-reversible | read-write | chainable | **High** |
| `kubectl_apply` | service | partially-reversible | read-write | cascading | **High** |
| `kubectl_patch` | service | partially-reversible | read-write | chainable | **High** |
| `kubectl_scale` | service | reversible | read-write | cascading | **High** |
| `kubectl_rollout` | service | partially-reversible | read-write | cascading | **High** |
| `exec_in_pod` | service | partially-reversible | read-write | chainable | **High** |
| `port_forward` | local | reversible | read-only | standalone | **Low** |
| `stop_port_forward` | local | reversible | read-only | standalone | **Low** |
| `node_management` | site | partially-reversible | lifecycle | cascading | **Critical** |
| `kubectl_delete` | service | irreversible | admin | cascading | **Critical** |
| `install_helm_chart` | service | partially-reversible | admin | cascading | **Critical** |
| `uninstall_helm_chart` | service | irreversible | admin | cascading | **Critical** |
| `upgrade_helm_chart` | service | partially-reversible | read-write | cascading | **High** |
| `cleanup` | service | irreversible | admin | standalone | **Critical** |

**Server risk summary:** 10 Low, 1 Medium, 6 High, 6 Critical. Critical tools gated by
GitOps policy (all changes via Atlantis MR). `kubectl_delete` and `node_management` are
the highest-risk tools in the entire platform.

---

### proxmox (15 tools)

Proxmox VE API across NL (3 nodes) and GR (2 nodes) sites. Lifecycle operations gated
by `PVE_ALLOW_LIFECYCLE` environment variable.

| Tool | Consequence | Reversibility | Auth | Compositional | Risk |
|------|------------|---------------|------|---------------|------|
| `pve_list_nodes` | local | reversible | read-only | standalone | **Low** |
| `pve_list_vms` | local | reversible | read-only | standalone | **Low** |
| `pve_list_lxc` | local | reversible | read-only | standalone | **Low** |
| `pve_node_status` | local | reversible | read-only | standalone | **Low** |
| `pve_guest_status` | local | reversible | read-only | standalone | **Low** |
| `pve_guest_config` | local | reversible | read-only | standalone | **Low** |
| `pve_vm_config` | local | reversible | read-only | standalone | **Low** |
| `pve_lxc_config` | local | reversible | read-only | standalone | **Low** |
| `pve_storage` | local | reversible | read-only | standalone | **Low** |
| `pve_cluster_status` | local | reversible | read-only | standalone | **Low** |
| `pve_node_tasks` | local | reversible | read-only | standalone | **Low** |
| `pve_start` | site | reversible | lifecycle | cascading | **Critical** |
| `pve_stop` | site | partially-reversible | lifecycle | cascading | **Critical** |
| `pve_reboot` | site | partially-reversible | lifecycle | cascading | **Critical** |
| `pve_shutdown` | site | partially-reversible | lifecycle | cascading | **Critical** |

**Server risk summary:** 11 Low, 0 Medium, 0 High, 4 Critical. All lifecycle operations
gated by `PVE_ALLOW_LIFECYCLE` env var (default: unset/disabled). Stopping a PVE node
hosting critical VMs (pve01 on either site) can cause site-wide outage.

**Cascading impact matrix for lifecycle tools:**

| Target | Impact if stopped/rebooted |
|--------|---------------------------|
| nl-pve01 | Gateway + DNS offline, total NL outage |
| nl-pve02 | K8s quorum maintained, SeaweedFS drain needed |
| nl-pve03 | Monitoring + Claude Code offline |
| gr-pve01 | Most GR VMs offline, VPN pipeline down |
| gr-pve02 | K8s iSCSI storage, NFS (89% used) |

---

### youtrack (47 tools)

YouTrack issue tracker. Used for issue lifecycle management, dedup, and audit trail.

| Tool Category | Tools | Consequence | Reversibility | Auth | Compositional | Risk |
|--------------|-------|------------|---------------|------|---------------|------|
| Read operations | `get_issue`, `get_issue_raw`, `get_issue_comments`, `get_issue_links`, `get_custom_fields`, `get_custom_field_schema`, `get_all_custom_fields_schemas`, `get_available_custom_field_values`, `get_custom_field_allowed_values`, `get_available_link_types`, `get_attachment_content`, `get_all_issues`, `get_all_projects`, `get_project`, `get_project_by_name`, `get_project_issues`, `get_projects`, `get_all_users`, `get_user`, `get_user_by_id`, `get_current_user`, `get_user_permissions`, `get_help` | local | reversible | read-only | standalone | **Low** |
| Search operations | `search_issues`, `search_users`, `search_with_custom_field_values`, `search_with_filter`, `advanced_search` | local | reversible | read-only | standalone | **Low** |
| Resource operations | `list_resources`, `read_resource`, `subscribe_resource`, `unsubscribe_resource` | local | reversible | read-only | standalone | **Low** |
| Validation operations | `validate_custom_field`, `validate_custom_field_for_project`, `diagnose_workflow_restrictions` | local | reversible | read-only | standalone | **Low** |
| Write operations | `add_comment`, `update_issue`, `update_custom_fields`, `update_issue_assignee`, `update_issue_estimation`, `update_issue_priority`, `update_issue_state`, `update_issue_type`, `link_issues`, `add_dependency`, `add_duplicate_link`, `add_relates_link`, `remove_dependency` | local | partially-reversible | read-write | chainable | **Medium** |
| Create operations | `create_issue`, `create_project`, `create_version`, `create_subsystem`, `create_build`, `batch_update_custom_fields`, `update_project` | local | reversible | admin | chainable | **Medium** |

**Server risk summary:** 35 Low, 12 Medium. No High or Critical. YT state transitions for
issue management use `curl /api/commands` (not MCP `update_issue_state` due to workflow
restrictions -- see `docs/known-failure-rules.md`).

---

### n8n-mcp (23 tools)

n8n workflow orchestration. Controls the platform's own automation layer.

| Tool | Consequence | Reversibility | Auth | Compositional | Risk |
|------|------------|---------------|------|---------------|------|
| `n8n_get_workflow` | local | reversible | read-only | standalone | **Low** |
| `n8n_list_workflows` | local | reversible | read-only | standalone | **Low** |
| `n8n_executions` | local | reversible | read-only | standalone | **Low** |
| `n8n_health_check` | local | reversible | read-only | standalone | **Low** |
| `n8n_workflow_versions` | local | reversible | read-only | standalone | **Low** |
| `get_node` | local | reversible | read-only | standalone | **Low** |
| `get_template` | local | reversible | read-only | standalone | **Low** |
| `search_nodes` | local | reversible | read-only | standalone | **Low** |
| `search_templates` | local | reversible | read-only | standalone | **Low** |
| `tools_documentation` | local | reversible | read-only | standalone | **Low** |
| `validate_node` | local | reversible | read-only | standalone | **Low** |
| `validate_workflow` | local | reversible | read-only | standalone | **Low** |
| `n8n_validate_workflow` | local | reversible | read-only | standalone | **Low** |
| `n8n_audit_instance` | local | reversible | read-only | standalone | **Low** |
| `n8n_create_workflow` | service | reversible | admin | cascading | **High** |
| `n8n_update_full_workflow` | service | partially-reversible | read-write | cascading | **High** |
| `n8n_update_partial_workflow` | service | partially-reversible | read-write | cascading | **High** |
| `n8n_generate_workflow` | local | reversible | read-write | standalone | **Medium** |
| `n8n_autofix_workflow` | service | partially-reversible | read-write | chainable | **High** |
| `n8n_deploy_template` | service | partially-reversible | admin | cascading | **High** |
| `n8n_test_workflow` | service | reversible | read-write | chainable | **Medium** |
| `n8n_manage_credentials` | cross-site | partially-reversible | admin | cascading | **Critical** |
| `n8n_delete_workflow` | service | irreversible | admin | cascading | **Critical** |
| `n8n_manage_datatable` | service | partially-reversible | read-write | chainable | **Medium** |

**Server risk summary:** 14 Low, 3 Medium, 4 High, 2 Critical. Workflow modifications
are high-risk because they change the platform's own control plane. A malformed workflow
update can break alert processing for all sites. `n8n_manage_credentials` is Critical
because it can revoke or modify credentials used by 26 workflows (~470 nodes).

**IMPORTANT:** After any workflow update via API/MCP, toggle deactivate then activate to
reload webhook listeners (known n8n behavior).

---

### gitlab-mcp (tools vary by server version)

GitLab operations for MR creation, pipeline checks, and commit management.

| Tool Category | Consequence | Reversibility | Auth | Compositional | Risk |
|--------------|------------|---------------|------|---------------|------|
| Read operations (list MRs, pipeline status, diffs) | local | reversible | read-only | standalone | **Low** |
| Create MR | local | reversible | read-write | chainable | **Medium** |
| Commit/push | service | partially-reversible | read-write | cascading | **High** |
| Merge MR | service | partially-reversible | admin | cascading | **High** |

**Server risk summary:** Mostly Low/Medium. Merge operations are High because they trigger
CI/CD pipelines that can deploy changes to production. The claude-gateway repo allows
direct push to main (per operator preference), but IaC repos require MR workflow.

---

### codegraph (19 tools)

CodeGraphContext (KuzuDB): code graph database for CubeOS (355K lines) and MeshSat.

| Tool | Consequence | Reversibility | Auth | Compositional | Risk |
|------|------------|---------------|------|---------------|------|
| `find_code` | local | reversible | read-only | standalone | **Low** |
| `find_dead_code` | local | reversible | read-only | standalone | **Low** |
| `find_most_complex_functions` | local | reversible | read-only | standalone | **Low** |
| `analyze_code_relationships` | local | reversible | read-only | standalone | **Low** |
| `get_repository_stats` | local | reversible | read-only | standalone | **Low** |
| `list_indexed_repositories` | local | reversible | read-only | standalone | **Low** |
| `execute_cypher_query` | local | reversible | read-only | standalone | **Low** |
| `visualize_graph_query` | local | reversible | read-only | standalone | **Low** |
| `check_job_status` | local | reversible | read-only | standalone | **Low** |
| `list_jobs` | local | reversible | read-only | standalone | **Low** |
| `list_watched_paths` | local | reversible | read-only | standalone | **Low** |
| `calculate_cyclomatic_complexity` | local | reversible | read-only | standalone | **Low** |
| `search_registry_bundles` | local | reversible | read-only | standalone | **Low** |
| `load_bundle` | local | reversible | read-write | standalone | **Low** |
| `add_code_to_graph` | local | reversible | read-write | standalone | **Medium** |
| `add_package_to_graph` | local | reversible | read-write | standalone | **Medium** |
| `watch_directory` | local | reversible | read-write | standalone | **Medium** |
| `unwatch_directory` | local | reversible | read-write | standalone | **Medium** |
| `delete_repository` | local | irreversible | admin | standalone | **High** |

**Server risk summary:** 14 Low, 4 Medium, 1 High. Entirely local scope (affects only
the code graph database, not live systems). `delete_repository` removes indexed data
but does not affect source code.

---

### opentofu (5 tools)

OpenTofu Registry lookups: provider docs, resource schemas, module metadata.

| Tool | Consequence | Reversibility | Auth | Compositional | Risk |
|------|------------|---------------|------|---------------|------|
| `search-opentofu-registry` | local | reversible | read-only | standalone | **Low** |
| `get-resource-docs` | local | reversible | read-only | standalone | **Low** |
| `get-datasource-docs` | local | reversible | read-only | standalone | **Low** |
| `get-provider-details` | local | reversible | read-only | standalone | **Low** |
| `get-module-details` | local | reversible | read-only | standalone | **Low** |

**Server risk summary:** All Low. Pure registry lookups with no write capability.

---

### tfmcp (29 tools)

Terraform/OpenTofu local analysis and execution. Contains both read-only analysis
and dangerous write operations.

| Tool | Consequence | Reversibility | Auth | Compositional | Risk |
|------|------------|---------------|------|---------------|------|
| `set_terraform_directory` | local | reversible | read-only | standalone | **Low** |
| `analyze_terraform` | local | reversible | read-only | standalone | **Low** |
| `analyze_module_health` | local | reversible | read-only | standalone | **Low** |
| `analyze_state` | local | reversible | read-only | standalone | **Low** |
| `analyze_plan` | local | reversible | read-only | standalone | **Low** |
| `get_terraform_state` | local | reversible | read-only | standalone | **Low** |
| `get_terraform_plan` | local | reversible | read-only | standalone | **Low** |
| `list_terraform_resources` | local | reversible | read-only | standalone | **Low** |
| `get_resource_dependency_graph` | local | reversible | read-only | standalone | **Low** |
| `get_security_status` | local | reversible | read-only | standalone | **Low** |
| `get_latest_module_version` | local | reversible | read-only | standalone | **Low** |
| `get_latest_provider_version` | local | reversible | read-only | standalone | **Low** |
| `get_module_details` | local | reversible | read-only | standalone | **Low** |
| `get_provider_docs` | local | reversible | read-only | standalone | **Low** |
| `get_provider_info` | local | reversible | read-only | standalone | **Low** |
| `search_terraform_modules` | local | reversible | read-only | standalone | **Low** |
| `search_terraform_providers` | local | reversible | read-only | standalone | **Low** |
| `suggest_module_refactoring` | local | reversible | read-only | standalone | **Low** |
| `terraform_output` | local | reversible | read-only | standalone | **Low** |
| `terraform_providers` | local | reversible | read-only | standalone | **Low** |
| `terraform_workspace` | local | reversible | read-only | chainable | **Low** |
| `validate_terraform` | local | reversible | read-only | standalone | **Low** |
| `validate_terraform_detailed` | local | reversible | read-only | standalone | **Low** |
| `terraform_graph` | local | reversible | read-only | standalone | **Low** |
| `terraform_fmt` | local | reversible | read-write | standalone | **Medium** |
| `init_terraform` | local | reversible | read-write | chainable | **Medium** |
| `terraform_refresh` | service | partially-reversible | read-write | cascading | **High** |
| `terraform_taint` | service | reversible | read-write | chainable | **High** |
| `terraform_import` | service | partially-reversible | read-write | chainable | **High** |
| `apply_terraform` | cross-site | partially-reversible | admin | cascading | **Critical** |
| `destroy_terraform` | cross-site | irreversible | admin | cascading | **Critical** |

**Server risk summary:** 24 Low, 2 Medium, 3 High, 2 Critical. `apply_terraform` and
`destroy_terraform` are gated by the Atlantis MR workflow (all K8s/infra changes must go
through GitOps). Direct execution bypasses this control and is prohibited.

---

## Risk Summary by Server

| MCP Server | Total Tools | Low | Medium | High | Critical |
|------------|-------------|-----|--------|------|----------|
| netbox | 4 | 4 | 0 | 0 | 0 |
| kubernetes | 23 | 10 | 1 | 6 | 6 |
| proxmox | 15 | 11 | 0 | 0 | 4 |
| youtrack | 47 | 35 | 12 | 0 | 0 |
| n8n-mcp | 23 | 14 | 3 | 4 | 2 |
| gitlab-mcp | varies | -- | -- | -- | -- |
| codegraph | 19 | 14 | 4 | 1 | 0 |
| opentofu | 5 | 5 | 0 | 0 | 0 |
| tfmcp | 29 | 24 | 2 | 3 | 2 |
| **Total** | **~165** | **~117** | **~22** | **~14** | **~14** |

**Distribution:** ~71% Low, ~13% Medium, ~8% High, ~8% Critical.

---

## Guardrail Cross-Reference

### Critical Tool Enforcement

| Guardrail | Mechanism | Tools Covered |
|-----------|-----------|---------------|
| PreToolUse hooks | `scripts/hooks/unified-guard.sh` (merged audit-bash + protect-files) | All Bash commands (30+ destructive patterns blocked), all Edit/Write operations (sensitive files protected) |
| exec-approvals.json | 36 explicit patterns (no wildcards) on OpenClaw | All OpenClaw shell execution |
| PVE_ALLOW_LIFECYCLE | Environment variable gate | `pve_start`, `pve_stop`, `pve_reboot`, `pve_shutdown` |
| GitOps policy | Atlantis MR workflow required | `apply_terraform`, `destroy_terraform`, all K8s mutations |
| AUTHORIZED_SENDERS | Matrix Bridge filter | Only `@dominicus` can trigger actions |
| Cost ceiling | $5/session warning, $25/day plan-only | All Tier 2 sessions |

### High Tool Monitoring

| Monitoring Layer | Data Store | Tools Covered |
|-----------------|------------|---------------|
| `tool_call_log` | gateway.db (~88K entries) | All tool invocations during sessions |
| `execution_log` | gateway.db (~18K entries) | SSH commands, state changes |
| `a2a_task_log` | gateway.db | All inter-tier escalations |
| Prometheus metrics | write-session-metrics.sh (cron */5) | Per-session cost, duration, confidence |
| Bash audit log | `/tmp/claude-code-bash-audit.log` | All Bash commands (unified-guard.sh) |
| File audit log | `/tmp/claude-code-file-audit.log` | All file edit/write operations |

### Compositional Risk Chains

Certain tool combinations create amplified risk beyond their individual classifications.
These chains are monitored but not automatically blocked (blocking would prevent legitimate
multi-step operations).

| Chain | Tools | Combined Risk | Mitigation |
|-------|-------|--------------|------------|
| K8s reconnaissance -> mutation | `kubectl_get` -> `kubectl_delete` | Critical | unified-guard blocks `kubectl delete namespace/--all` |
| Workflow modification -> credential access | `n8n_update_full_workflow` -> `n8n_manage_credentials` | Critical | n8n API key rotation, credential audit |
| Terraform state read -> destroy | `get_terraform_state` -> `destroy_terraform` | Critical | Atlantis MR gate |
| PVE reconnaissance -> lifecycle | `pve_guest_status` -> `pve_stop` | Critical | PVE_ALLOW_LIFECYCLE env var |
| Code graph delete -> reindex | `delete_repository` -> `add_code_to_graph` | Medium | Manual confirmation |
| K8s scale -> Helm upgrade | `kubectl_scale` -> `upgrade_helm_chart` | High | GitOps policy |

---

## Tier-Specific Tool Access

Not all tiers have access to all tools. Access is constrained by architecture.

| MCP Server | Tier 1 (OpenClaw) | Tier 2 (Claude Code) | Notes |
|------------|-------------------|---------------------|-------|
| netbox | Via skill scripts | Direct MCP | OpenClaw uses `netbox-lookup.sh` wrapper |
| kubernetes | Via `kubectl` in safe-exec | Direct MCP | OpenClaw gated by exec-approvals |
| proxmox | No access | Direct MCP | Lifecycle gated by PVE_ALLOW_LIFECYCLE |
| youtrack | Via mcporter + shell scripts | Direct MCP | Both tiers have full access |
| n8n-mcp | Via mcporter | Direct MCP | Both tiers, write ops are High+ |
| gitlab-mcp | Via curl (mcporter broken) | Direct MCP | OpenClaw uses curl fallback |
| codegraph | Via skill scripts | Direct MCP | Read-only for OpenClaw |
| opentofu | No access | Direct MCP | Registry lookups only |
| tfmcp | No access | Direct MCP | apply/destroy gated by Atlantis |

---

## Blocked Patterns (unified-guard.sh)

The PreToolUse hook blocks these patterns before any permission check can authorize them.
This is the last line of defense -- it fires deterministically regardless of agent reasoning.

### Destructive Commands (Bash)

```
rm -rf /
rm -rf /*
rm -rf ~
mkfs
dd if=/dev/zero
kubectl delete namespace
kubectl delete --all
systemctl stop n8n
systemctl stop docker
iptables -F
init 0
init 6
halt
poweroff
shutdown -h
reboot (unqualified)
```

### Exfiltration Patterns (Bash)

```
curl.*| bash
wget.*| bash
nc -e
bash -i >& /dev/tcp
python -c.*socket
/dev/tcp/
```

### Protected Files (Edit/Write)

```
.env
*.key
*.pem
id_rsa
id_ed25519
credentials
passwords
authorized_keys
known_hosts (write only)
```

### OpenClaw Exec Blocklist (safe-exec.sh)

30+ additional patterns enforced at the OpenClaw tier, including all of the above plus:
`pkill`, `killall`, `chmod 777`, `chown root`, `crontab -r`, `userdel`, `groupdel`,
`visudo`, `passwd`, reverse shell patterns.

---

## Audit and Review Cadence

| Activity | Frequency | Owner | Output |
|----------|-----------|-------|--------|
| Tool call log review | Weekly | Automated (regression-detector.sh) | Anomaly alerts to `#alerts` |
| Risk classification review | Quarterly | Operator | Updated tool-risk-classification.md |
| Guardrail effectiveness test | Monthly | Automated (golden-test-suite.sh) | T7, T12, T13 test results |
| New tool onboarding review | Per addition | Operator | Classification added to this document |
| ACI tool audit | Semi-annual | Operator | Updated docs/aci-tool-audit.md |
| Compositional chain review | Quarterly | Operator | Updated chain table above |

---

## Cross-References

| Document | Relevance |
|----------|-----------|
| `docs/aci-tool-audit.md` | 8-point ACI checklist for top-10 tools |
| `docs/compliance-mapping.md` | NIST CSF 2.0 and CIS Controls v8 mapping |
| `docs/agent-decommissioning.md` | Credential revocation during agent lifecycle |
| `docs/architecture.md` | System architecture, workflow topology |
| `openclaw/exec-approvals.json` | 36-pattern allowlist for OpenClaw exec |
| `scripts/hooks/unified-guard.sh` | PreToolUse hook (merged audit-bash + protect-files) |
| `.claude/settings.json` | Hook configuration (PreToolUse, Stop, PreCompact) |
| `.claude/rules/platform-features.md` | Guardrails and safety documentation |
