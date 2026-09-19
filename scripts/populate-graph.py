#!/usr/bin/env python3
"""Populate GraphRAG tables (graph_entities, graph_relationships) from existing data.

Sources:
  1. incident_knowledge — hosts, alert_rules, incidents, inter-host dependencies
  2. session_log — incidents with alert_category
  3. lessons_learned — linked to incidents

Usage:
  python3 scripts/populate-graph.py                          # Full population
  python3 scripts/populate-graph.py --stats                  # Show graph statistics
  python3 scripts/populate-graph.py --issue IFRNLLEI01PRD-123  # Add single incident
"""

import argparse
import json
import os
REDACTED_a7b84d63
import sqlite3
import sys

DB_PATH = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")

# Matches Example Corp hostnames: nl-pve01, gr-fw01, gr2cam01, etc.
HOSTNAME_RE = re.compile(r"\b([a-z]{2}[a-z0-9]{3,5}\d{2}[a-z][a-z0-9-]*\d{2})\b")

# Also match K8s-style long names that appear as hostnames in the data
K8S_HOST_RE = re.compile(
    r"\b(prometheus-monitoring-[a-z0-9-]+\d|my-awx-[a-z]+)\b"
)

# Match issue IDs referenced in text (e.g. "IFRNLLEI01PRD-202")
ISSUE_RE = re.compile(r"\b((?:IFRNLLEI01PRD|IFRGRSKG01PRD|CUBEOS|MESHSAT)-\d+)\b")


def get_db():
    """Open database connection with WAL mode."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def upsert_entity(conn, entity_type, name, source_table="", source_id="", attributes=None):
    """Insert or ignore an entity. Returns the entity id."""
    attrs = json.dumps(attributes or {}, ensure_ascii=False)
    conn.execute(
        """INSERT OR IGNORE INTO graph_entities
           (entity_type, name, source_table, source_id, attributes)
           VALUES (?, ?, ?, ?, ?)""",
        (entity_type, name, source_table, source_id, attrs),
    )
    row = conn.execute(
        "SELECT id FROM graph_entities WHERE entity_type = ? AND name = ?",
        (entity_type, name),
    ).fetchone()
    return row["id"]


def upsert_relationship(conn, source_id, target_id, rel_type, confidence=1.0, metadata=None):
    """Insert a relationship if it does not already exist (same source, target, type)."""
    existing = conn.execute(
        """SELECT id FROM graph_relationships
           WHERE source_id = ? AND target_id = ? AND rel_type = ?""",
        (source_id, target_id, rel_type),
    ).fetchone()
    if existing:
        return existing["id"]
    meta = json.dumps(metadata or {}, ensure_ascii=False)
    cur = conn.execute(
        """INSERT INTO graph_relationships
           (source_id, target_id, rel_type, confidence, metadata)
           VALUES (?, ?, ?, ?, ?)""",
        (source_id, target_id, rel_type, confidence, meta),
    )
    return cur.lastrowid


def extract_hostnames(text):
    """Extract all Example Corp-style hostnames from text."""
    if not text:
        return set()
    hosts = set(HOSTNAME_RE.findall(text))
    hosts.update(K8S_HOST_RE.findall(text))
    return hosts


def extract_issue_ids(text):
    """Extract issue IDs referenced in text."""
    if not text:
        return set()
    return set(ISSUE_RE.findall(text))


def populate_from_incident_knowledge(conn, issue_filter=None):
    """Process incident_knowledge rows into graph entities and relationships."""
    query = "SELECT * FROM incident_knowledge"
    params = ()
    if issue_filter:
        query += " WHERE issue_id = ?"
        params = (issue_filter,)

    rows = conn.execute(query, params).fetchall()
    count = {"entities": 0, "relationships": 0}

    for row in rows:
        issue_id = row["issue_id"]
        hostname = row["hostname"]
        alert_rule = row["alert_rule"]
        root_cause = row["root_cause"] or ""
        resolution = row["resolution"] or ""
        confidence = row["confidence"] if row["confidence"] >= 0 else None
        site = row["site"] or ""
        tags = row["tags"] or ""

        # Skip rows without an issue_id — nothing to anchor
        if not issue_id:
            continue

        # 1. Create incident entity
        incident_attrs = {}
        if root_cause:
            incident_attrs["root_cause"] = root_cause
        if resolution:
            incident_attrs["resolution"] = resolution
        if confidence is not None:
            incident_attrs["confidence"] = confidence
        if site:
            incident_attrs["site"] = site
        if tags:
            incident_attrs["tags"] = tags

        incident_eid = upsert_entity(
            conn, "incident", issue_id,
            source_table="incident_knowledge",
            source_id=str(row["id"]),
            attributes=incident_attrs,
        )
        count["entities"] += 1

        # 2. Create host entity and incident -affects-> host
        if hostname:
            host_eid = upsert_entity(
                conn, "host", hostname,
                source_table="incident_knowledge",
                source_id=str(row["id"]),
                attributes={"site": site} if site else {},
            )
            count["entities"] += 1
            upsert_relationship(conn, incident_eid, host_eid, "affects")
            count["relationships"] += 1

        # 3. Create alert_rule entity and alert_rule -triggers-> incident
        if alert_rule:
            rule_eid = upsert_entity(
                conn, "alert_rule", alert_rule,
                source_table="incident_knowledge",
                source_id=str(row["id"]),
            )
            count["entities"] += 1
            upsert_relationship(conn, rule_eid, incident_eid, "triggers")
            count["relationships"] += 1

        # 4. Cross-host dependencies from resolution + root_cause text
        combined_text = f"{root_cause} {resolution}"
        mentioned_hosts = extract_hostnames(combined_text)
        # Remove the primary hostname to avoid self-reference
        if hostname:
            mentioned_hosts.discard(hostname)

        for other_host in mentioned_hosts:
            other_eid = upsert_entity(
                conn, "host", other_host,
                attributes={"site": site} if site else {},
            )
            count["entities"] += 1
            upsert_relationship(
                conn, incident_eid, other_eid, "depends_on",
                confidence=0.8,
                metadata={"extracted_from": "text"},
            )
            count["relationships"] += 1

        # 5. Cross-incident references from resolution text
        referenced_issues = extract_issue_ids(resolution)
        referenced_issues.discard(issue_id)  # no self-reference
        for ref_issue in referenced_issues:
            ref_eid = upsert_entity(
                conn, "incident", ref_issue,
                source_table="incident_knowledge",
            )
            count["entities"] += 1
            upsert_relationship(
                conn, incident_eid, ref_eid, "caused_by",
                confidence=0.7,
                metadata={"extracted_from": "resolution_text"},
            )
            count["relationships"] += 1

    return count


def populate_from_session_log(conn, issue_filter=None):
    """Process session_log rows — create incident entities with alert_category."""
    query = "SELECT * FROM session_log WHERE issue_id IS NOT NULL AND issue_id != ''"
    params = ()
    if issue_filter:
        query += " AND issue_id = ?"
        params = (issue_filter,)

    rows = conn.execute(query, params).fetchall()
    count = {"entities": 0, "relationships": 0}

    for row in rows:
        issue_id = row["issue_id"]
        alert_category = row["alert_category"] or ""
        outcome = row["outcome"] or ""
        issue_title = row["issue_title"] or ""

        attrs = {}
        if alert_category:
            attrs["alert_category"] = alert_category
        if outcome:
            attrs["outcome"] = outcome

        # Create or update incident entity
        upsert_entity(
            conn, "incident", issue_id,
            source_table="session_log",
            source_id=str(row["id"]),
            attributes=attrs,
        )
        count["entities"] += 1

        # Extract hostnames from issue_title and link them
        if issue_title:
            hosts = extract_hostnames(issue_title)
            for host in hosts:
                host_eid = upsert_entity(
                    conn, "host", host,
                    source_table="session_log",
                )
                count["entities"] += 1
                incident_eid = conn.execute(
                    "SELECT id FROM graph_entities WHERE entity_type = 'incident' AND name = ?",
                    (issue_id,),
                ).fetchone()["id"]
                upsert_relationship(conn, incident_eid, host_eid, "affects")
                count["relationships"] += 1

    return count


def populate_from_chaos_experiments(conn):
    """#14 upgrade: add chaos_experiments as entities linked to their target hosts.

    Creates:
      - one `chaos_experiment` entity per experiment_id
      - `chaos-tests` relationship from experiment -> each target host mentioned in targets
    """
    count = {"entities": 0, "relationships": 0}
    try:
        rows = conn.execute(
            "SELECT experiment_id, chaos_type, targets, verdict, "
            "convergence_seconds, mttd_seconds, started_at "
            "FROM chaos_experiments"
        ).fetchall()
    except sqlite3.OperationalError:
        return count

    for r in rows:
        if not r["experiment_id"]:
            continue
        attrs = {
            "chaos_type": r["chaos_type"] or "",
            "verdict": r["verdict"] or "",
            "convergence_seconds": r["convergence_seconds"],
            "mttd_seconds": r["mttd_seconds"],
            "started_at": r["started_at"] or "",
        }
        chaos_eid = upsert_entity(
            conn, "chaos_experiment", r["experiment_id"],
            source_table="chaos_experiments",
            source_id=r["experiment_id"],
            attributes=attrs,
        )
        count["entities"] += 1

        # Extract hosts from targets field (may be JSON or free text)
        targets_text = r["targets"] or ""
        hosts = extract_hostnames(targets_text)
        for host in hosts:
            host_eid = upsert_entity(conn, "host", host, source_table="chaos_experiments")
            count["entities"] += 1
            upsert_relationship(conn, chaos_eid, host_eid, "chaos-tests")
            count["relationships"] += 1
    return count


# Common service/subsystem names we want as graph entities when mentioned in text
SERVICE_KEYWORDS = {
    "n8n", "apiserver", "etcd", "Freedom ISP", "xs4all", "inalan", "SeaweedFS",
    "VTI tunnel", "BGP", "iSCSI", "ZFS", "Zigbee", "MeshSat", "PiKVM", "Atlantis",
    "Prometheus", "Grafana", "Matrix", "Mattermost", "LibreNMS", "Velero",
    "SQLite mutex", "Cilium", "CoreDNS", "ClusterMesh", "Longhorn", "androidsdk01",
}


def populate_services_from_text(conn):
    """#14 upgrade: extract well-known service names from incident resolutions."""
    count = {"entities": 0, "relationships": 0}
    rows = conn.execute(
        "SELECT issue_id, resolution, root_cause FROM incident_knowledge "
        "WHERE issue_id IS NOT NULL AND issue_id != ''"
    ).fetchall()
    for row in rows:
        issue_id = row["issue_id"]
        text = " ".join(str(row[k] or "") for k in ("resolution", "root_cause"))
        low = text.lower()
        for svc in SERVICE_KEYWORDS:
            if svc.lower() in low:
                svc_eid = upsert_entity(
                    conn, "service", svc,
                    source_table="incident_knowledge",
                    source_id=issue_id,
                )
                count["entities"] += 1
                inc = conn.execute(
                    "SELECT id FROM graph_entities WHERE entity_type='incident' AND name=?",
                    (issue_id,),
                ).fetchone()
                if inc:
                    upsert_relationship(conn, inc["id"], svc_eid, "involves-service")
                    count["relationships"] += 1
    return count


def populate_from_lessons_learned(conn, issue_filter=None):
    """Process lessons_learned — link lessons to their incidents."""
    query = "SELECT * FROM lessons_learned WHERE issue_id IS NOT NULL AND issue_id != ''"
    params = ()
    if issue_filter:
        query += " AND issue_id = ?"
        params = (issue_filter,)

    rows = conn.execute(query, params).fetchall()
    count = {"entities": 0, "relationships": 0}

    for row in rows:
        issue_id = row["issue_id"]
        lesson_text = row["lesson"] or ""

        # Ensure the incident entity exists
        incident_eid = upsert_entity(
            conn, "incident", issue_id,
            source_table="lessons_learned",
            source_id=str(row["id"]),
        )
        count["entities"] += 1

        # Create a lesson entity
        lesson_name = f"lesson-{row['id']}"
        lesson_eid = upsert_entity(
            conn, "lesson", lesson_name,
            source_table="lessons_learned",
            source_id=str(row["id"]),
            attributes={"text": lesson_text, "source": row["source"] or ""},
        )
        count["entities"] += 1

        # lesson -resolves-> incident
        upsert_relationship(conn, lesson_eid, incident_eid, "resolves")
        count["relationships"] += 1

        # Extract hosts mentioned in lesson text and link
        hosts = extract_hostnames(lesson_text)
        for host in hosts:
            host_eid = upsert_entity(conn, "host", host)
            count["entities"] += 1
            upsert_relationship(
                conn, lesson_eid, host_eid, "affects",
                confidence=0.7,
                metadata={"extracted_from": "lesson_text"},
            )
            count["relationships"] += 1

    return count


def print_stats(conn):
    """Print graph statistics."""
    print("\n=== Graph Entity Statistics ===")
    rows = conn.execute(
        "SELECT entity_type, COUNT(*) as cnt FROM graph_entities GROUP BY entity_type ORDER BY cnt DESC"
    ).fetchall()
    total_entities = 0
    for r in rows:
        print(f"  {r['entity_type']:15s} {r['cnt']:4d}")
        total_entities += r["cnt"]
    print(f"  {'TOTAL':15s} {total_entities:4d}")

    print("\n=== Graph Relationship Statistics ===")
    rows = conn.execute(
        "SELECT rel_type, COUNT(*) as cnt FROM graph_relationships GROUP BY rel_type ORDER BY cnt DESC"
    ).fetchall()
    total_rels = 0
    for r in rows:
        print(f"  {r['rel_type']:15s} {r['cnt']:4d}")
        total_rels += r["cnt"]
    print(f"  {'TOTAL':15s} {total_rels:4d}")

    # Top connected entities
    print("\n=== Top 10 Most Connected Entities ===")
    rows = conn.execute(
        """SELECT e.entity_type, e.name,
                  (SELECT COUNT(*) FROM graph_relationships WHERE source_id = e.id)
                + (SELECT COUNT(*) FROM graph_relationships WHERE target_id = e.id) as degree
           FROM graph_entities e
           ORDER BY degree DESC
           LIMIT 10"""
    ).fetchall()
    for r in rows:
        print(f"  {r['entity_type']:15s} {r['name']:40s} degree={r['degree']}")


def main():
    parser = argparse.ArgumentParser(description="Populate GraphRAG tables from existing data")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics only")
    parser.add_argument("--issue", type=str, help="Process a single issue ID")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = get_db()

    if args.stats:
        print_stats(conn)
        conn.close()
        return

    issue_filter = args.issue
    if issue_filter:
        print(f"Processing single issue: {issue_filter}")
    else:
        print("Full graph population from all sources")

    print(f"Database: {DB_PATH}\n")

    # Phase 1: incident_knowledge
    print("--- Phase 1: incident_knowledge ---")
    c1 = populate_from_incident_knowledge(conn, issue_filter)
    conn.commit()
    print(f"  Processed: {c1['entities']} entity upserts, {c1['relationships']} relationship upserts")

    # Phase 2: session_log
    print("--- Phase 2: session_log ---")
    c2 = populate_from_session_log(conn, issue_filter)
    conn.commit()
    print(f"  Processed: {c2['entities']} entity upserts, {c2['relationships']} relationship upserts")

    # Phase 3: lessons_learned
    print("--- Phase 3: lessons_learned ---")
    c3 = populate_from_lessons_learned(conn, issue_filter)
    conn.commit()
    print(f"  Processed: {c3['entities']} entity upserts, {c3['relationships']} relationship upserts")

    # Phase 4 (#14 upgrade): chaos_experiments
    print("--- Phase 4: chaos_experiments ---")
    c4 = populate_from_chaos_experiments(conn)
    conn.commit()
    print(f"  Processed: {c4['entities']} entity upserts, {c4['relationships']} relationship upserts")

    # Phase 5 (#14 upgrade): services from text
    print("--- Phase 5: service extraction ---")
    c5 = populate_services_from_text(conn)
    conn.commit()
    print(f"  Processed: {c5['entities']} entity upserts, {c5['relationships']} relationship upserts")

    # Final stats
    print_stats(conn)
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
