#!/usr/bin/env python3
"""Fail if the chatops-workflow master skill inlined into the Runner's Build Prompt
node has drifted from the canonical .claude/skills/chatops-workflow/SKILL.md.

Bench IFRNLLEI01PRD-1422 dim-3 (modular design): the Build Prompt carries a frozen inline
copy of the master skill (var chatopsWorkflowSkill). The content is currently in parity, but
nothing guarded it — so a future SKILL.md edit could silently diverge from what dispatched
sessions actually receive. This is the parity guard (cron + QA), single-source-of-truth.

Exit 0 = parity (whitespace-normalized). Exit 1 = drift (prints a short diff).
Usage: check-skill-parity.py [--workflow workflows/claude-gateway-runner.json]
"""
import json
REDACTED_a7b84d63
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / "workflows" / "claude-gateway-runner.json"
SKILL = REPO / ".claude" / "skills" / "chatops-workflow" / "SKILL.md"


def _norm(s: str) -> str:
    # collapse all runs of whitespace; parity is about content, not formatting.
    return re.sub(r"\s+", " ", s).strip()


def extract_inline_skill(workflow_path: Path) -> str:
    wf = json.loads(workflow_path.read_text())
    bp = next((n for n in wf["nodes"] if n.get("name") == "Build Prompt"), None)
    if not bp:
        raise SystemExit("check-skill-parity: Build Prompt node not found")
    code = bp["parameters"]["jsCode"]
    # capture the RHS of `var chatopsWorkflowSkill = <literals>;`
    m = re.search(r"var\s+chatopsWorkflowSkill\s*=\s*(.+?);\s*\n", code, re.S)
    if not m:
        raise SystemExit("check-skill-parity: chatopsWorkflowSkill assignment not found")
    rhs = m.group(1)
    # pull every double-quoted JS string literal (with escapes) and JSON-decode each
    literals = re.findall(r'"(?:[^"\\]|\\.)*"', rhs)
    parts = []
    for lit in literals:
        try:
            parts.append(json.loads(lit))
        except json.JSONDecodeError:
            parts.append(lit.strip('"'))
    return "".join(parts)


def strip_frontmatter(md: str) -> str:
    if md.startswith("---"):
        parts = md.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return md


def main() -> int:
    wf_path = WORKFLOW
    if "--workflow" in sys.argv:
        wf_path = Path(sys.argv[sys.argv.index("--workflow") + 1])
    inline = _norm(extract_inline_skill(wf_path))
    canonical = _norm(strip_frontmatter(SKILL.read_text()))
    # the inline copy prefixes a header line; compare on the shared body suffix
    if canonical and canonical in inline:
        print(f"check-skill-parity: PARITY (SKILL.md body present in inline copy, "
              f"{len(canonical)} normalized chars)")
        return 0
    if inline == canonical:
        print("check-skill-parity: PARITY (exact)")
        return 0
    # report drift compactly
    print("check-skill-parity: DRIFT — inline Build-Prompt skill != SKILL.md")
    print(f"  inline normalized len={len(inline)}  SKILL.md body normalized len={len(canonical)}")
    # first divergence point
    for i, (a, b) in enumerate(zip(inline, canonical)):
        if a != b:
            print(f"  first divergence at char {i}: inline=...{inline[max(0,i-20):i+20]!r}... "
                  f"skill=...{canonical[max(0,i-20):i+20]!r}...")
            break
    return 1


if __name__ == "__main__":
    sys.exit(main())
