"""YouTrack API client — Python wrapper for common youtrack MCP operations.

Usage:
    from servers.youtrack import client
    issues = client.search("project: IFRNLLEI01PRD #Unresolved")
    issue = client.get_issue("IFRNLLEI01PRD-281")
    client.add_comment("IFRNLLEI01PRD-281", "Resolved via automated triage.")
"""

import json
import os
import ssl
import urllib.parse
import urllib.request


class YouTrackClient:
    """Wraps YouTrack REST API calls as Python functions."""

    def __init__(self):
        self.base_url = os.environ.get(
            "YOUTRACK_URL", "https://youtrack.example.net"
        )
        self.token = os.environ.get("YOUTRACK_TOKEN", "")
        if not self.token:
            env_path = os.path.expanduser(
                "~/gitlab/n8n/claude-gateway/.env"
            )
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        if line.startswith("YOUTRACK_TOKEN="):
                            self.token = line.strip().split("=", 1)[1].strip("\"'")

    def _api(self, endpoint, method="GET", data=None):
        """Make a YouTrack API call."""
        url = f"{self.base_url}/api/{endpoint}"

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/json")

        if data:
            req.add_header("Content-Type", "application/json")
            body = json.dumps(data).encode()
        else:
            body = None

        with urllib.request.urlopen(req, body, context=ctx) as resp:
            return json.loads(resp.read().decode()) if resp.read() else {}

    def search(self, query, fields=None, top=10):
        """Search issues using YouTrack query language."""
        params = f"query={urllib.parse.quote(query)}&$top={top}"
        if fields:
            params += f"&fields={fields}"
        else:
            params += "&fields=idReadable,summary,customFields(name,value(name))"
        return self._api(f"issues?{params}")

    def get_issue(self, issue_id, fields=None):
        """Get a specific issue by readable ID."""
        f = fields or "idReadable,summary,description,customFields(name,value(name))"
        return self._api(f"issues/{issue_id}?fields={f}")

    def add_comment(self, issue_id, text):
        """Add a comment to an issue."""
        return self._api(
            f"issues/{issue_id}/comments",
            method="POST",
            data={"text": text},
        )

    def update_state(self, issue_id, state_name):
        """Update the State custom field of an issue."""
        return self._api(
            f"issues/{issue_id}",
            method="POST",
            data={
                "customFields": [
                    {
                        "name": "State",
                        "$type": "StateIssueCustomField",
                        "value": {"name": state_name},
                    }
                ]
            },
        )

    def get_project_issues(self, project_short_name, query_extra="", top=25):
        """Get issues for a project with optional extra query."""
        query = f"project: {project_short_name}"
        if query_extra:
            query += f" {query_extra}"
        return self.search(query, top=top)
