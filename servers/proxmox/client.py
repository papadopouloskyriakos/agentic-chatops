"""Proxmox VE API client — Python wrapper for common proxmox MCP operations.

Usage:
    from servers.proxmox import client
    nodes = client.list_nodes()
    vms = client.list_vms("nl-pve01")
    status = client.guest_status("nl-pve01", VMID_REDACTED)
"""

import json
import os
import ssl
import urllib.request


class ProxmoxClient:
    """Wraps Proxmox VE REST API calls as Python functions.

    Uses the same API tokens as the MCP server. Reads from environment
    or .env file for credentials.
    """

    def __init__(self):
        self.nodes = {}
        self._load_config()

    def _load_config(self):
        """Load PVE API endpoints and tokens from environment."""
        # Default NL nodes
        self.nodes = {
            "nl-pve01": {
                "url": os.environ.get(
                    "PVE_NL_PVE01_URL",
                    "https://nl-pve01.example.net:8006",
                ),
                "token": os.environ.get("PVE_NL_PVE01_TOKEN", ""),
            },
            "nl-pve02": {
                "url": os.environ.get(
                    "PVE_NL_PVE02_URL",
                    "https://nl-pve02.example.net:8006",
                ),
                "token": os.environ.get("PVE_NL_PVE02_TOKEN", ""),
            },
            "nl-pve03": {
                "url": os.environ.get(
                    "PVE_NL_PVE03_URL",
                    "https://nl-pve03.example.net:8006",
                ),
                "token": os.environ.get("PVE_NL_PVE03_TOKEN", ""),
            },
        }

    def _api(self, node, endpoint):
        """Make a Proxmox API call."""
        cfg = self.nodes.get(node)
        if not cfg:
            raise ValueError(f"Unknown node: {node}")

        url = f"{cfg['url']}/api2/json/{endpoint}"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"PVEAPIToken={cfg['token']}")

        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode()).get("data", {})

    def list_nodes(self):
        """List all configured PVE nodes."""
        return list(self.nodes.keys())

    def list_vms(self, node):
        """List all QEMU VMs on a node."""
        return self._api(node, f"nodes/{node}/qemu")

    def list_lxc(self, node):
        """List all LXC containers on a node."""
        return self._api(node, f"nodes/{node}/lxc")

    def guest_status(self, node, vmid):
        """Get status of a specific guest (VM or LXC)."""
        # Try QEMU first, then LXC
        try:
            return self._api(node, f"nodes/{node}/qemu/{vmid}/status/current")
        except Exception:
            return self._api(node, f"nodes/{node}/lxc/{vmid}/status/current")

    def node_status(self, node):
        """Get node resource usage (CPU, memory, disk)."""
        return self._api(node, f"nodes/{node}/status")
