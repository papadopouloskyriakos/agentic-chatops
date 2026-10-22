#!/usr/bin/env python3
"""Compile unified knowledge base wiki from 7+ fragmented knowledge sources.

Inspired by Karpathy's LLM Knowledge Bases pattern: raw data from multiple sources
is compiled by an LLM into a browsable .md wiki with auto-maintained indexes,
cross-references, and health checks.

Sources: memory files, CLAUDE.md files, incident_knowledge, lessons_learned,
openclaw_memory, 03_Lab manifest, docs/, OpenClaw skills, Grafana dashboards.

Usage:
  wiki-compile.py                          # Incremental compilation
  wiki-compile.py --full                   # Force full recompilation
  wiki-compile.py --article topology/vpn-mesh.md  # Single article
  wiki-compile.py --health                 # Health checks only
  wiki-compile.py --dry-run                # Show what would compile
"""

import sys
import os
import json
import hashlib
import sqlite3
import glob as globmod
REDACTED_a7b84d63
import datetime
import subprocess

# ── Paths ──────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI_DIR = os.path.join(BASE_DIR, "wiki")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
SKILLS_DIR = os.path.join(BASE_DIR, "openclaw", "skills")
GRAFANA_DIR = os.path.join(BASE_DIR, "grafana")
DB_PATH = os.path.expanduser(
    "~/gitlab/products/cubeos/claude-context/gateway.db"
)
MEMORY_DIR = os.path.expanduser(
    "~/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory"
)
LAB_DIR = os.path.expanduser("~/Q/03_Lab")
IAC_REPOS = {
    "nl": os.path.expanduser("~/gitlab/infrastructure/nl/production"),
    "gr": os.path.expanduser("~/gitlab/infrastructure/gr/production"),
}
COMPILE_STATE = os.path.join(WIKI_DIR, ".compile-state.json")
SOURCE_MAP = os.path.join(WIKI_DIR, ".source-map.json")

NOW = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
TODAY = datetime.datetime.utcnow().strftime("%Y-%m-%d")


# ── Source Readers ─────────────────────────────────────────────────────────────


def sha256_file(path):
    """SHA-256 of a file (or empty string if unreadable)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return ""


def sha256_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def parse_frontmatter(path):
    """Parse YAML frontmatter + markdown body from a memory file."""
    try:
        with open(path, "r") as f:
            content = f.read()
    except (OSError, IOError):
        return None
    meta = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip()] = val.strip()
            body = parts[2].strip()
    return {"path": path, "meta": meta, "body": body, "filename": os.path.basename(path)}


def read_memory_files():
    """Read all memory files with YAML frontmatter."""
    if not os.path.isdir(MEMORY_DIR):
        return []
    memories = []
    for f in sorted(os.listdir(MEMORY_DIR)):
        if not f.endswith(".md") or f == "MEMORY.md":
            continue
        parsed = parse_frontmatter(os.path.join(MEMORY_DIR, f))
        if parsed:
            memories.append(parsed)
    return memories


def read_claude_md_files():
    """Find and read all CLAUDE.md files across IaC repos and other known locations."""
    files = []
    # IaC repos (NL + GR)
    for site, repo in IAC_REPOS.items():
        if os.path.isdir(repo):
            for root, _dirs, fnames in os.walk(repo):
                if "CLAUDE.md" in fnames:
                    path = os.path.join(root, "CLAUDE.md")
                    rel = os.path.relpath(path, repo)
                    try:
                        with open(path, "r") as f:
                            content = f.read()
                    except (OSError, IOError):
                        continue
                    files.append({"path": path, "site": site, "rel": rel, "content": content})
    # Gateway CLAUDE.md
    gw_claude = os.path.join(BASE_DIR, "CLAUDE.md")
    if os.path.isfile(gw_claude):
        with open(gw_claude, "r") as f:
            files.append({"path": gw_claude, "site": "gateway", "rel": "CLAUDE.md", "content": f.read()})
    # Other known repos
    for extra in [
        "~/gitlab/products/cubeos",
        "~/gitlab/n8n/social-media-autoposter",
        "~/gitlab/n8n/doorbell",
    ]:
        p = os.path.expanduser(os.path.join(extra, "CLAUDE.md"))
        if os.path.isfile(p):
            try:
                with open(p, "r") as f:
                    files.append({"path": p, "site": "other", "rel": p, "content": f.read()})
            except (OSError, IOError):
                pass
    return files


def read_sqlite_tables():
    """Read incident_knowledge, lessons_learned, openclaw_memory from gateway.db."""
    if not os.path.isfile(DB_PATH):
        return {"incidents": [], "lessons": [], "openclaw_mem": []}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    incidents = [dict(r) for r in conn.execute(
        "SELECT id, alert_rule, hostname, site, root_cause, resolution, "
        "confidence, duration_seconds, cost_usd, created_at, issue_id, tags "
        "FROM incident_knowledge ORDER BY created_at DESC"
    ).fetchall()]

    lessons = [dict(r) for r in conn.execute(
        "SELECT id, issue_id, lesson, source, created_at "
        "FROM lessons_learned ORDER BY created_at DESC"
    ).fetchall()]

    openclaw_mem = [dict(r) for r in conn.execute(
        "SELECT id, category, key, value, issue_id, updated_at "
        "FROM openclaw_memory ORDER BY updated_at DESC"
    ).fetchall()]

    conn.close()
    return {"incidents": incidents, "lessons": lessons, "openclaw_mem": openclaw_mem}


def read_docs():
    """Read markdown docs from docs/ directory."""
    docs = []
    if not os.path.isdir(DOCS_DIR):
        return docs
    for f in sorted(os.listdir(DOCS_DIR)):
        if not f.endswith(".md"):
            continue
        path = os.path.join(DOCS_DIR, f)
        try:
            with open(path, "r") as fh:
                content = fh.read()
        except (OSError, IOError):
            continue
        docs.append({"path": path, "filename": f, "content": content})
    return docs


def read_skills():
    """Read OpenClaw skill scripts — extract usage and purpose from headers."""
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        return skills
    for entry in sorted(os.listdir(SKILLS_DIR)):
        full = os.path.join(SKILLS_DIR, entry)
        # Direct scripts (*.sh)
        if os.path.isfile(full) and entry.endswith(".sh"):
            skills.append(_parse_skill_script(full, entry))
        # Directory-based skills (e.g., infra-triage/infra-triage.sh)
        elif os.path.isdir(full):
            main_sh = os.path.join(full, f"{entry}.sh")
            if os.path.isfile(main_sh):
                skills.append(_parse_skill_script(main_sh, entry))
            else:
                # Look for any .sh in the dir
                for sub in sorted(os.listdir(full)):
                    if sub.endswith(".sh"):
                        skills.append(_parse_skill_script(os.path.join(full, sub), entry))
                        break
    return skills


def _parse_skill_script(path, name):
    """Extract header comments and usage from a shell script."""
    lines = []
    try:
        with open(path, "r") as f:
            for i, line in enumerate(f):
                if i > 30:
                    break
                lines.append(line.rstrip())
    except (OSError, IOError):
        pass
    # Extract comment block after shebang
    comments = []
    for line in lines[1:]:
        if line.startswith("#"):
            comments.append(line.lstrip("# "))
        elif not line.strip():
            continue
        else:
            break
    return {
        "name": name.replace(".sh", ""),
        "path": path,
        "header": "\n".join(comments) if comments else "(no description)",
        "line_count": sum(1 for _ in open(path, "r")) if os.path.isfile(path) else 0,
    }


def read_grafana():
    """Extract dashboard info from Grafana JSON exports."""
    dashboards = []
    if not os.path.isdir(GRAFANA_DIR):
        return dashboards
    for f in sorted(os.listdir(GRAFANA_DIR)):
        if not f.endswith(".json"):
            continue
        path = os.path.join(GRAFANA_DIR, f)
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        panels = []
        for panel in data.get("panels", []):
            if panel.get("type") == "row":
                for sub in panel.get("panels", []):
                    panels.append(sub.get("title", "untitled"))
            elif panel.get("title"):
                panels.append(panel["title"])
        dashboards.append({
            "filename": f,
            "title": data.get("title", f),
            "panel_count": len(panels),
            "panels": panels,
        })
    return dashboards


def read_lab_manifest():
    """Walk 03_Lab directory tree — paths + sizes + mtimes only, NOT content."""
    manifest = {"total_files": 0, "total_size_mb": 0, "structure": {}}
    if not os.path.isdir(LAB_DIR):
        return manifest
    for entry in sorted(os.listdir(LAB_DIR)):
        full = os.path.join(LAB_DIR, entry)
        if entry.startswith("."):
            continue
        if os.path.isdir(full):
            count = 0
            size = 0
            subdirs = []
            for sub in sorted(os.listdir(full)):
                subpath = os.path.join(full, sub)
                if os.path.isdir(subpath):
                    subdirs.append(sub)
                    for root, _d, files in os.walk(subpath):
                        for fn in files:
                            fp = os.path.join(root, fn)
                            try:
                                count += 1
                                size += os.path.getsize(fp)
                            except OSError:
                                pass
                elif os.path.isfile(subpath):
                    count += 1
                    try:
                        size += os.path.getsize(subpath)
                    except OSError:
                        pass
            manifest["structure"][entry] = {
                "files": count,
                "size_mb": round(size / (1024 * 1024), 1),
                "subdirs": subdirs,
            }
            manifest["total_files"] += count
            manifest["total_size_mb"] += round(size / (1024 * 1024), 1)
    return manifest


# ── Compile State ──────────────────────────────────────────────────────────────


def load_compile_state():
    if os.path.isfile(COMPILE_STATE):
        with open(COMPILE_STATE, "r") as f:
            return json.load(f)
    return {"checksums": {}, "compiled_at": ""}


def save_compile_state(state):
    state["compiled_at"] = NOW
    os.makedirs(os.path.dirname(COMPILE_STATE), exist_ok=True)
    with open(COMPILE_STATE, "w") as f:
        json.dump(state, f, indent=2)


def load_source_map():
    if os.path.isfile(SOURCE_MAP):
        with open(SOURCE_MAP, "r") as f:
            return json.load(f)
    return {}


def save_source_map(smap):
    with open(SOURCE_MAP, "w") as f:
        json.dump(smap, f, indent=2)


def compute_source_checksums(memories, claude_mds, db_data, docs, skills, grafana, lab):
    """Compute SHA-256 checksums for all source files."""
    checksums = {}
    for m in memories:
        checksums[m["path"]] = sha256_file(m["path"])
    for c in claude_mds:
        checksums[c["path"]] = sha256_text(c["content"])
    checksums["db:incident_knowledge"] = sha256_text(json.dumps(db_data["incidents"], default=str))
    checksums["db:lessons_learned"] = sha256_text(json.dumps(db_data["lessons"], default=str))
    checksums["db:openclaw_memory"] = sha256_text(json.dumps(db_data["openclaw_mem"], default=str))
    for d in docs:
        checksums[d["path"]] = sha256_file(d["path"])
    for s in skills:
        checksums[s["path"]] = sha256_file(s["path"])
    for g in grafana:
        checksums[os.path.join(GRAFANA_DIR, g["filename"])] = sha256_file(
            os.path.join(GRAFANA_DIR, g["filename"])
        )
    checksums["lab:manifest"] = sha256_text(json.dumps(lab, default=str))
    return checksums


# ── Article Compilers ──────────────────────────────────────────────────────────

# Each compiler returns (article_path, content, source_deps)
# article_path is relative to wiki/ (e.g., "operations/operational-rules.md")
# source_deps is a list of source keys (for the source map)


def compile_operational_rules(memories):
    """P0: Compile all feedback memories into categorized operational rules."""
    feedbacks = [m for m in memories if m["meta"].get("type") == "feedback"]
    if not feedbacks:
        return None

    # Categorize by domain
    categories = {
        "Configuration Safety": [],
        "ASA / VPN / Network": [],
        "Kubernetes": [],
        "Deployment & Sync": [],
        "Infrastructure Operations": [],
        "Data Integrity": [],
        "General": [],
    }

    for fb in feedbacks:
        name = fb["meta"].get("name", fb["filename"])
        body = fb["body"]
        fname = fb["filename"].lower()

        if any(k in fname for k in ["asa", "vpn", "ipsec", "wan", "crypto", "sw01"]):
            cat = "ASA / VPN / Network"
        elif any(k in fname for k in ["k8s", "gitops"]):
            cat = "Kubernetes"
        elif any(k in fname for k in ["deploy", "sync", "openclaw_deploy", "openclaw_ssh"]):
            cat = "Deployment & Sync"
        elif any(k in fname for k in ["ask_before", "never_modify", "config"]):
            cat = "Configuration Safety"
        elif any(k in fname for k in ["trust", "audit", "hostname"]):
            cat = "Data Integrity"
        elif any(k in fname for k in ["pve", "maint", "awx", "oob"]):
            cat = "Infrastructure Operations"
        else:
            cat = "General"

        categories[cat].append({"name": name, "body": body, "file": fb["filename"]})

    lines = [
        "# Operational Rules",
        "",
        f"> Auto-compiled from {len(feedbacks)} feedback memory files on {NOW}.",
        "> These are hard-won lessons from real incidents. Violating them has caused outages.",
        "",
    ]

    for cat, rules in categories.items():
        if not rules:
            continue
        lines.append(f"## {cat}")
        lines.append("")
        for r in sorted(rules, key=lambda x: x["name"]):
            lines.append(f"### {r['name']}")
            lines.append("")
            lines.append(r["body"])
            lines.append("")
            lines.append(f"*Source: `memory/{r['file']}`*")
            lines.append("")

    deps = [m["path"] for m in feedbacks]
    return ("operations/operational-rules.md", "\n".join(lines), deps)


def compile_host_pages(memories, claude_mds, db_data):
    """P0: Compile per-host pages for notable hosts."""
    # Collect all hostnames that appear in incidents or have dedicated CLAUDE.md mentions
    hostnames = set()
    for inc in db_data["incidents"]:
        if inc.get("hostname"):
            hostnames.add(inc["hostname"])

    # Also add key infrastructure hosts
    for h in [
        "nl-fw01", "nl-pve01", "nl-pve02", "nl-pve03",
        "nl-claude01", "nl-openclaw01", "nl-gpu01",
        "gr-fw01", "gr-pve01", "gr-pve02",
        "nl-sw01", "nl-nas01",
    ]:
        hostnames.add(h)

    results = []
    for hostname in sorted(hostnames):
        lines = [f"# {hostname}", ""]

        # Site detection
        site = "gr" if hostname.startswith("grskg") else "nl"
        lines.append(f"**Site:** {'GR (Skagkia)' if site == 'gr' else 'NL (Leiden)'}")
        lines.append("")

        # CLAUDE.md mentions
        claude_mentions = []
        for c in claude_mds:
            if hostname.lower() in c["content"].lower():
                # Extract lines mentioning the host
                mention_lines = []
                for line in c["content"].split("\n"):
                    if hostname.lower() in line.lower():
                        mention_lines.append(line.strip())
                if mention_lines:
                    claude_mentions.append({
                        "file": c["rel"],
                        "site": c["site"],
                        "mentions": mention_lines[:5],
                    })

        if claude_mentions:
            lines.append("## Knowledge Base References")
            lines.append("")
            for cm in claude_mentions:
                lines.append(f"**{cm['site']}:{cm['file']}**")
                for ml in cm["mentions"]:
                    lines.append(f"- {ml}")
                lines.append("")

        # Incidents
        host_incidents = [i for i in db_data["incidents"] if i.get("hostname") == hostname]
        if host_incidents:
            lines.append("## Incident History")
            lines.append("")
            lines.append("| Date | Alert | Root Cause | Resolution | Confidence |")
            lines.append("|------|-------|------------|------------|------------|")
            for inc in host_incidents:
                date = (inc.get("created_at") or "")[:10]
                alert = inc.get("alert_rule", "")
                cause = (inc.get("root_cause") or "")[:60]
                res = (inc.get("resolution") or "")[:60]
                conf = inc.get("confidence", -1)
                conf_str = f"{conf:.1f}" if conf >= 0 else "N/A"
                lines.append(f"| {date} | {alert} | {cause} | {res} | {conf_str} |")
            lines.append("")

        # Lessons learned (from incidents on this host)
        host_issues = {i.get("issue_id") for i in host_incidents if i.get("issue_id")}
        host_lessons = [l for l in db_data["lessons"] if l.get("issue_id") in host_issues]
        if host_lessons:
            lines.append("## Lessons Learned")
            lines.append("")
            for l in host_lessons:
                lines.append(f"- **{l.get('issue_id', 'unknown')}**: {l['lesson']}")
            lines.append("")

        # Memory mentions
        host_memories = []
        for m in memories:
            if hostname.lower() in m["body"].lower():
                host_memories.append(m)
        if host_memories:
            lines.append("## Related Memory Entries")
            lines.append("")
            for m in host_memories:
                name = m["meta"].get("name", m["filename"])
                mtype = m["meta"].get("type", "unknown")
                lines.append(f"- **{name}** ({mtype}): {m['meta'].get('description', '')}")
            lines.append("")

        # 03_Lab references
        lab_host_dir = os.path.join(LAB_DIR, site.upper() if site == "gr" else "NL", "Servers", hostname)
        if os.path.isdir(lab_host_dir):
            lab_files = []
            for root, _d, files in os.walk(lab_host_dir):
                for fn in files:
                    lab_files.append(os.path.relpath(os.path.join(root, fn), LAB_DIR))
            if lab_files:
                lines.append("## Physical Documentation (03_Lab)")
                lines.append("")
                for lf in sorted(lab_files)[:20]:
                    lines.append(f"- `03_Lab/{lf}`")
                lines.append("")

        lines.append(f"*Compiled: {NOW}*")

        deps = (
            [c["path"] for c in claude_mds if hostname.lower() in c["content"].lower()]
            + ["db:incident_knowledge", "db:lessons_learned"]
            + [m["path"] for m in host_memories]
        )
        results.append((f"hosts/{hostname}.md", "\n".join(lines), deps))

    return results


def compile_incident_timeline(db_data, docs):
    """P0: Chronological incident timeline."""
    incidents = db_data["incidents"]
    if not incidents:
        return None

    lines = [
        "# Incident Timeline",
        "",
        f"> {len(incidents)} incidents recorded. Compiled {NOW}.",
        "",
        "| Date | Host | Site | Alert | Root Cause | Issue | Confidence |",
        "|------|------|------|-------|------------|-------|------------|",
    ]

    for inc in incidents:
        date = (inc.get("created_at") or "")[:10]
        host = inc.get("hostname", "")
        site = inc.get("site", "").upper()
        alert = inc.get("alert_rule", "")
        cause = (inc.get("root_cause") or "")[:50]
        issue = inc.get("issue_id", "")
        conf = inc.get("confidence", -1)
        conf_str = f"{conf:.1f}" if conf >= 0 else "N/A"
        host_link = f"[{host}](../hosts/{host}.md)" if host else ""
        lines.append(f"| {date} | {host_link} | {site} | {alert} | {cause} | {issue} | {conf_str} |")

    # Lessons learned
    if db_data["lessons"]:
        lines.append("")
        lines.append("## Lessons Learned")
        lines.append("")
        for l in db_data["lessons"]:
            lines.append(f"- **{l.get('issue_id', '')}** ({(l.get('created_at') or '')[:10]}): {l['lesson']}")

    # Link to postmortems
    postmortems = [d for d in docs if "postmortem" in d["filename"].lower()]
    if postmortems:
        lines.append("")
        lines.append("## Postmortems")
        lines.append("")
        for pm in postmortems:
            lines.append(f"- [{pm['filename']}](../../docs/{pm['filename']})")

    lines.append("")
    lines.append(f"*Compiled: {NOW}*")
    deps = ["db:incident_knowledge", "db:lessons_learned"] + [d["path"] for d in postmortems]
    return ("incidents/index.md", "\n".join(lines), deps)


def compile_topology(claude_mds, memories):
    """P1: Network topology pages."""
    results = []

    # VPN Mesh
    vpn_memories = [m for m in memories if any(
        k in m["filename"].lower()
        for k in ["vpn", "vti", "wan", "ipsec", "freedom", "tunnel"]
    )]
    vpn_claude = [c for c in claude_mds if any(
        k in c["content"].lower()
        for k in ["vti", "crypto-map", "tunnel", "bgp", "ipsec"]
    )]

    lines = [
        "# VPN Mesh & Dual-WAN Architecture",
        "",
        f"> Compiled from {len(vpn_memories)} memory files + {len(vpn_claude)} CLAUDE.md files. {NOW}.",
        "",
    ]

    for m in vpn_memories:
        name = m["meta"].get("name", m["filename"])
        lines.append(f"## {name}")
        lines.append("")
        lines.append(m["body"])
        lines.append("")
        lines.append(f"*Source: `memory/{m['filename']}`*")
        lines.append("")

    deps = [m["path"] for m in vpn_memories] + [c["path"] for c in vpn_claude]
    results.append(("topology/vpn-mesh.md", "\n".join(lines), deps))

    # Per-site topology
    for site_code, site_name in [("nl", "NL (Leiden)"), ("gr", "GR (Skagkia)")]:
        site_claude = [c for c in claude_mds if c["site"] == site_code]
        site_memories = [m for m in memories if site_code in m["filename"].lower()]
        lines = [
            f"# {site_name} Site Topology",
            "",
            f"> Compiled from {len(site_claude)} CLAUDE.md files + {len(site_memories)} memory files. {NOW}.",
            "",
            "## CLAUDE.md Files",
            "",
        ]
        for c in site_claude:
            # Extract first 5 non-empty lines as summary
            summary_lines = [l for l in c["content"].split("\n") if l.strip()][:5]
            lines.append(f"### {c['rel']}")
            lines.append("")
            for sl in summary_lines:
                lines.append(sl)
            lines.append("")

        deps = [c["path"] for c in site_claude] + [m["path"] for m in site_memories]
        results.append((f"topology/{site_code}-site.md", "\n".join(lines), deps))

    # K8s clusters
    k8s_claude = [c for c in claude_mds if "k8s" in c["rel"].lower()]
    k8s_memories = [m for m in memories if "k8s" in m["filename"].lower()]
    lines = [
        "# Kubernetes Clusters",
        "",
        f"> Compiled from {len(k8s_claude)} CLAUDE.md files + {len(k8s_memories)} memories. {NOW}.",
        "",
    ]
    for c in k8s_claude:
        lines.append(f"## {c['site'].upper()}: {c['rel']}")
        lines.append("")
        # Extract K8s-relevant sections
        for line in c["content"].split("\n"):
            if any(k in line.lower() for k in ["cilium", "cluster", "node", "worker", "control", "etcd", "pod"]):
                lines.append(line)
        lines.append("")

    deps = [c["path"] for c in k8s_claude] + [m["path"] for m in k8s_memories]
    results.append(("topology/k8s-clusters.md", "\n".join(lines), deps))

    return results


def compile_services(claude_mds, memories, docs, skills, db_data):
    """P1: Service architecture pages."""
    results = []

    # ChatOps Platform
    chatops_docs = [d for d in docs if "architecture" in d["filename"].lower() or "chatops" in d["filename"].lower()]
    lines = [
        "# ChatOps Platform",
        "",
        f"> The agentic infrastructure orchestration system. Compiled {NOW}.",
        "",
        "## Architecture",
        "",
        "3 subsystems: **ChatOps** (infra alerts), **ChatSecOps** (security alerts), **ChatDevOps** (dev tasks).",
        "",
        "Pipeline: External trigger -> n8n webhook -> OpenClaw triage (Tier 1) -> Claude Code (Tier 2) -> Human approval (Tier 3)",
        "",
    ]

    # Extract key stats from memories
    arch_memories = [m for m in memories if any(
        k in m["filename"].lower() for k in ["matrix", "runner", "agentic", "bridge"]
    )]
    for m in arch_memories:
        lines.append(f"### {m['meta'].get('name', m['filename'])}")
        lines.append("")
        lines.append(m["body"][:500])
        lines.append("")

    deps = [d["path"] for d in chatops_docs] + [m["path"] for m in arch_memories]
    results.append(("services/chatops-platform.md", "\n".join(lines), deps))

    # OpenClaw
    oc_memories = [m for m in memories if "openclaw" in m["filename"].lower() or "knowledge_injection" in m["filename"].lower()]
    lines = [
        "# OpenClaw (Tier 1 Agent)",
        "",
        f"> GPT-5.1 triage agent on nl-openclaw01. Compiled {NOW}.",
        "",
        "## Skills",
        "",
    ]
    for s in skills:
        lines.append(f"- **{s['name']}** ({s['line_count']} lines): {s['header'][:100]}")
    lines.append("")

    # OpenClaw memory entries
    if db_data["openclaw_mem"]:
        lines.append(f"## Operational Memory ({len(db_data['openclaw_mem'])} entries)")
        lines.append("")
        cats = {}
        for om in db_data["openclaw_mem"]:
            cat = om.get("category", "uncategorized")
            cats.setdefault(cat, []).append(om)
        for cat, entries in sorted(cats.items()):
            lines.append(f"### {cat} ({len(entries)} entries)")
            lines.append("")
            for e in entries[:10]:
                lines.append(f"- `{e['key']}`: {str(e['value'])[:80]}")
            if len(entries) > 10:
                lines.append(f"- ... and {len(entries) - 10} more")
            lines.append("")

    deps = [m["path"] for m in oc_memories] + [s["path"] for s in skills] + ["db:openclaw_memory"]
    results.append(("services/openclaw.md", "\n".join(lines), deps))

    # RAG Pipeline
    rag_memories = [m for m in memories if any(
        k in m["filename"].lower() for k in ["rag", "knowledge", "semantic"]
    )]
    lines = [
        "# RAG Pipeline",
        "",
        f"> 3-channel hybrid retrieval. Compiled {NOW}.",
        "",
        "## Channels",
        "",
        "1. **Hybrid Semantic Search (RRF)** — nomic-embed-text 768 dims + keyword LIKE, blended via Reciprocal Rank Fusion",
        "2. **Deterministic Hostname Routing** — claude-knowledge-lookup.sh pattern-matches hostname to CLAUDE.md files",
        "3. **XML-Tagged Injection** — `<incident_knowledge>`, `<lessons_learned>`, `<operational_memory>` tags",
        "",
    ]
    for m in rag_memories:
        lines.append(f"### {m['meta'].get('name', m['filename'])}")
        lines.append("")
        lines.append(m["body"])
        lines.append("")

    deps = [m["path"] for m in rag_memories]
    results.append(("services/rag-pipeline.md", "\n".join(lines), deps))

    # Security Ops
    sec_memories = [m for m in memories if "security" in m["filename"].lower()]
    sec_docs = [d for d in docs if "sec" in d["filename"].lower()]
    lines = [
        "# Security Operations (ChatSecOps)",
        "",
        f"> CrowdSec, scanners, MITRE ATT&CK. Compiled {NOW}.",
        "",
    ]
    for m in sec_memories:
        lines.append(f"## {m['meta'].get('name', m['filename'])}")
        lines.append("")
        lines.append(m["body"])
        lines.append("")
    for d in sec_docs:
        lines.append(f"## {d['filename']}")
        lines.append("")
        lines.append(d["content"][:500])
        lines.append("")

    deps = [m["path"] for m in sec_memories] + [d["path"] for d in sec_docs]
    results.append(("services/security-ops.md", "\n".join(lines), deps))

    # SeaweedFS
    swfs_memories = [m for m in memories if "seaweedfs" in m["filename"].lower()]
    lines = [
        "# SeaweedFS Cross-Site Storage",
        "",
        f"> Compiled {NOW}.",
        "",
    ]
    for m in swfs_memories:
        lines.append(m["body"])
        lines.append("")

    deps = [m["path"] for m in swfs_memories]
    results.append(("services/seaweedfs.md", "\n".join(lines), deps))

    return results


def compile_runbooks(skills):
    """P1: OpenClaw skill runbooks."""
    lines = [
        "# Runbooks (OpenClaw Skills)",
        "",
        f"> {len(skills)} operational skills. Compiled {NOW}.",
        "",
        "| Skill | Lines | Purpose |",
        "|-------|-------|---------|",
    ]
    for s in skills:
        purpose = s["header"].split("\n")[0][:80] if s["header"] != "(no description)" else "—"
        lines.append(f"| {s['name']} | {s['line_count']} | {purpose} |")

    lines.append("")

    for s in skills:
        lines.append(f"## {s['name']}")
        lines.append("")
        lines.append(f"**Path:** `{os.path.relpath(s['path'], BASE_DIR)}`")
        lines.append(f"**Lines:** {s['line_count']}")
        lines.append("")
        if s["header"] != "(no description)":
            lines.append("```")
            lines.append(s["header"])
            lines.append("```")
        lines.append("")

    deps = [s["path"] for s in skills]
    return ("operations/runbooks.md", "\n".join(lines), deps)


def compile_emergency_procedures(memories, claude_mds):
    """P1: Emergency/OOB procedures."""
    oob_memories = [m for m in memories if any(
        k in m["filename"].lower() for k in ["oob", "emergency", "ssh", "asa", "stepstone", "maintenance"]
    )]
    lines = [
        "# Emergency Procedures",
        "",
        f"> OOB access, ASA SSH, PiKVM, maintenance companion. Compiled {NOW}.",
        "",
    ]
    for m in oob_memories:
        lines.append(f"## {m['meta'].get('name', m['filename'])}")
        lines.append("")
        lines.append(m["body"])
        lines.append("")

    deps = [m["path"] for m in oob_memories]
    return ("operations/emergency-procedures.md", "\n".join(lines), deps)


def compile_data_trust(memories):
    """P1: Data trust hierarchy page."""
    trust_memories = [m for m in memories if "trust" in m["filename"].lower()]
    lines = [
        "# Data Trust Hierarchy",
        "",
        f"> The foundational principle for all infrastructure decisions. Compiled {NOW}.",
        "",
        "## The 4 Levels",
        "",
        "1. **Running config on the live device** — SSH and check. This is the ONLY 100% truth.",
        "2. **LibreNMS** — active monitoring, real-time status.",
        "3. **NetBox** — CMDB inventory. Accurate but manually maintained.",
        "4. **03_Lab, GitLab IaC, backups** — supplementary reference. Can be stale.",
        "",
        "**If 03_Lab contradicts a live device, the live device wins. Always.**",
        "",
    ]
    for m in trust_memories:
        lines.append(f"## {m['meta'].get('name', m['filename'])}")
        lines.append("")
        lines.append(m["body"])
        lines.append("")

    deps = [m["path"] for m in trust_memories]
    return ("operations/data-trust-hierarchy.md", "\n".join(lines), deps)


def compile_decisions(memories, docs):
    """P1: Architectural decisions index."""
    # Extract decisions from project-type memories
    project_memories = [m for m in memories if m["meta"].get("type") == "project"]
    lines = [
        "# Architectural Decisions",
        "",
        f"> Extracted from {len(project_memories)} project memory files. Compiled {NOW}.",
        "",
    ]

    for m in sorted(project_memories, key=lambda x: x["filename"]):
        name = m["meta"].get("name", m["filename"])
        desc = m["meta"].get("description", "")
        lines.append(f"- **{name}**: {desc}")

    lines.append("")
    lines.append("## Audit Reports")
    lines.append("")
    audit_docs = [d for d in docs if "audit" in d["filename"].lower() or "eval" in d["filename"].lower()]
    for d in audit_docs:
        lines.append(f"- [{d['filename']}](../../docs/{d['filename']})")

    deps = [m["path"] for m in project_memories] + [d["path"] for d in audit_docs]
    return ("decisions/index.md", "\n".join(lines), deps)


def compile_lab_index(lab):
    """P2: 03_Lab file manifest."""
    lines = [
        "# 03_Lab Reference Library",
        "",
        f"> ~{lab['total_files']:,} files, ~{lab['total_size_mb']:,.0f} MB. Compiled {NOW}.",
        "",
        "Physical documentation, wiring diagrams, firmware, topology. Synced via Syncthing.",
        "",
        "**WARNING:** 03_Lab is supplementary reference (Level 4 in the data trust hierarchy).",
        "Always verify against live device config.",
        "",
        "## Structure",
        "",
        "| Directory | Files | Size (MB) | Subdirectories |",
        "|-----------|-------|-----------|----------------|",
    ]
    for dirname, info in sorted(lab["structure"].items()):
        subdirs = ", ".join(info["subdirs"][:5])
        if len(info["subdirs"]) > 5:
            subdirs += f" (+{len(info['subdirs']) - 5} more)"
        lines.append(f"| {dirname} | {info['files']:,} | {info['size_mb']:,.1f} | {subdirs} |")

    lines.append("")
    lines.append(f"**Path:** `/app/reference-library/`")
    lines.append(f"**Query tool:** `openclaw/skills/lab-lookup/lab-lookup.sh`")
    lines.append("")
    lines.append("### Available Commands")
    lines.append("")
    lines.append("- `port-map <hostname>` — switch port, VLAN, patchpanel location")
    lines.append("- `nic-config <hostname>` — NIC interfaces, bonds, VLANs, IPs")
    lines.append("- `vlan-devices <vlan_id>` — all devices on a VLAN")
    lines.append("- `switch-ports <switch>` — all populated ports on a switch")
    lines.append("- `docs <hostname>` — list reference files for a host")
    lines.append("- `ups-pdu <site>` — UPS and PDU port assignments")

    return ("lab/index.md", "\n".join(lines), ["lab:manifest"])


def compile_health_report(memories, claude_mds, db_data, skills):
    """P3: Staleness report and coverage matrix."""
    issues = []
    coverage = {"hosts_with_pages": 0, "hosts_in_incidents": 0, "skills_documented": 0}

    # 1. Stale memories (> 60 days with specific file/line references)
    for m in memories:
        body = m["body"]
        if re.search(r":\d+", body) or re.search(r"line \d+", body, re.I):
            # Has line number references — likely to rot
            issues.append({
                "type": "staleness",
                "severity": "medium",
                "message": f"Memory `{m['filename']}` references specific line numbers (may be stale)",
            })

    # 2. Incidents without lessons
    incident_issues = {i["issue_id"] for i in db_data["incidents"] if i.get("issue_id")}
    lesson_issues = {l["issue_id"] for l in db_data["lessons"] if l.get("issue_id")}
    missing_lessons = incident_issues - lesson_issues - {"", None}
    for issue_id in sorted(missing_lessons):
        issues.append({
            "type": "coverage",
            "severity": "low",
            "message": f"Incident {issue_id} has no corresponding lesson_learned entry",
        })

    # 3. Contradiction detection — cross-check memories vs NetBox (MemPalace pattern)
    contradictions_flag = "--contradictions" in sys.argv
    if contradictions_flag:
        try:
            import urllib.request
            netbox_url = os.environ.get("NETBOX_URL", "https://netbox.example.net")
            netbox_token = os.environ.get("NETBOX_TOKEN", "")
            if not netbox_token:
                # Try reading from .env
                env_file = os.path.join(BASE_DIR, ".env")
                if os.path.isfile(env_file):
                    with open(env_file) as ef:
                        for eline in ef:
                            if eline.startswith("NETBOX_TOKEN="):
                                netbox_token = eline.strip().split("=", 1)[1].strip('"').strip("'")

            if netbox_token:
                # Query NetBox for device list
                req = urllib.request.Request(
                    f"{netbox_url}/api/dcim/devices/?limit=300&fields=id,name,primary_ip4,cluster,site,role",
                    headers={"Authorization": f"Token {netbox_token}", "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    nb_data = json.loads(resp.read())
                nb_devices = {}
                for dev in nb_data.get("results", []):
                    nb_devices[dev["name"]] = {
                        "ip": (dev.get("primary_ip4") or {}).get("address", "").split("/")[0],
                        "site": (dev.get("site") or {}).get("slug", ""),
                        "role": (dev.get("role") or {}).get("slug", ""),
                    }

                # Cross-check memories mentioning hosts
                host_pattern = re.compile(r"\b((?:nllei|grskg)\d{2}[a-z0-9]+)\b")
                for m in memories:
                    mentioned = set(host_pattern.findall(m["body"]))
                    for hostname in mentioned:
                        if hostname in nb_devices:
                            nb = nb_devices[hostname]
                            # Check for IP contradictions
                            ip_pattern = re.compile(r"(?:IP|address)[:\s]+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
                            for ip_match in ip_pattern.finditer(m["body"]):
                                mem_ip = ip_match.group(1)
                                if nb["ip"] and mem_ip != nb["ip"]:
                                    issues.append({
                                        "type": "contradiction",
                                        "severity": "high",
                                        "message": f"Memory `{m['filename']}` claims {hostname} IP {mem_ip}, NetBox says {nb['ip']}",
                                    })

                            # Check for site contradictions
                            site_pattern = re.compile(r"site[:\s]+(nl|gr)", re.I)
                            for site_match in site_pattern.finditer(m["body"]):
                                mem_site = site_match.group(1).lower()
                                if nb["site"] and mem_site != nb["site"]:
                                    issues.append({
                                        "type": "contradiction",
                                        "severity": "high",
                                        "message": f"Memory `{m['filename']}` claims {hostname} site={mem_site}, NetBox says {nb['site']}",
                                    })
        except Exception as e:
            issues.append({
                "type": "warning",
                "severity": "low",
                "message": f"Contradiction detection skipped: {e}",
            })

    # 4. Skills without documentation
    coverage["skills_documented"] = len(skills)

    # 5. Count hosts
    incident_hosts = {i["hostname"] for i in db_data["incidents"] if i.get("hostname")}
    coverage["hosts_in_incidents"] = len(incident_hosts)

    lines = [
        "# Knowledge Base Health Report",
        "",
        f"> Generated {NOW}.",
        "",
        "## Summary",
        "",
        f"- **Issues found:** {len(issues)}",
        f"- **Hosts in incidents:** {coverage['hosts_in_incidents']}",
        f"- **Skills documented:** {coverage['skills_documented']}",
        f"- **Memory files:** {len(memories)}",
        f"- **CLAUDE.md files:** {len(claude_mds)}",
        f"- **Incident records:** {len(db_data['incidents'])}",
        f"- **Lessons learned:** {len(db_data['lessons'])}",
        "",
    ]

    if issues:
        lines.append("## Issues")
        lines.append("")
        lines.append("| Severity | Type | Message |")
        lines.append("|----------|------|---------|")
        for issue in sorted(issues, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]):
            lines.append(f"| {issue['severity']} | {issue['type']} | {issue['message']} |")
        lines.append("")

    return ("health/staleness-report.md", "\n".join(lines), [])


def compile_coverage_matrix(memories, claude_mds, db_data, docs, skills, grafana, lab):
    """P3: Coverage matrix — what's compiled, what has gaps."""
    lines = [
        "# Coverage Matrix",
        "",
        f"> Source coverage audit. Compiled {NOW}.",
        "",
        "## Source Inventory",
        "",
        "| Source | Count | Status |",
        "|--------|-------|--------|",
        f"| Memory files (feedback) | {len([m for m in memories if m['meta'].get('type') == 'feedback'])} | Compiled to operational-rules.md |",
        f"| Memory files (project) | {len([m for m in memories if m['meta'].get('type') == 'project'])} | Compiled to decisions/index.md |",
        f"| CLAUDE.md files | {len(claude_mds)} | Compiled to topology + host pages |",
        f"| incident_knowledge | {len(db_data['incidents'])} | Compiled to incidents/index.md |",
        f"| lessons_learned | {len(db_data['lessons'])} | Compiled to incidents/index.md |",
        f"| openclaw_memory | {len(db_data['openclaw_mem'])} | Compiled to services/openclaw.md |",
        f"| docs/*.md | {len(docs)} | Linked from relevant articles |",
        f"| OpenClaw skills | {len(skills)} | Compiled to operations/runbooks.md |",
        f"| Grafana dashboards | {len(grafana)} | Listed in coverage matrix |",
        f"| 03_Lab files | ~{lab['total_files']:,} | Manifest in lab/index.md |",
        "",
        "## Grafana Dashboards",
        "",
        "| Dashboard | Panels |",
        "|-----------|--------|",
    ]
    for g in grafana:
        lines.append(f"| {g['title']} | {g['panel_count']} |")

    return ("health/coverage-matrix.md", "\n".join(lines), [])


def compile_master_index(all_articles):
    """P3: Master index with categorized links to all wiki articles."""
    categories = {}
    for path, _content, _deps in all_articles:
        cat = path.split("/")[0] if "/" in path else "root"
        categories.setdefault(cat, []).append(path)

    lines = [
        "# Example Corp Knowledge Base",
        "",
        f"> Auto-compiled wiki from 7+ knowledge sources. Last compiled: {NOW}.",
        f"> {len(all_articles)} articles across {len(categories)} categories.",
        "",
        "## How This Works",
        "",
        "This wiki is **compiled by `scripts/wiki-compile.py`** from:",
        "- 70+ memory files (operational feedback, project knowledge)",
        "- 55 CLAUDE.md files across 6 repos (per-host, per-service documentation)",
        "- SQLite tables: incident_knowledge, lessons_learned, openclaw_memory",
        "- docs/ directory (architecture, postmortems, audits)",
        "- 15 OpenClaw skill scripts",
        "- 5 Grafana dashboards",
        "- 03_Lab reference library (~5,200 files manifest)",
        "",
        "**Do not edit wiki files directly** — they are overwritten on each compilation.",
        "Edit the source files instead.",
        "",
    ]

    order = ["operations", "hosts", "incidents", "topology", "services", "decisions", "lab", "health"]
    cat_names = {
        "operations": "Operations & Runbooks",
        "hosts": "Host Pages",
        "incidents": "Incidents",
        "topology": "Network Topology",
        "services": "Services & Architecture",
        "decisions": "Decisions",
        "lab": "Physical Lab",
        "health": "Health & Coverage",
    }

    for cat in order:
        if cat not in categories:
            continue
        lines.append(f"## {cat_names.get(cat, cat.title())}")
        lines.append("")
        for path in sorted(categories[cat]):
            name = os.path.splitext(os.path.basename(path))[0].replace("-", " ").title()
            lines.append(f"- [{name}]({path})")
        lines.append("")

    return ("index.md", "\n".join(lines), [])


# ── Main Compilation ───────────────────────────────────────────────────────────


def write_article(article_path, content):
    """Write a wiki article to disk."""
    full_path = os.path.join(WIKI_DIR, article_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(content)


def run_compilation(force=False, single_article=None, health_only=False, dry_run=False):
    """Main compilation entry point."""
    print(f"[wiki-compile] Starting {'full' if force else 'incremental'} compilation at {NOW}")

    # Read all sources
    print("[wiki-compile] Reading sources...")
    memories = read_memory_files()
    claude_mds = read_claude_md_files()
    db_data = read_sqlite_tables()
    docs = read_docs()
    skills = read_skills()
    grafana = read_grafana()
    lab = read_lab_manifest()

    print(f"  memories={len(memories)}, claude_mds={len(claude_mds)}, "
          f"incidents={len(db_data['incidents'])}, lessons={len(db_data['lessons'])}, "
          f"openclaw_mem={len(db_data['openclaw_mem'])}, docs={len(docs)}, "
          f"skills={len(skills)}, grafana={len(grafana)}, lab_files={lab['total_files']}")

    # Health check mode
    if health_only:
        health = compile_health_report(memories, claude_mds, db_data, skills)
        coverage = compile_coverage_matrix(memories, claude_mds, db_data, docs, skills, grafana, lab)
        if dry_run:
            print(f"[dry-run] Would write: {health[0]}, {coverage[0]}")
        else:
            write_article(health[0], health[1])
            write_article(coverage[0], coverage[1])
            print(f"[wiki-compile] Health report written to wiki/{health[0]}")
        return

    # Compute checksums for incremental compilation
    new_checksums = compute_source_checksums(memories, claude_mds, db_data, docs, skills, grafana, lab)
    old_state = load_compile_state()
    old_checksums = old_state.get("checksums", {})

    changed = set()
    if force:
        changed = set(new_checksums.keys())
    else:
        for key, val in new_checksums.items():
            if old_checksums.get(key) != val:
                changed.add(key)
        # Also compile if new keys appeared
        for key in new_checksums:
            if key not in old_checksums:
                changed.add(key)

    if not changed and not force:
        print("[wiki-compile] No source changes detected. Nothing to compile.")
        return

    print(f"[wiki-compile] {len(changed)} source(s) changed. Compiling articles...")

    # Collect all articles
    all_articles = []
    source_map = {}

    # P0: Operational Rules
    result = compile_operational_rules(memories)
    if result:
        all_articles.append(result)

    # P0: Host Pages
    host_results = compile_host_pages(memories, claude_mds, db_data)
    if host_results:
        all_articles.extend(host_results)

    # P0: Incident Timeline
    result = compile_incident_timeline(db_data, docs)
    if result:
        all_articles.append(result)

    # P1: Topology
    topo_results = compile_topology(claude_mds, memories)
    all_articles.extend(topo_results)

    # P1: Services
    svc_results = compile_services(claude_mds, memories, docs, skills, db_data)
    all_articles.extend(svc_results)

    # P1: Runbooks
    result = compile_runbooks(skills)
    if result:
        all_articles.append(result)

    # P1: Emergency Procedures
    result = compile_emergency_procedures(memories, claude_mds)
    if result:
        all_articles.append(result)

    # P1: Data Trust Hierarchy
    result = compile_data_trust(memories)
    if result:
        all_articles.append(result)

    # P1: Decisions
    result = compile_decisions(memories, docs)
    if result:
        all_articles.append(result)

    # P2: Lab Index
    result = compile_lab_index(lab)
    if result:
        all_articles.append(result)

    # P3: Health Report
    result = compile_health_report(memories, claude_mds, db_data, skills)
    if result:
        all_articles.append(result)

    # P3: Coverage Matrix
    result = compile_coverage_matrix(memories, claude_mds, db_data, docs, skills, grafana, lab)
    if result:
        all_articles.append(result)

    # P3: Master Index (must be last — needs all_articles)
    result = compile_master_index(all_articles)
    all_articles.append(result)

    # Filter for single article if requested
    if single_article:
        all_articles = [a for a in all_articles if a[0] == single_article]
        if not all_articles:
            print(f"[wiki-compile] Article '{single_article}' not found in compilation targets.")
            return

    # Write or dry-run
    if dry_run:
        print(f"\n[dry-run] Would compile {len(all_articles)} articles:")
        for path, content, deps in all_articles:
            print(f"  {path} ({len(content)} chars, {len(deps)} source deps)")
        return

    written = 0
    for path, content, deps in all_articles:
        write_article(path, content)
        source_map[path] = deps
        written += 1

    # Save state
    save_compile_state({"checksums": new_checksums})
    save_source_map(source_map)

    print(f"\n[wiki-compile] Done. {written} articles written to wiki/.")
    print(f"[wiki-compile] State saved to {COMPILE_STATE}")

    # Trigger wiki-embed if kb-semantic-search.py exists
    kb_script = os.path.join(BASE_DIR, "scripts", "kb-semantic-search.py")
    if os.path.isfile(kb_script):
        print("[wiki-compile] Triggering wiki-embed for RAG integration...")
        try:
            subprocess.run(
                [sys.executable, kb_script, "wiki-embed"],
                timeout=120, capture_output=True
            )
            print("[wiki-compile] Wiki articles embedded successfully.")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[wiki-compile] Wiki-embed skipped: {e}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    force = "--full" in sys.argv
    dry_run = "--dry-run" in sys.argv
    health_only = "--health" in sys.argv
    single_article = None

    for i, arg in enumerate(sys.argv):
        if arg == "--article" and i + 1 < len(sys.argv):
            single_article = sys.argv[i + 1]

    # Pre-step (IFRNLLEI01PRD-715): refresh docs/skills-index.md from
    # .claude/{agents,skills,commands}/**/*.md frontmatter. Never fatal —
    # the drift test (scripts/qa/suites/test-656-skill-index-fresh.sh) is
    # the hard gate; this is belt-and-braces for the daily cron.
    if not dry_run and not health_only:
        try:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            renderer = os.path.join(repo_root, "scripts", "render-skill-index.py")
            target = os.path.join(repo_root, "docs", "skills-index.md")
            if os.path.exists(renderer):
                subprocess.run(
                    ["python3", renderer, target],
                    check=False,
                    timeout=30,
                )
        except Exception as e:
            print(f"[wiki-compile] skill-index refresh skipped: {e}")

    run_compilation(
        force=force,
        single_article=single_article,
        health_only=health_only,
        dry_run=dry_run,
    )
