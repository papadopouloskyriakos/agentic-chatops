#!/usr/bin/env python3
"""Track credential usage across the claude-gateway platform.

Scans .env files, n8n credentials, SSH keys, and tool_call_log MCP usage
to populate the credential_usage_log table.

Usage:
  track-credential-usage.py           # full audit + insert
  track-credential-usage.py --stats   # show credential inventory
"""
import sys
import os
import json
import sqlite3
REDACTED_a7b84d63
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
ENV_PATH = os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")
SSH_DIR = os.path.expanduser("~/.ssh")

# n8n credentials from CLAUDE.md references
N8N_CREDENTIALS = [
    {
        "name": "nl-claude01 SSH app-user",
        "id": "REDACTED_SSH_CRED",
        "type": "SSH private key",
    },
    {
        "name": "Matrix Claude Bot (HTTP Header Auth)",
        "id": "REDACTED_MATRIX_CRED",
        "type": "Bearer token",
    },
    {
        "name": "YouTrack API Token (HTTP Header Auth)",
        "id": "REDACTED_YT_CRED",
        "type": "Bearer token",
    },
]

# MCP servers that imply credential usage when called
MCP_CREDENTIAL_MAP = {
    "mcp__youtrack__": "YouTrack API Token",
    "mcp__netbox__": "NetBox API Token",
    "mcp__proxmox__": "Proxmox API Token",
    "mcp__n8n-mcp__": "n8n API Credential",
    "mcp__gitlab__": "GitLab API Token",
    "mcp__codegraph__": "CodeGraph Local",
    "mcp__kubernetes__": "Kubernetes Kubeconfig",
    "mcp__opentofu__": "OpenTofu Registry",
    "mcp__tfmcp__": "Terraform MCP Local",
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def clear_previous_audit(conn):
    """Remove previous audit entries (source != 'session') to allow re-run."""
    conn.execute(
        "DELETE FROM credential_usage_log WHERE session_id = '' OR session_id IS NULL"
    )
    conn.commit()


def scan_env_file(conn):
    """Scan .env file for credential-related variables."""
    if not os.path.exists(ENV_PATH):
        print(f"[warn] .env not found at {ENV_PATH}")
        return 0

    inserted = 0
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            # Only track credential-like env vars
            if any(kw in key.upper() for kw in (
                "KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "API"
            )):
                conn.execute(
                    """INSERT INTO credential_usage_log
                       (credential_name, source, ttl_seconds, created_at)
                       VALUES (?, 'env', 0, CURRENT_TIMESTAMP)""",
                    (key,)
                )
                inserted += 1
                print(f"  [env] {key}")

    conn.commit()
    return inserted


def scan_n8n_credentials(conn):
    """Record known n8n credentials."""
    inserted = 0
    for cred in N8N_CREDENTIALS:
        conn.execute(
            """INSERT INTO credential_usage_log
               (credential_name, source, session_id, ttl_seconds, created_at)
               VALUES (?, 'n8n', ?, 0, CURRENT_TIMESTAMP)""",
            (f"{cred['name']} ({cred['id']})", cred["id"])
        )
        inserted += 1
        print(f"  [n8n] {cred['name']} (ID: {cred['id']}, type: {cred['type']})")

    conn.commit()
    return inserted


def scan_ssh_keys(conn):
    """Scan ~/.ssh/ for key files."""
    if not os.path.isdir(SSH_DIR):
        print(f"[warn] SSH dir not found: {SSH_DIR}")
        return 0

    inserted = 0
    for entry in sorted(os.listdir(SSH_DIR)):
        path = os.path.join(SSH_DIR, entry)
        if not os.path.isfile(path):
            continue
        # Skip known non-key files
        if entry in ("config", "known_hosts", "known_hosts.old", "authorized_keys"):
            continue
        # Skip .pub files (they're the public half)
        if entry.endswith(".pub") or entry.endswith(".b64"):
            continue

        # Check if it looks like a private key
        is_key = False
        try:
            with open(path, "r") as f:
                first_line = f.readline().strip()
                if "PRIVATE KEY" in first_line or "OPENSSH PRIVATE KEY" in first_line:
                    is_key = True
        except (UnicodeDecodeError, PermissionError):
            # Binary file or no access -- might still be a key
            is_key = entry in ("id_rsa", "id_ed25519", "id_ecdsa", "one_key")

        if is_key:
            stat = os.stat(path)
            perms = oct(stat.st_mode)[-3:]
            conn.execute(
                """INSERT INTO credential_usage_log
                   (credential_name, source, session_id, ttl_seconds, created_at)
                   VALUES (?, 'ssh-key', ?, 0, CURRENT_TIMESTAMP)""",
                (f"SSH key: {entry}", f"perms:{perms}")
            )
            inserted += 1
            print(f"  [ssh] {entry} (perms: {perms})")

    conn.commit()
    return inserted


def scan_mcp_usage(conn):
    """Scan tool_call_log for MCP tool calls that imply credential usage."""
    # Check if tool_call_log has data
    count = conn.execute("SELECT COUNT(*) FROM tool_call_log").fetchone()[0]
    if count == 0:
        print("  [mcp] No tool_call_log data to scan")
        return 0

    inserted = 0
    for prefix, cred_name in MCP_CREDENTIAL_MAP.items():
        rows = conn.execute(
            """SELECT COUNT(*) as cnt,
                      MIN(created_at) as first_use,
                      MAX(created_at) as last_use
               FROM tool_call_log
               WHERE tool_name LIKE ?""",
            (prefix + "%",)
        ).fetchone()

        call_count = rows[0]
        if call_count > 0:
            first_use = rows[1] or ""
            last_use = rows[2] or ""
            conn.execute(
                """INSERT INTO credential_usage_log
                   (credential_name, source, session_id, issue_id,
                    ttl_seconds, created_at)
                   VALUES (?, 'mcp-usage', ?, ?, 0, CURRENT_TIMESTAMP)""",
                (
                    cred_name,
                    f"calls:{call_count}",
                    f"first:{first_use[:19]} last:{last_use[:19]}",
                )
            )
            inserted += 1
            print(f"  [mcp] {cred_name}: {call_count} calls "
                  f"({first_use[:10]} to {last_use[:10]})")

    conn.commit()
    return inserted


def show_stats():
    """Show credential inventory from the database."""
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) FROM credential_usage_log"
    ).fetchone()[0]

    if total == 0:
        print("[stats] No credential data. Run without --stats first.")
        conn.close()
        return

    print(f"=== Credential Inventory ({total} entries) ===\n")

    print("By source:")
    rows = conn.execute("""
        SELECT source, COUNT(*) as cnt
        FROM credential_usage_log
        GROUP BY source ORDER BY cnt DESC
    """).fetchall()
    for source, cnt in rows:
        print(f"  {source}: {cnt}")

    print("\nAll credentials:")
    rows = conn.execute("""
        SELECT credential_name, source, session_id, created_at
        FROM credential_usage_log
        ORDER BY source, credential_name
    """).fetchall()
    for name, source, sid, created in rows:
        extra = f" [{sid}]" if sid else ""
        print(f"  [{source:<8}] {name}{extra}")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        show_stats()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        sys.exit(0)

    print("=== Credential Usage Audit ===\n")

    conn = get_db()

    # Clear previous audit data for idempotent re-runs
    clear_previous_audit(conn)

    total = 0

    print("[1/4] Scanning .env file...")
    total += scan_env_file(conn)

    print("\n[2/4] Recording n8n credentials...")
    total += scan_n8n_credentials(conn)

    print("\n[3/4] Scanning SSH keys...")
    total += scan_ssh_keys(conn)

    print("\n[4/4] Scanning MCP usage from tool_call_log...")
    total += scan_mcp_usage(conn)

    # Compute rotation_due_at = created_at + 90 days for all entries
    conn = get_db()
    updated = conn.execute("""
        UPDATE credential_usage_log
        SET rotation_due_at = datetime(created_at, '+90 days')
        WHERE rotation_due_at IS NULL
    """).rowcount
    conn.commit()
    print(f"\n[5/5] Updated rotation_due_at for {updated} credentials (90-day cycle)")

    # Write credential age metrics to Prometheus textfile collector
    prom_path = "/var/lib/node_exporter/textfile_collector/credential_metrics.prom"
    try:
        rows = conn.execute("""
            SELECT credential_name, source,
                   CAST(julianday('now') - julianday(created_at) AS INTEGER) as age_days,
                   rotation_due_at,
                   CASE WHEN rotation_due_at < datetime('now') THEN 1 ELSE 0 END as overdue
            FROM credential_usage_log
            WHERE credential_name != ''
        """).fetchall()

        with open(prom_path, "w") as pf:
            pf.write("# HELP credential_age_days Age of credential in days\n")
            pf.write("# TYPE credential_age_days gauge\n")
            pf.write("# HELP credential_rotation_overdue 1 if credential is past rotation date\n")
            pf.write("# TYPE credential_rotation_overdue gauge\n")
            pf.write("# HELP credential_total Total tracked credentials\n")
            pf.write("# TYPE credential_total gauge\n")
            for name, source, age_days, rot_due, overdue in rows:
                safe_name = name.replace('"', '').replace("'", "")[:60]
                pf.write(f'credential_age_days{{name="{safe_name}",source="{source}"}} {age_days}\n')
                pf.write(f'credential_rotation_overdue{{name="{safe_name}",source="{source}"}} {overdue}\n')
            pf.write(f"credential_total {len(rows)}\n")
        print(f"[prom] Wrote {len(rows)} credential metrics to {prom_path}")
    except Exception as e:
        print(f"[warn] Could not write Prometheus metrics: {e}")

    conn.close()

    print(f"\n[done] {total} credential entries recorded in credential_usage_log")
