// Self-test for the proxmox MCP node resolver. No live cluster: a fake pveApi returns a topology where
// the target guest lives on a node the static PVE_NODES list never named (the real pve04 /
// gitlabrunner02 case). Run: `node mcp-proxmox/index.test.js` (exit 0 = pass, 1 = fail).
//
// THE BUG THIS PINS (2026-08-10): findVmNode iterated the static PVE_NODES env ("pve01,pve02,pve03") to
// auto-detect a guest's node. gitlabrunner02 (vmid VMID_REDACTED) is on pve04, absent from that list, so
// pve_start / pve_guest_status returned "VMID not found on any node" for a VM pve_list_vms could show
// when handed pve04 explicitly. The fix discovers nodes from the live cluster (/nodes). Killing mutation:
// revert resolverNodes to `return PVE_NODES` and the pve04 case below goes RED.
import { findVmNode, resolverNodes } from "./index.js";

let failures = 0;
function check(name, cond) {
  if (cond) {
    console.log(`  ok: ${name}`);
  } else {
    console.error(`  FAIL: ${name}`);
    failures++;
  }
}

// A cluster whose 4th node (pve04) is NOT in the process's PVE_NODES env — the exact stale-list shape.
function fakeApi(topology) {
  return async (path) => {
    if (path === "/nodes") return topology.nodes;
    const m = path.match(/^\/nodes\/([^/]+)\/(lxc|qemu)$/);
    if (m) {
      const [, node, kind] = m;
      return (topology.guests[node] || []).filter((g) => g.kind === kind);
    }
    throw new Error(`fakeApi: unexpected path ${path}`);
  };
}

const topo = {
  nodes: [
    { node: "nl-pve01", status: "online" },
    { node: "nl-pve02", status: "online" },
    { node: "nl-pve03", status: "online" },
    { node: "nlpve04", status: "online" }, // the node PVE_NODES never named
  ],
  guests: {
    "nlpve04": [{ vmid: VMID_REDACTED, kind: "qemu" }], // gitlabrunner02
    "nl-pve01": [{ vmid: VMID_REDACTED, kind: "qemu" }], // gitlabrunner01
  },
};

async function main() {
  // 1. The regression itself: a guest on a dynamically-discovered node resolves.
  const loc = await findVmNode(VMID_REDACTED, fakeApi(topo));
  check("guest on pve04 (outside PVE_NODES) is resolved", loc && loc.node === "nlpve04" && loc.type === "qemu");

  // 2. A known-node guest still resolves (no regression to the happy path).
  const loc1 = await findVmNode(VMID_REDACTED, fakeApi(topo));
  check("guest on a listed node still resolves", loc1 && loc1.node === "nl-pve01");

  // 3. A truly-absent vmid returns null, not a wrong node.
  const none = await findVmNode(999999999, fakeApi(topo));
  check("absent vmid resolves to null", none === null);

  // 4. resolverNodes prefers the live /nodes over the static list, and includes pve04.
  const nodes = await resolverNodes(fakeApi(topo));
  check("resolverNodes discovers pve04 from the cluster", nodes.includes("nlpve04"));

  // 5. Fallback: if /nodes is unreachable, resolution degrades to PVE_NODES rather than dying.
  const brokenApi = async (path) => {
    if (path === "/nodes") throw new Error("cluster unreachable");
    return [];
  };
  const fallback = await resolverNodes(brokenApi);
  check("resolverNodes falls back to the static list when /nodes fails", Array.isArray(fallback) && fallback.length > 0);

  if (failures) {
    console.error(`proxmox resolver self-test: FAIL (${failures})`);
    process.exit(1);
  }
  console.log("proxmox resolver self-test: PASS (5 checks)");
}

main();
