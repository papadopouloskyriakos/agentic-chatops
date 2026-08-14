#!/usr/bin/env python3
"""Chaos Engineering -- Parallel branch execution engine.

Implements Azure Chaos Studio step/branch/action model (AZ-2).
Steps execute sequentially; branches within a step execute in parallel.

Usage (from chaos-test.py):
    from chaos_parallel import execute_experiment_method, ChaosAbortError
"""
import datetime
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_script_dir, "lib"))
sys.path.insert(0, _script_dir)

from asa_ssh import (ssh_nl_asa_config, ssh_gr_asa_config, ssh_nl_asa_command,
                     ssh_gr_asa_command, SSH_OPTS_BASE)
from ios_ssh import sw01_port_shutdown, sw01_port_noshut


class ChaosAbortError(Exception):
    """Raised when a branch fails and experiment must abort."""
    pass


class BranchResult:
    """Result of a single branch execution."""
    def __init__(self, name, success=True, events=None, error=None):
        self.name = name
        self.success = success
        self.events = events or []
        self.error = error


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _execute_action(action):
    """Execute a single chaos action. Returns (success, event_dict)."""
    action_type = action.get("type", "")
    target = action.get("target", "")
    event = {"time": _now_iso(), "action": action_type, "target": target}

    if action_type == "asa-tunnel-shutdown":
        interface = action.get("interface", "")
        asa = "nl" if "nl" in target else "gr"
        config_fn = ssh_nl_asa_config if asa == "nl" else ssh_gr_asa_config
        success = config_fn([f"interface {interface}", "shutdown"])
        event["detail"] = f"shutdown {interface} on {target}"
        event["success"] = success
        return success, event

    elif action_type == "docker-compose-stop":
        services = action.get("services", [])
        host = target
        key = os.path.expanduser("~/.ssh/one_key")
        for svc in services:
            cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
                   "-o", "ConnectTimeout=15", f"operator@{host}",
                   f"cd /srv/{svc} && docker compose stop {svc} 2>/dev/null || "
                   f"docker stop {svc} 2>/dev/null || true"]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        event["detail"] = f"stopped {','.join(services)} on {host}"
        event["success"] = True
        return True, event

    elif action_type == "tc-netem":
        interface = action.get("interface", "")
        params = action.get("params", {})
        key = os.path.expanduser("~/.ssh/one_key")
        # Build tc command
        tc_parts = ["sudo", "tc", "qdisc", "add", "dev", interface, "root", "netem"]
        if "delay_ms" in params:
            tc_parts += ["delay", f"{params['delay_ms']}ms"]
            if "jitter_ms" in params:
                tc_parts += [f"{params['jitter_ms']}ms"]
        if "loss_percent" in params:
            tc_parts += ["loss", f"{params['loss_percent']}%"]

        # Get target access info from catalog
        tc_cmd = " ".join(tc_parts)
        access = _resolve_target_access(target)
        if access:
            cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
                   "-o", "ConnectTimeout=15",
                   f"{access['user']}@{access['host']}", tc_cmd]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            success = result.returncode == 0
        else:
            success = False
        event["detail"] = f"tc netem {params} on {interface}@{target}"
        event["success"] = success
        return success, event

    elif action_type == "ios-port-shutdown":
        interface = action.get("interface", "")
        if "sw01" not in target:
            event["detail"] = f"ios-port-shutdown: target '{target}' not supported (sw01 only)"
            event["success"] = False
            return False, event
        success, msg = sw01_port_shutdown(interface)
        event["detail"] = f"shutdown {interface} on {target}: {msg}"
        event["success"] = success
        return success, event

    else:
        event["detail"] = f"unknown action type: {action_type}"
        event["success"] = False
        return False, event


def _execute_rollback_action(rollback):
    """Execute a single rollback action."""
    action_type = rollback.get("type", "")
    target = rollback.get("target", "")

    if action_type == "asa-tunnel-noshut":
        interface = rollback.get("interface", "")
        asa = "nl" if "nl" in target else "gr"
        config_fn = ssh_nl_asa_config if asa == "nl" else ssh_gr_asa_config
        config_fn([f"interface {interface}", "no shutdown"])

    elif action_type == "docker-compose-start":
        services = rollback.get("services", [])
        key = os.path.expanduser("~/.ssh/one_key")
        for svc in services:
            cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
                   "-o", "ConnectTimeout=15", f"operator@{target}",
                   f"cd /srv/{svc} && docker compose start {svc} 2>/dev/null || "
                   f"docker start {svc} 2>/dev/null || true"]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    elif action_type == "tc-netem-clear":
        interface = rollback.get("interface", "")
        key = os.path.expanduser("~/.ssh/one_key")
        access = _resolve_target_access(target)
        if access:
            cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
                   "-o", "ConnectTimeout=15",
                   f"{access['user']}@{access['host']}",
                   f"sudo tc qdisc del dev {interface} root netem 2>/dev/null || true"]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    elif action_type == "ios-port-noshut":
        interface = rollback.get("interface", "")
        force_poe_cycle = rollback.get("force_poe_cycle", False)
        if "sw01" in target and interface:
            sw01_port_noshut(interface, force_poe_cycle=force_poe_cycle)


def _resolve_target_access(target_id):
    """Resolve target access info from catalog."""
    try:
        from chaos_catalog import get_target
        target = get_target(target_id)
        if target:
            return target.get("access", {})
    except ImportError:
        pass
    return None


def _execute_branch(branch_name, actions):
    """Execute a branch (list of actions). Returns BranchResult."""
    events = []
    for action in actions:
        success, event = _execute_action(action)
        events.append(event)
        if not success:
            return BranchResult(branch_name, success=False, events=events,
                                error=f"Action {action.get('type')} failed on {action.get('target')}")
    return BranchResult(branch_name, success=True, events=events)


def execute_experiment_method(method):
    """Execute an experiment method with step/branch/action hierarchy.

    Steps execute sequentially. Branches within a step execute in parallel.
    If any branch fails, all completed branches are rolled back.

    Args:
        method: Either a list of actions (simple experiment) or a dict with
                'steps' key containing step/branch structure.

    Returns:
        (all_events, completed_branches) tuple
    """
    all_events = []
    completed_branches = []

    # Simple method (list of actions) -- execute sequentially
    if isinstance(method, list):
        for action in method:
            success, event = _execute_action(action)
            all_events.append(event)
            if not success:
                raise ChaosAbortError(f"Action failed: {event.get('detail')}")
        return all_events, []

    # Step/branch method (AZ-2 model)
    steps = method.get("steps", [])
    for step_idx, step in enumerate(steps):
        step_name = step.get("name", f"step-{step_idx}")
        branches = step.get("branches", [])

        if not branches:
            # Single-action step
            actions = step.get("actions", [])
            result = _execute_branch(step_name, actions)
            all_events.extend(result.events)
            if result.success:
                completed_branches.append(result)
            else:
                raise ChaosAbortError(f"Step {step_name} failed: {result.error}")
            continue

        # Parallel branch execution
        branch_results = {}
        with ThreadPoolExecutor(max_workers=len(branches)) as pool:
            futures = {}
            for branch in branches:
                bname = branch.get("name", f"branch-{len(futures)}")
                bactions = branch.get("actions", [])
                futures[pool.submit(_execute_branch, bname, bactions)] = bname

            for future in as_completed(futures, timeout=120):
                bname = futures[future]
                try:
                    result = future.result()
                    branch_results[bname] = result
                    all_events.extend(result.events)
                except Exception as e:
                    all_events.append({
                        "time": _now_iso(),
                        "action": "branch-error",
                        "target": bname,
                        "detail": str(e),
                        "success": False,
                    })
                    branch_results[bname] = BranchResult(bname, success=False, error=str(e))

        # Check if all branches succeeded
        failed = [r for r in branch_results.values() if not r.success]
        completed_branches.extend(r for r in branch_results.values() if r.success)

        if failed:
            raise ChaosAbortError(
                f"Step {step_name}: {len(failed)} branch(es) failed: "
                + ", ".join(f.name for f in failed)
            )

    return all_events, completed_branches


def rollback_all(rollbacks):
    """Execute all rollbacks sequentially (never parallel for safety)."""
    events = []
    for rb in rollbacks:
        try:
            _execute_rollback_action(rb)
            events.append({
                "time": _now_iso(),
                "action": f"rollback-{rb.get('type')}",
                "target": rb.get("target", ""),
                "detail": f"rolled back {rb.get('type')} on {rb.get('target', '')}",
                "success": True,
            })
        except Exception as e:
            events.append({
                "time": _now_iso(),
                "action": f"rollback-{rb.get('type')}",
                "target": rb.get("target", ""),
                "detail": f"rollback failed: {e}",
                "success": False,
            })
    return events
