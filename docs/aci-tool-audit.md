# ACI Tool Audit — Agent-Computer Interface Assessment

**Date:** 2026-04-07
**Reference:** Industry Agentic References (Knowledge Source #3), Section 2
**Scope:** Top-10 most-used MCP tools audited against ACI checklist

---

## Checklist (from Anthropic + Microsoft Semantic Kernel)

Every tool description should satisfy:

| # | Criteria | Source |
|---|----------|--------|
| C1 | Example usage included | Anthropic |
| C2 | Edge cases documented | Anthropic |
| C3 | Input format requirements specified | Anthropic |
| C4 | Clear boundaries from similar/overlapping tools | Anthropic |
| C5 | Parameter names unambiguous | Anthropic, SK |
| C6 | Type annotations complete | SK |
| C7 | Written as if explaining to a junior developer | Anthropic |
| C8 | Snake_case naming | SK |

---

## Tool Audit Results

### 1. `mcp__netbox__netbox_search_objects`

**Usage:** Device/VM identification, CMDB queries. Called in every infra triage.

| Criteria | Status | Notes |
|----------|--------|-------|
| C1 Example | Needs improvement | No usage examples in description |
| C2 Edge cases | Missing | Doesn't document what happens with partial names or ambiguous queries |
| C3 Input format | Good | Parameters well-defined |
| C4 Boundaries | Needs improvement | Overlap with `netbox_get_objects` and `netbox_get_object_by_id` not clarified |
| C5 Param names | Good | Clear names |
| C6 Types | Good | String types specified |
| C7 Junior-friendly | Needs improvement | Assumes familiarity with NetBox data model |
| C8 Snake_case | Good | Consistent snake_case |

**Rating: Needs Improvement** (3/8 criteria met)

**Consolidation opportunity:** `netbox_search_objects` and `netbox_get_objects` could be merged into a single `netbox_query` tool with a `mode` parameter.

---

### 2. `mcp__kubernetes__kubectl_get`

**Usage:** Pod/node/deployment status queries. Called in every K8s alert triage.

| Criteria | Status | Notes |
|----------|--------|-------|
| C1 Example | Missing | No examples of resource type + namespace combinations |
| C2 Edge cases | Missing | Doesn't document behavior when resource doesn't exist |
| C3 Input format | Good | Resource type, name, namespace parameters |
| C4 Boundaries | Needs improvement | Overlap with `kubectl_describe`, `kubectl_logs` — when to use which? |
| C5 Param names | Good | Clear names |
| C6 Types | Good | Well-typed |
| C7 Junior-friendly | Needs improvement | Assumes kubectl knowledge |
| C8 Snake_case | Good | Consistent |

**Rating: Needs Improvement** (3/8)

**Consolidation opportunity:** For triage contexts, `kubectl_get`, `kubectl_describe`, and `kubectl_logs` could be wrapped in a single `k8s_investigate(resource, action)` tool.

---

### 3. `mcp__youtrack__get_issue`

**Usage:** Issue context retrieval at session start and during investigation.

| Criteria | Status | Notes |
|----------|--------|-------|
| C1 Example | Missing | No example output format |
| C2 Edge cases | Missing | Behavior with invalid issue IDs undocumented |
| C3 Input format | Good | Issue ID clearly required |
| C4 Boundaries | Good | No overlapping tool |
| C5 Param names | Good | Clear |
| C6 Types | Good | Well-typed |
| C7 Junior-friendly | Adequate | Straightforward |
| C8 Snake_case | Good | Consistent |

**Rating: Good** (5/8)

---

### 4. `mcp__proxmox__pve_guest_status`

**Usage:** VM/LXC status checks during availability triage.

| Criteria | Status | Notes |
|----------|--------|-------|
| C1 Example | Missing | No example of output fields |
| C2 Edge cases | Missing | What happens with powered-off guests? |
| C3 Input format | Good | VMID required |
| C4 Boundaries | Needs improvement | Overlap with `pve_guest_config` and `pve_vm_config` |
| C5 Param names | Good | Clear |
| C6 Types | Good | Integer VMID |
| C7 Junior-friendly | Needs improvement | Assumes PVE knowledge |
| C8 Snake_case | Good | Consistent |

**Rating: Needs Improvement** (3/8)

---

### 5. `mcp__n8n-mcp__n8n_get_workflow`

**Usage:** Workflow inspection during dev/debug sessions.

| Criteria | Status | Notes |
|----------|--------|-------|
| C1 Example | Good | Mode parameter well-documented |
| C2 Edge cases | Good | Different modes handle different needs |
| C3 Input format | Good | ID required, mode documented |
| C4 Boundaries | Good | Clear separation from update tools |
| C5 Param names | Good | Clear |
| C6 Types | Good | Enum for mode |
| C7 Junior-friendly | Good | Clear descriptions |
| C8 Snake_case | Good | Consistent |

**Rating: Good** (8/8)

---

### 6-10. Remaining Tools (Summary)

| # | Tool | Rating | Key Issue |
|---|------|--------|-----------|
| 6 | `mcp__netbox__netbox_get_objects` | Needs Improvement | Overlaps with search_objects |
| 7 | `mcp__kubernetes__kubectl_describe` | Needs Improvement | No boundary docs vs kubectl_get |
| 8 | `mcp__kubernetes__kubectl_logs` | Good | Clear purpose, no overlap |
| 9 | `mcp__proxmox__pve_list_vms` | Good | Straightforward list operation |
| 10 | `mcp__youtrack__update_issue_state` | Needs Improvement | Known broken (see known-failure-rules.md #14) |

---

## Consolidation Recommendations

| Current Tools | Proposed Consolidation | Impact |
|--------------|----------------------|--------|
| `netbox_search_objects` + `netbox_get_objects` + `netbox_get_object_by_id` | Single `netbox_query(type, query, id?)` | Reduces 3 tools → 1, eliminates selection confusion |
| `kubectl_get` + `kubectl_describe` + `kubectl_logs` | `k8s_investigate(resource, action)` for triage | Reduces 3 → 1 for triage contexts |
| `pve_guest_status` + `pve_guest_config` + `pve_vm_config` + `pve_lxc_config` | `pve_query(vmid, detail_level)` | Reduces 4 → 1 |

**Note:** Consolidation requires MCP server changes. As an interim measure, **prompt-level tool guidance** via `config/tool-profiles.json` provides equivalent effect by steering agents to the right tools.

---

## Response Format Recommendations

| Tool | Current | Recommended |
|------|---------|-------------|
| `netbox_search_objects` | Full JSON with all fields | Add `response_format: concise` returning only name, IP, site, role |
| `kubectl_get` | Full resource YAML | Add `response_format: concise` returning only status, conditions, events |
| `pve_guest_status` | Full status object | Add `response_format: concise` returning only state, uptime, node |

**Token savings estimate:** ~3x reduction per query in concise mode (~200 tokens vs ~600 tokens).

---

## Overall Assessment

| Rating | Count | Tools |
|--------|-------|-------|
| Good (6-8/8) | 4 | n8n_get_workflow, kubectl_logs, pve_list_vms, get_issue |
| Needs Improvement (3-5/8) | 6 | netbox_search, kubectl_get, kubectl_describe, pve_guest_status, netbox_get_objects, update_issue_state |
| Critical (0-2/8) | 0 | None |

**Action items:**
1. Add usage examples to top-6 tools' descriptions (via MCP server config or wrapper layer)
2. Document tool boundaries in CLAUDE.md (interim: done via tool-profiles.json)
3. Implement response_format parameter for high-traffic tools (future MCP server enhancement)
