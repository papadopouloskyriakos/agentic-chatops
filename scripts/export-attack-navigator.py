#!/usr/bin/env python3
"""Export MITRE ATT&CK Navigator layer from mitre-mapping.json.
Output: docs/attack-navigator-layer.json
View at: https://mitre-attack.github.io/attack-navigator/ (Open Existing Layer → Upload)
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPING = os.path.join(REPO, "openclaw/skills/security-triage/mitre-mapping.json")
OUTPUT = os.path.join(REPO, "docs/attack-navigator-layer.json")

# ATT&CK technique → tactic mapping (required by Navigator for sub-techniques)
TECHNIQUE_TACTICS = {
    "T1110": "credential-access",
    "T1110.001": "credential-access",
    "T1190": "initial-access",
    "T1595": "reconnaissance",
    "T1595.002": "reconnaissance",
    "T1083": "discovery",
    "T1590.005": "reconnaissance",
    "T1189": "initial-access",
    "T1498": "impact",
    "T1499": "impact",
    "T1505.003": "persistence",
    "T1078": "initial-access",
    "T1566": "initial-access",
    "T1046": "discovery",
    "T1557": "credential-access",
    "T1557.002": "credential-access",
    "T1203": "execution",
    "T1059": "execution",
    "T1090": "command-and-control",
    "T1552.001": "credential-access",
    "T1496": "impact",
    "T1485": "impact",
}

with open(MAPPING) as f:
    mapping = json.load(f)

# Collect unique techniques with scenario counts
technique_scenarios = {}
for scenario, data in mapping.items():
    if isinstance(data, str):
        continue  # skip _comment keys
    for t in data.get("techniques", []):
        if t not in technique_scenarios:
            technique_scenarios[t] = []
        technique_scenarios[t].append(scenario.replace("crowdsecurity/", ""))

# Build Navigator technique entries — one per technique-tactic pair
techniques = []
for tid, scenarios in technique_scenarios.items():
    tactic = TECHNIQUE_TACTICS.get(tid, "")
    techniques.append({
        "techniqueID": tid,
        "tactic": tactic,
        "color": "#66ff33" if len(scenarios) >= 3 else "#99ff66" if len(scenarios) >= 2 else "#ccff99",
        "comment": "Detected by: " + ", ".join(scenarios),
        "enabled": True,
        "score": len(scenarios),
        "showSubtechniques": "." in tid
    })

layer = {
    "name": "ChatSecOps Detection Coverage",
    "versions": {"attack": "16", "navigator": "5.0.1", "layer": "4.5"},
    "domain": "enterprise-attack",
    "description": f"CrowdSec + scanner detection coverage. {len(technique_scenarios)} techniques from {len(mapping)} scenarios. Auto-generated from mitre-mapping.json.",
    "techniques": techniques,
    "gradient": {"colors": ["#a1d99b", "#31a354", "#006d2c"], "minValue": 1, "maxValue": 5},
    "legendItems": [
        {"label": "1 scenario", "color": "#a1d99b"},
        {"label": "2-3 scenarios", "color": "#31a354"},
        {"label": "4+ scenarios", "color": "#006d2c"}
    ],
    "showTacticRowBackground": True,
    "tacticRowBackground": "#dddddd",
    "selectTechniquesAcrossTactics": False,
    "hideDisabled": False,
    "layout": {
        "layout": "flat",
        "aggregateFunction": "average",
        "showID": True,
        "showName": True,
        "showAggregateScores": False,
        "countUnscored": False,
        "expandedSubtechniques": "annotated"
    }
}

with open(OUTPUT, "w") as f:
    json.dump(layer, f, indent=2)

print(f"Exported {len(techniques)} techniques from {len(mapping)} scenarios to {OUTPUT}")
