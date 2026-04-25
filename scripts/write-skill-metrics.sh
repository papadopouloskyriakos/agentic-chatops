#!/usr/bin/env bash
# write-skill-metrics.sh — emit Prometheus metrics describing skill-prereq
# health and per-skill version.
#
# IFRNLLEI01PRD-716 (Phase D).
#
# Run via cron `*/5 * * * *`. Emits to node_exporter textfile collector.
#
# Metrics:
#   chatops_skill_requires_ok{skill,kind,check}    — 0 / 1 per bin + per env
#   chatops_skill_requires_ok_all{skill,kind}      — 0 / 1 aggregate per skill
#   chatops_skill_version{skill,kind,version}      — info metric (always 1)
#   chatops_skill_count{kind}                      — counter per kind (agent/skill)
#   chatops_skill_metrics_last_run_timestamp       — unix seconds

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTDIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
mkdir -p "$OUTDIR"

TARGET="$OUTDIR/skill-metrics.prom"
TMP=$(mktemp "${TARGET}.XXXXXX")
trap 'rm -f "$TMP"' EXIT

REPO_ROOT="$REPO_ROOT" python3 <<'PY' > "$TMP"
import os, pathlib, shutil, time, yaml
root = pathlib.Path(os.environ["REPO_ROOT"])
lines = []
lines.append("# HELP chatops_skill_requires_ok Whether each declared bin/env prereq is satisfied (1=ok).")
lines.append("# TYPE chatops_skill_requires_ok gauge")
lines.append("# HELP chatops_skill_requires_ok_all 1 if all prereqs are satisfied for this skill, 0 otherwise.")
lines.append("# TYPE chatops_skill_requires_ok_all gauge")
lines.append("# HELP chatops_skill_version Info metric carrying the declared skill version.")
lines.append("# TYPE chatops_skill_version gauge")
lines.append("# HELP chatops_skill_count Total declared skills per kind.")
lines.append("# TYPE chatops_skill_count gauge")
lines.append("# HELP chatops_skill_metrics_last_run_timestamp Unix time of last export.")
lines.append("# TYPE chatops_skill_metrics_last_run_timestamp gauge")

surfaces = [
    ("agent", list((root / ".claude/agents").glob("*.md"))),
    ("skill", [p for p in (root / ".claude/skills").glob("*/SKILL.md")]),
]
counts = {"agent": 0, "skill": 0}

for kind, paths in surfaces:
    for p in sorted(paths):
        text = p.read_text()
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end < 0:
            continue
        try:
            fm = yaml.safe_load(text[4:end])
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        name = fm.get("name", p.stem)
        counts[kind] += 1
        version = str(fm.get("version", "unknown"))
        lines.append(
            f'chatops_skill_version{{skill="{name}",kind="{kind}",version="{version}"}} 1'
        )
        req = fm.get("requires") or {}
        if not isinstance(req, dict):
            continue
        bins = req.get("bins") or []
        env_vars = req.get("env") or []
        all_ok = 1
        for b in bins:
            ok = 1 if shutil.which(b) else 0
            if not ok:
                all_ok = 0
            lines.append(
                f'chatops_skill_requires_ok{{skill="{name}",kind="{kind}",check="bin:{b}"}} {ok}'
            )
        for e in env_vars:
            ok = 1 if os.environ.get(e) else 0
            if not ok:
                all_ok = 0
            lines.append(
                f'chatops_skill_requires_ok{{skill="{name}",kind="{kind}",check="env:{e}"}} {ok}'
            )
        lines.append(
            f'chatops_skill_requires_ok_all{{skill="{name}",kind="{kind}"}} {all_ok}'
        )

for kind, n in counts.items():
    lines.append(f'chatops_skill_count{{kind="{kind}"}} {n}')

lines.append(f"chatops_skill_metrics_last_run_timestamp {int(time.time())}")
print("\n".join(lines))
PY

# Atomic move + ensure node_exporter can read (runs as `nobody`; mktemp
# defaults to 0600 which is too restrictive for the textfile collector).
chmod 0644 "$TMP"
mv "$TMP" "$TARGET"
trap - EXIT
