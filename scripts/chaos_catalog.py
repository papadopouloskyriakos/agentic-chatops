#!/usr/bin/env python3
"""Chaos Engineering -- Declarative experiment catalog loader.

Reads experiments/catalog.yaml and provides the same interface as the
hardcoded BASELINE_TEST_MATRIX and CHAOS_TUNNELS dicts, enabling
Chaos Toolkit (CT-1) and Azure Chaos Studio (AZ-1) compliance.

Usage:
  # Validate catalog
  python3 chaos_catalog.py validate

  # List experiments
  python3 chaos_catalog.py list [--category wan-failover] [--tier primary]

  # List target capabilities (AZ-1)
  python3 chaos_catalog.py list-capabilities

  # Export Chaos Toolkit experiment JSON
  python3 chaos_catalog.py export-ct <experiment-id>
"""
import json
import os
import sys

# Try yaml import -- fallback to manual parse if not available
try:
    import yaml
except ImportError:
    yaml = None

CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "catalog.yaml"
)

_catalog_cache = None


def _parse_yaml_fallback(path):
    """Minimal YAML parser for simple structures when PyYAML unavailable."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c",
         f"import json; exec(open('{path}').read()); print('ERROR: needs yaml')"],
        capture_output=True, text=True, timeout=5,
    )
    raise ImportError("PyYAML required: pip install pyyaml")


def load_catalog(path=None):
    """Load and cache the experiment catalog from YAML."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache

    path = path or CATALOG_PATH
    if not os.path.exists(path):
        return None

    if yaml is None:
        raise ImportError("PyYAML required for catalog: pip install pyyaml")

    with open(path) as f:
        _catalog_cache = yaml.safe_load(f)
    return _catalog_cache


def get_experiment(experiment_id):
    """Get a single experiment by ID."""
    catalog = load_catalog()
    if not catalog:
        return None
    for exp in catalog.get("experiments", []):
        if exp.get("id") == experiment_id:
            return exp
    return None


def list_experiments(category=None, tier=None, frequency=None):
    """List experiments with optional filters."""
    catalog = load_catalog()
    if not catalog:
        return []
    results = []
    for exp in catalog.get("experiments", []):
        if category and exp.get("category") != category:
            continue
        sched = exp.get("schedule", {})
        if tier and sched.get("tier") != tier:
            continue
        if frequency and sched.get("frequency") != frequency:
            continue
        results.append(exp)
    return results


def get_targets():
    """Get all target definitions (AZ-1 capability registration)."""
    catalog = load_catalog()
    if not catalog:
        return []
    return catalog.get("targets", [])


def get_target(target_id):
    """Get a target by ID."""
    for t in get_targets():
        if t.get("id") == target_id:
            return t
    return None


def list_capabilities():
    """List all targets with their capabilities (AZ-1)."""
    results = []
    for t in get_targets():
        results.append({
            "id": t["id"],
            "type": t["type"],
            "site": t.get("site", ""),
            "capabilities": t.get("capabilities", []),
        })
    return results


def get_contributions():
    """Get CT contributions block."""
    catalog = load_catalog()
    if not catalog:
        return {}
    return catalog.get("contributions", {})


def get_domain_slos():
    """Get domain SLO definitions."""
    catalog = load_catalog()
    if not catalog:
        return {}
    return catalog.get("domain_slos", {})


def validate_safety(experiment):
    """Validate safety constraints for an experiment."""
    safety = experiment.get("safety", {})
    errors = []

    if not safety.get("max_duration"):
        errors.append(f"{experiment['id']}: missing max_duration")

    if safety.get("max_duration", 0) > 600:
        errors.append(f"{experiment['id']}: max_duration {safety['max_duration']} exceeds 600s limit")

    return errors


def validate_catalog(path=None):
    """Validate the entire catalog. Returns list of errors."""
    catalog = load_catalog(path)
    if not catalog:
        return ["Catalog file not found or empty"]

    errors = []

    # Check version
    if catalog.get("version") != "1.0":
        errors.append(f"Unknown catalog version: {catalog.get('version')}")

    # Check contributions (CT requirement)
    contribs = catalog.get("contributions", {})
    for key in ("reliability", "availability", "performance", "security"):
        if key not in contribs:
            errors.append(f"Missing contribution: {key}")

    # Check targets
    target_ids = set()
    for t in catalog.get("targets", []):
        if "id" not in t:
            errors.append("Target missing 'id'")
        elif t["id"] in target_ids:
            errors.append(f"Duplicate target ID: {t['id']}")
        else:
            target_ids.add(t["id"])
        if not t.get("capabilities"):
            errors.append(f"Target {t.get('id', '?')} has no capabilities")

    # Check experiments
    exp_ids = set()
    for exp in catalog.get("experiments", []):
        eid = exp.get("id", "")
        if not eid:
            errors.append("Experiment missing 'id'")
            continue
        if eid in exp_ids:
            errors.append(f"Duplicate experiment ID: {eid}")
        exp_ids.add(eid)

        if not exp.get("title"):
            errors.append(f"{eid}: missing title")

        # Validate method exists
        method = exp.get("method")
        if not method:
            errors.append(f"{eid}: missing method")

        # Validate rollbacks exist
        if not exp.get("rollbacks"):
            errors.append(f"{eid}: missing rollbacks (CT requires explicit rollback)")

        # Validate safety
        errors.extend(validate_safety(exp))

        # Validate method targets reference known targets
        if isinstance(method, list):
            for action in method:
                target = action.get("target", "")
                if target and target not in target_ids:
                    errors.append(f"{eid}: method references unknown target '{target}'")
        elif isinstance(method, dict) and "steps" in method:
            for step in method["steps"]:
                for branch in step.get("branches", []):
                    for action in branch.get("actions", []):
                        target = action.get("target", "")
                        if target and target not in target_ids:
                            errors.append(f"{eid}: method references unknown target '{target}'")

    return errors


def export_chaostoolkit_experiment(experiment_id):
    """Export an experiment as Chaos Toolkit-compatible JSON."""
    exp = get_experiment(experiment_id)
    if not exp:
        return None

    # Build CT steady-state hypothesis
    hypothesis = exp.get("steady_state_hypothesis", {})
    ct_probes = []
    for probe in hypothesis.get("probes", []):
        ct_probes.append({
            "type": "probe",
            "name": f"{probe['type']}-check",
            "tolerance": probe.get("tolerance", {}),
            "provider": {
                "type": "python",
                "module": "chaos_catalog",
                "func": f"probe_{probe['type']}",
                "arguments": {k: v for k, v in probe.items() if k not in ("type", "tolerance")},
            },
        })

    # Build CT method
    ct_method = []
    method = exp.get("method", [])
    if isinstance(method, list):
        for action in method:
            ct_method.append({
                "type": "action",
                "name": f"{action['type']}-{action.get('target', '')}",
                "provider": {
                    "type": "python",
                    "module": "chaos_catalog",
                    "func": f"action_{action['type'].replace('-', '_')}",
                    "arguments": {k: v for k, v in action.items() if k != "type"},
                },
            })

    # Build CT rollbacks
    ct_rollbacks = []
    for rb in exp.get("rollbacks", []):
        ct_rollbacks.append({
            "type": "action",
            "name": f"rollback-{rb['type']}-{rb.get('target', '')}",
            "provider": {
                "type": "python",
                "module": "chaos_catalog",
                "func": f"action_{rb['type'].replace('-', '_')}",
                "arguments": {k: v for k, v in rb.items() if k != "type"},
            },
        })

    return {
        "title": exp["title"],
        "description": exp.get("description", ""),
        "contributions": get_contributions(),
        "steady-state-hypothesis": {
            "title": hypothesis.get("title", ""),
            "probes": ct_probes,
        },
        "method": ct_method,
        "rollbacks": ct_rollbacks,
    }


def to_baseline_test_matrix():
    """Convert catalog to legacy BASELINE_TEST_MATRIX format for backward compat."""
    matrix = []
    for exp in list_experiments():
        method = exp.get("method", [])
        if isinstance(method, list) and len(method) == 1:
            action = method[0]
            if action.get("type") == "asa-tunnel-shutdown":
                pair = action.get("tunnel_pair", [])
                if len(pair) == 2:
                    matrix.append({
                        "type": "tunnel",
                        "tunnel": pair[0],
                        "wan": pair[1],
                        "label": exp["title"],
                    })
            elif action.get("type") == "docker-compose-stop":
                matrix.append({
                    "type": "dmz" if not action.get("services") or len(action["services"]) > 1 else "container",
                    "host": action["target"],
                    "container": action["services"][0] if len(action.get("services", [])) == 1 else None,
                    "label": exp["title"],
                })
        elif isinstance(method, dict) and "steps" in method:
            matrix.append({
                "type": "combined",
                "label": exp["title"],
            })
    return matrix


def to_chaos_tunnels():
    """Convert catalog targets+experiments to legacy CHAOS_TUNNELS format."""
    tunnels = {}
    for exp in list_experiments(category="wan-failover"):
        method = exp.get("method", [])
        if isinstance(method, list):
            for action in method:
                pair = action.get("tunnel_pair", [])
                if len(pair) == 2:
                    key = (pair[0], pair[1])
                    tunnels[key] = {
                        "asa": "nl" if "nl" in action.get("target", "") else "gr",
                        "interface": action.get("interface", ""),
                        "failover_via": exp.get("description", ""),
                    }
    return tunnels


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Chaos experiment catalog manager")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("validate", help="Validate catalog.yaml")
    list_p = sub.add_parser("list", help="List experiments")
    list_p.add_argument("--category", help="Filter by category")
    list_p.add_argument("--tier", help="Filter by tier")
    sub.add_parser("list-capabilities", help="List target capabilities (AZ-1)")
    export_p = sub.add_parser("export-ct", help="Export Chaos Toolkit experiment JSON")
    export_p.add_argument("experiment_id", help="Experiment ID to export")
    sub.add_parser("legacy-matrix", help="Show legacy BASELINE_TEST_MATRIX format")

    args = parser.parse_args()

    if args.command == "validate":
        errors = validate_catalog()
        if errors:
            print(f"FAIL: {len(errors)} errors:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)
        catalog = load_catalog()
        n_targets = len(catalog.get("targets", []))
        n_exps = len(catalog.get("experiments", []))
        print(f"OK: {n_exps} experiments, {n_targets} targets, 0 errors")

    elif args.command == "list":
        for exp in list_experiments(category=args.category, tier=args.tier):
            sched = exp.get("schedule", {})
            print(f"  {exp['id']:40s} [{exp.get('category', ''):20s}] "
                  f"{sched.get('frequency', '-'):12s} {sched.get('tier', '-')}")

    elif args.command == "list-capabilities":
        for cap in list_capabilities():
            caps = ", ".join(cap["capabilities"])
            print(f"  {cap['id']:20s} [{cap['type']:20s}] {cap['site']:4s} {caps}")

    elif args.command == "export-ct":
        ct = export_chaostoolkit_experiment(args.experiment_id)
        if not ct:
            print(f"Experiment '{args.experiment_id}' not found", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(ct, indent=2))

    elif args.command == "legacy-matrix":
        for entry in to_baseline_test_matrix():
            print(f"  {entry}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
