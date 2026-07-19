#!/usr/bin/env python3
"""Create the minimal 'NL - ChatDevOps Planner' workflow in n8n.

Stays INACTIVE by default — operator manually activates after testing.
"""
import json
import os
import sys
import urllib.request
import urllib.error
import uuid


def make_workflow() -> dict:
    """Build a minimal Planner workflow (webhook → validate → SSH planner-decompose.py → respond)."""
    # Node IDs (stable, used in connections)
    n_webhook = "planner-webhook"
    n_validate = "validate-input"
    n_run = "run-planner"
    n_respond = "respond-webhook"

    nodes = [
        {
            "id": n_webhook,
            "name": "Planner Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [240, 300],
            "parameters": {
                "httpMethod": "POST",
                "path": "chatops-devops-planner",
                "responseMode": "responseNode",
                "options": {},
            },
        },
        {
            "id": n_validate,
            "name": "Validate Input",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [460, 300],
            "parameters": {
                "jsCode": """const body = $('Planner Webhook').first().json.body || $('Planner Webhook').first().json;
const featureId = body.featureId || body.feature_id || body.issueId || '';
const repoSlug = body.repoSlug || body.repo_slug || '';
const dryRun = !!body.dryRun || !!body.dry_run;

if (!/^[A-Z][A-Z0-9_]+-\\d+$/.test(featureId)) {
  return [{ json: { error: 'invalid featureId; expected like CUBEOS-1234', received: featureId } }];
}

return [{ json: { featureId, repoSlug, dryRun, valid: true } }];"""
            },
        },
        {
            "id": n_run,
            "name": "Run Planner",
            "type": "n8n-nodes-base.ssh",
            "typeVersion": 1,
            "position": [680, 300],
            "parameters": {
                "authentication": "privateKey",
                "command": "={{ ($('Validate Input').first().json.valid) ? (\n  '/home/app-user/gateway-state/bin/planner-decompose.py'\n  + ' --feature-id ' + $('Validate Input').first().json.featureId\n  + ($('Validate Input').first().json.repoSlug ? ' --repo-slug ' + $('Validate Input').first().json.repoSlug : '')\n  + ($('Validate Input').first().json.dryRun ? ' --dry-run' : '')\n  + ' --json'\n) : 'echo \"{\\\"error\\\":\\\"input validation failed\\\"}\" && exit 1' }}",
                "cwd": "/tmp",
            },
            "credentials": {
                "sshPrivateKey": {
                    "id": "REDACTED_SSH_CRED",
                    "name": "nl-claude01 - SSH app-user",
                }
            },
        },
        {
            "id": n_respond,
            "name": "Respond",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1,
            "position": [900, 300],
            "parameters": {
                "respondWith": "json",
                "responseBody": "={{ JSON.parse($('Run Planner').first().json.stdout || '{}') }}",
            },
        },
    ]

    connections = {
        "Planner Webhook": {"main": [[{"node": "Validate Input", "type": "main", "index": 0}]]},
        "Validate Input": {"main": [[{"node": "Run Planner", "type": "main", "index": 0}]]},
        "Run Planner": {"main": [[{"node": "Respond", "type": "main", "index": 0}]]},
    }

    return {
        "name": "NL - ChatDevOps Planner",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "staticData": None,
    }


def main() -> int:
    token = os.environ["N8N_API_KEY"]
    wf = make_workflow()
    req = urllib.request.Request(
        "https://n8n.example.net/api/v1/workflows",
        data=json.dumps(wf).encode(),
        headers={
            "X-N8N-API-KEY": token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.load(r)
            print(f"Created workflow: id={result['id']}, name='{result['name']}', active={result.get('active')}")
            print(f"  Webhook (when activated): POST https://n8n.example.net/webhook/chatops-devops-planner")
            print(f"  Test payload: {{'featureId': 'CUBEOS-9999', 'dryRun': true}}")
    except urllib.error.HTTPError as e:
        print(f"ERROR {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
