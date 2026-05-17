#!/usr/bin/env node
// mcp-proxmox — Thin MCP server for Proxmox VE API
// Tools: node/VM/LXC discovery, status, config, lifecycle (start/stop/reboot)

// Self-signed cert support — must be set before any imports that use fetch
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Proxmox API client
// ---------------------------------------------------------------------------

const PVE_HOST = process.env.PVE_HOST || "nl-pve01";
const PVE_PORT = process.env.PVE_PORT || "8006";
const PVE_TOKEN_ID = process.env.PVE_TOKEN_ID || "root@pam!mcp";
const PVE_TOKEN_SECRET = process.env.PVE_TOKEN_SECRET || "";
const PVE_NODES = (process.env.PVE_NODES || "nl-pve01,nl-pve02,nl-pve03").split(",");

async function pveApi(path, { method = "GET", node, body } = {}) {
  const host = node || PVE_HOST;
  const url = `https://${host}:${PVE_PORT}/api2/json${path}`;
  const headers = {
    Authorization: `PVEAPIToken=${PVE_TOKEN_ID}=${PVE_TOKEN_SECRET}`,
    "Content-Type": "application/json",
  };

  const opts = { method, headers };
  if (body && method === "POST") {
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(url, opts);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PVE API ${method} ${path} on ${host}: ${res.status} ${text}`);
  }
  const json = await res.json();
  return json.data;
}

// Helper: find which PVE host owns a VMID
async function findVmNode(vmid) {
  for (const node of PVE_NODES) {
    try {
      // Try LXC first
      const lxcs = await pveApi(`/nodes/${node}/lxc`, { node });
      if (lxcs.some((c) => String(c.vmid) === String(vmid))) {
        return { node, type: "lxc" };
      }
      // Try QEMU
      const vms = await pveApi(`/nodes/${node}/qemu`, { node });
      if (vms.some((v) => String(v.vmid) === String(vmid))) {
        return { node, type: "qemu" };
      }
    } catch {
      continue;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

const server = new McpServer({
  name: "mcp-proxmox",
  version: "1.0.0",
});

// --- Discovery tools ---

server.tool(
  "pve_cluster_status",
  "Get Proxmox cluster status and quorum info",
  {},
  async () => {
    const data = await pveApi("/cluster/status");
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

server.tool(
  "pve_list_nodes",
  "List all nodes in the Proxmox cluster with CPU, memory, uptime",
  {},
  async () => {
    const data = await pveApi("/nodes");
    const summary = data.map((n) => ({
      node: n.node,
      status: n.status,
      cpu: `${(n.cpu * 100).toFixed(1)}%`,
      mem: `${((n.mem / n.maxmem) * 100).toFixed(1)}% (${(n.mem / 1e9).toFixed(1)}/${(n.maxmem / 1e9).toFixed(1)} GB)`,
      uptime: `${(n.uptime / 86400).toFixed(1)} days`,
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

server.tool(
  "pve_node_status",
  "Get detailed status for a specific node (CPU, memory, load, kernel, PVE version)",
  { node: z.string().describe("PVE node name, e.g. nl-pve01") },
  async ({ node }) => {
    const data = await pveApi(`/nodes/${node}/status`, { node });
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);

server.tool(
  "pve_list_lxc",
  "List all LXC containers on a node with status, CPU, memory",
  { node: z.string().describe("PVE node name") },
  async ({ node }) => {
    const data = await pveApi(`/nodes/${node}/lxc`, { node });
    const summary = data.map((c) => ({
      vmid: c.vmid,
      name: c.name,
      status: c.status,
      cpu: c.cpus,
      mem: `${(c.mem / 1e6).toFixed(0)}/${(c.maxmem / 1e6).toFixed(0)} MB`,
      disk: `${(c.disk / 1e9).toFixed(1)}/${(c.maxdisk / 1e9).toFixed(1)} GB`,
      uptime: c.uptime ? `${(c.uptime / 3600).toFixed(1)}h` : "stopped",
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

server.tool(
  "pve_list_vms",
  "List all QEMU VMs on a node with status, CPU, memory",
  { node: z.string().describe("PVE node name") },
  async ({ node }) => {
    const data = await pveApi(`/nodes/${node}/qemu`, { node });
    const summary = data.map((v) => ({
      vmid: v.vmid,
      name: v.name,
      status: v.status,
      cpu: v.cpus,
      mem: `${(v.mem / 1e6).toFixed(0)}/${(v.maxmem / 1e6).toFixed(0)} MB`,
      disk: `${(v.disk / 1e9).toFixed(1)}/${(v.maxdisk / 1e9).toFixed(1)} GB`,
      uptime: v.uptime ? `${(v.uptime / 3600).toFixed(1)}h` : "stopped",
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

// --- Config tools ---

server.tool(
  "pve_lxc_config",
  "Get full LXC container configuration (current running config). Finds the node automatically.",
  { vmid: z.number().describe("Container VMID") },
  async ({ vmid }) => {
    const loc = await findVmNode(vmid);
    if (!loc || loc.type !== "lxc") {
      return { content: [{ type: "text", text: `LXC ${vmid} not found on any node` }] };
    }
    const data = await pveApi(`/nodes/${loc.node}/lxc/${vmid}/config`, { node: loc.node });
    return {
      content: [{ type: "text", text: `LXC ${vmid} on ${loc.node}:\n${JSON.stringify(data, null, 2)}` }],
    };
  }
);

server.tool(
  "pve_vm_config",
  "Get full QEMU VM configuration (current running config). Finds the node automatically.",
  { vmid: z.number().describe("VM VMID") },
  async ({ vmid }) => {
    const loc = await findVmNode(vmid);
    if (!loc || loc.type !== "qemu") {
      return { content: [{ type: "text", text: `VM ${vmid} not found on any node` }] };
    }
    const data = await pveApi(`/nodes/${loc.node}/qemu/${vmid}/config`, { node: loc.node });
    return {
      content: [{ type: "text", text: `VM ${vmid} on ${loc.node}:\n${JSON.stringify(data, null, 2)}` }],
    };
  }
);

server.tool(
  "pve_guest_config",
  "Get config for any VMID (auto-detects LXC vs QEMU, finds node automatically)",
  { vmid: z.number().describe("VMID (LXC or QEMU)") },
  async ({ vmid }) => {
    const loc = await findVmNode(vmid);
    if (!loc) {
      return { content: [{ type: "text", text: `VMID ${vmid} not found on any node` }] };
    }
    const path =
      loc.type === "lxc"
        ? `/nodes/${loc.node}/lxc/${vmid}/config`
        : `/nodes/${loc.node}/qemu/${vmid}/config`;
    const data = await pveApi(path, { node: loc.node });
    return {
      content: [
        {
          type: "text",
          text: `${loc.type.toUpperCase()} ${vmid} on ${loc.node}:\n${JSON.stringify(data, null, 2)}`,
        },
      ],
    };
  }
);

// --- Status tools ---

server.tool(
  "pve_guest_status",
  "Get runtime status for any VMID (auto-detects LXC vs QEMU, finds node). Returns status, CPU, memory, uptime, PID.",
  { vmid: z.number().describe("VMID (LXC or QEMU)") },
  async ({ vmid }) => {
    const loc = await findVmNode(vmid);
    if (!loc) {
      return { content: [{ type: "text", text: `VMID ${vmid} not found on any node` }] };
    }
    const path =
      loc.type === "lxc"
        ? `/nodes/${loc.node}/lxc/${vmid}/status/current`
        : `/nodes/${loc.node}/qemu/${vmid}/status/current`;
    const data = await pveApi(path, { node: loc.node });
    return {
      content: [
        {
          type: "text",
          text: `${loc.type.toUpperCase()} ${vmid} on ${loc.node}:\n${JSON.stringify(data, null, 2)}`,
        },
      ],
    };
  }
);

// --- Lifecycle tools (guarded) ---

const ALLOW_LIFECYCLE = process.env.PVE_ALLOW_LIFECYCLE === "true";

async function lifecycleAction(vmid, action) {
  if (!ALLOW_LIFECYCLE) {
    return {
      content: [
        {
          type: "text",
          text: `Lifecycle operations disabled. Set PVE_ALLOW_LIFECYCLE=true to enable start/stop/reboot.`,
        },
      ],
    };
  }
  const loc = await findVmNode(vmid);
  if (!loc) {
    return { content: [{ type: "text", text: `VMID ${vmid} not found on any node` }] };
  }
  const path =
    loc.type === "lxc"
      ? `/nodes/${loc.node}/lxc/${vmid}/status/${action}`
      : `/nodes/${loc.node}/qemu/${vmid}/status/${action}`;
  const data = await pveApi(path, { node: loc.node, method: "POST" });
  return {
    content: [
      {
        type: "text",
        text: `${action.toUpperCase()} ${loc.type.toUpperCase()} ${vmid} on ${loc.node}: task ${data || "submitted"}`,
      },
    ],
  };
}

server.tool(
  "pve_start",
  "Start a stopped VM or LXC container. Requires PVE_ALLOW_LIFECYCLE=true.",
  { vmid: z.number().describe("VMID to start") },
  async ({ vmid }) => lifecycleAction(vmid, "start")
);

server.tool(
  "pve_stop",
  "Force-stop a VM or LXC container. Requires PVE_ALLOW_LIFECYCLE=true.",
  { vmid: z.number().describe("VMID to stop") },
  async ({ vmid }) => lifecycleAction(vmid, "stop")
);

server.tool(
  "pve_shutdown",
  "Gracefully shutdown a VM or LXC container. Requires PVE_ALLOW_LIFECYCLE=true.",
  { vmid: z.number().describe("VMID to shutdown") },
  async ({ vmid }) => lifecycleAction(vmid, "shutdown")
);

server.tool(
  "pve_reboot",
  "Reboot a VM or LXC container. Requires PVE_ALLOW_LIFECYCLE=true.",
  { vmid: z.number().describe("VMID to reboot") },
  async ({ vmid }) => lifecycleAction(vmid, "reboot")
);

// --- Task tools ---

server.tool(
  "pve_node_tasks",
  "List recent tasks on a node (deployments, migrations, backups, etc.)",
  {
    node: z.string().describe("PVE node name"),
    limit: z.number().optional().default(10).describe("Number of tasks to return"),
  },
  async ({ node, limit }) => {
    const data = await pveApi(`/nodes/${node}/tasks?limit=${limit}`, { node });
    const summary = data.map((t) => ({
      upid: t.upid,
      type: t.type,
      status: t.status,
      user: t.user,
      starttime: new Date(t.starttime * 1000).toISOString(),
      endtime: t.endtime ? new Date(t.endtime * 1000).toISOString() : "running",
      vmid: t.id || "",
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

server.tool(
  "pve_storage",
  "List storage pools on a node with usage",
  { node: z.string().describe("PVE node name") },
  async ({ node }) => {
    const data = await pveApi(`/nodes/${node}/storage`, { node });
    const summary = data.map((s) => ({
      storage: s.storage,
      type: s.type,
      status: s.active ? "active" : "inactive",
      used: `${((s.used || 0) / 1e9).toFixed(1)} GB`,
      total: `${((s.total || 0) / 1e9).toFixed(1)} GB`,
      pct: s.total ? `${(((s.used || 0) / s.total) * 100).toFixed(1)}%` : "N/A",
      content: s.content,
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

const transport = new StdioServerTransport();
await server.connect(transport);
