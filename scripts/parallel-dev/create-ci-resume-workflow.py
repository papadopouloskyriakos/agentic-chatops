#!/usr/bin/env python3
"""Create the 'NL - ChatDevOps CI Resume' workflow in n8n.
Webhook trigger on GitLab pipeline_events; parses payload + invokes pipeline-resume.sh via SSH.
INACTIVE by default."""
import json
import os
import sys
import urllib.request
import urllib.error


def make_workflow() -> dict:
    nodes = [
        {
            "id": "ci-resume-webhook",
            "name": "Pipeline Events Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [240, 300],
            "parameters": {
                "httpMethod": "POST",
                "path": "gitlab-pipeline-events",
                "responseMode": "responseNode",
                "options": {},
            },
        },
        {
            "id": "parse-pipeline",
            "name": "Parse Pipeline Payload",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [460, 300],
            "parameters": {
                "jsCode": """// GitLab pipeline_events payload: {object_kind: 'pipeline', object_attributes: {id, ref, status, web_url}, ...}
const body = $('Pipeline Events Webhook').first().json.body || $('Pipeline Events Webhook').first().json;
if (body.object_kind !== 'pipeline') {
  return [{ json: { skip: true, reason: 'not a pipeline event' } }];
}
const oa = body.object_attributes || {};
// Only care about terminal statuses (success / failed / canceled)
if (!['success', 'failed', 'canceled'].includes(oa.status)) {
  return [{ json: { skip: true, reason: 'non-terminal status: ' + oa.status } }];
}
return [{ json: {
  pipeline_id: oa.id,
  branch: oa.ref,
  status: oa.status,
  pipeline_url: oa.web_url || '',
  skip: false,
} }];"""
            },
        },
        {
            "id": "resume-worker",
            "name": "Resume Worker",
            "type": "n8n-nodes-base.ssh",
            "typeVersion": 1,
            "position": [680, 300],
            "parameters": {
                "authentication": "privateKey",
                "command": "={{ ($('Parse Pipeline Payload').first().json.skip) ? ('echo \"skip: ' + $('Parse Pipeline Payload').first().json.reason + '\"') : ('/home/app-user/gateway-state/bin/pipeline-resume.sh ' + $('Parse Pipeline Payload').first().json.pipeline_id + ' ' + $('Parse Pipeline Payload').first().json.branch + ' ' + $('Parse Pipeline Payload').first().json.status + ' ' + $('Parse Pipeline Payload').first().json.pipeline_url) }}",
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
            "id": "respond",
            "name": "Respond",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1,
            "position": [900, 300],
            "parameters": {
                "respondWith": "text",
                "responseBody": "={{ $('Resume Worker').first().json.stdout || 'ok' }}",
            },
        },
    ]
    connections = {
        "Pipeline Events Webhook": {"main": [[{"node": "Parse Pipeline Payload", "type": "main", "index": 0}]]},
        "Parse Pipeline Payload": {"main": [[{"node": "Resume Worker", "type": "main", "index": 0}]]},
        "Resume Worker": {"main": [[{"node": "Respond", "type": "main", "index": 0}]]},
    }
    return {
        "name": "NL - ChatDevOps CI Resume",
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
        headers={"X-N8N-API-KEY": token, "Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.load(r)
            print(f"Created: id={result['id']}, name='{result['name']}', active={result.get('active')}")
            print(f"  Webhook: POST https://n8n.example.net/webhook/gitlab-pipeline-events")
    except urllib.error.HTTPError as e:
        print(f"ERROR {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
