"""NetBox API client — Python wrapper for common netbox MCP operations.

Usage:
    from servers.netbox import client
    device = client.get_device("nl-pve01")
    vms = client.search("virtual-machines", site="nl")
    ip = client.get_ip("10.0.181.X")
"""

import json
import os
import subprocess
import sys


class NetBoxClient:
    """Wraps NetBox REST API calls as Python functions.

    Uses the NetBox API directly (same credentials as the MCP server)
    to avoid MCP round-trip overhead when chaining multiple lookups.
    """

    def __init__(self):
        self.base_url = os.environ.get(
            "NETBOX_URL", "https://netbox.example.net"
        )
        self.token = os.environ.get("NETBOX_TOKEN", "")
        if not self.token:
            # Try reading from .env
            env_path = os.path.expanduser(
                "~/gitlab/n8n/claude-gateway/.env"
            )
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        if line.startswith("NETBOX_TOKEN="):
                            self.token = line.strip().split("=", 1)[1].strip("\"'")

    def _api(self, endpoint, params=None):
        """Make a NetBox API call and return parsed JSON."""
        import urllib.request
        import ssl

        url = f"{self.base_url}/api/{endpoint}/"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url += f"?{query}"

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Token {self.token}")
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode())

    def get_device(self, name):
        """Look up a device by name. Returns dict or None."""
        data = self._api("dcim/devices", {"name": name})
        results = data.get("results", [])
        return results[0] if results else None

    def get_vm(self, name):
        """Look up a virtual machine by name. Returns dict or None."""
        data = self._api("virtualization/virtual-machines", {"name": name})
        results = data.get("results", [])
        return results[0] if results else None

    def get_ip(self, address):
        """Look up an IP address. Returns dict or None."""
        data = self._api("ipam/ip-addresses", {"address": address})
        results = data.get("results", [])
        return results[0] if results else None

    def search(self, object_type, **filters):
        """Generic search. object_type: devices, virtual-machines, ip-addresses, vlans, etc.

        Maps to NetBox API endpoints:
          devices       -> dcim/devices
          virtual-machines -> virtualization/virtual-machines
          ip-addresses  -> ipam/ip-addresses
          vlans         -> ipam/vlans
          interfaces    -> dcim/interfaces
          cables        -> dcim/cables
        """
        type_map = {
            "devices": "dcim/devices",
            "virtual-machines": "virtualization/virtual-machines",
            "ip-addresses": "ipam/ip-addresses",
            "vlans": "ipam/vlans",
            "interfaces": "dcim/interfaces",
            "cables": "dcim/cables",
        }
        endpoint = type_map.get(object_type, object_type)
        data = self._api(endpoint, filters)
        return data.get("results", [])

    def get_device_interfaces(self, device_name):
        """Get all interfaces for a device."""
        return self.search("interfaces", device=device_name)

    def get_site_devices(self, site_slug):
        """Get all devices at a site (e.g., 'nl', 'gr')."""
        return self.search("devices", site=site_slug)

    def get_vlan(self, vid, site=None):
        """Look up a VLAN by ID, optionally filtered by site."""
        params = {"vid": vid}
        if site:
            params["site"] = site
        return self.search("vlans", **params)
