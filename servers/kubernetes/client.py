"""Kubernetes client — Python wrapper for kubectl operations.

Usage:
    from servers.kubernetes import client
    pods = client.get_pods("monitoring", context="nl")
    unhealthy = client.get_unhealthy_pods(context="nl")
    nodes = client.get_nodes(context="nl")
"""

import json
import subprocess


class K8sClient:
    """Wraps kubectl commands as Python functions.

    Uses kubeconfig contexts (nl, gr) already configured on the host.
    All operations are read-only (no mutations via code orchestration).
    """

    def _kubectl(self, args, context="nl"):
        """Run a kubectl command and return parsed output."""
        cmd = ["kubectl", f"--context={context}", "-o", "json"] + args
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def get_pods(self, namespace=None, context="nl"):
        """Get pods, optionally filtered by namespace."""
        args = ["get", "pods"]
        if namespace:
            args += ["-n", namespace]
        else:
            args += ["-A"]
        return self._kubectl(args, context)

    def get_unhealthy_pods(self, context="nl"):
        """Get pods not in Running/Succeeded state."""
        args = [
            "get", "pods", "-A",
            "--field-selector=status.phase!=Running,status.phase!=Succeeded",
        ]
        return self._kubectl(args, context)

    def get_nodes(self, context="nl"):
        """Get all cluster nodes with status."""
        return self._kubectl(["get", "nodes"], context)

    def get_deployments(self, namespace=None, context="nl"):
        """Get deployments, optionally filtered by namespace."""
        args = ["get", "deployments"]
        if namespace:
            args += ["-n", namespace]
        else:
            args += ["-A"]
        return self._kubectl(args, context)

    def describe(self, resource_type, name, namespace=None, context="nl"):
        """Describe a resource (returns text, not JSON)."""
        cmd = ["kubectl", f"--context={context}", "describe", resource_type, name]
        if namespace:
            cmd += ["-n", namespace]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout if result.returncode == 0 else result.stderr

    def get_events(self, namespace=None, context="nl"):
        """Get recent events, optionally filtered by namespace."""
        args = ["get", "events", "--sort-by=.lastTimestamp"]
        if namespace:
            args += ["-n", namespace]
        else:
            args += ["-A"]
        return self._kubectl(args, context)

    def top_pods(self, namespace=None, context="nl"):
        """Get pod resource usage (requires metrics-server)."""
        cmd = ["kubectl", f"--context={context}", "top", "pods"]
        if namespace:
            cmd += ["-n", namespace]
        else:
            cmd += ["-A"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout if result.returncode == 0 else result.stderr

    def top_nodes(self, context="nl"):
        """Get node resource usage."""
        cmd = ["kubectl", f"--context={context}", "top", "nodes"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout if result.returncode == 0 else result.stderr
