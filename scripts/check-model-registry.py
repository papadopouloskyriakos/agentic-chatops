#!/usr/bin/env python3
"""Flag stragglers: a live model-SELECTION caller pinning an Anthropic model id that is
NOT the current registry id (scripts/lib/models.py). Bench IFRNLLEI01PRD-1422 dim-10.

Future-readiness: adopting a newer model should be a one-line bump in models.py; this guard
catches any LIVE_SELECTION_CALLERS left pinning the old id. REPRODUCIBILITY_PINS are excluded
(intentionally frozen). It does NOT auto-bump anything — it only reports drift.

Exit 0 = no straggler / all current. Exit 1 = a live caller pins a non-current id.
"""
REDACTED_a7b84d63
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import models  # noqa: E402

CURRENT = set(models.ANTHROPIC_MODELS.values())
ANTHROPIC_RE = re.compile(r"claude-(?:haiku|sonnet|opus)-[0-9][0-9a-z-]*")


def main() -> int:
    stragglers = []
    for rel in models.LIVE_SELECTION_CALLERS:
        p = REPO / rel
        if not p.exists():
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for mid in ANTHROPIC_RE.findall(line):
                if mid not in CURRENT:
                    stragglers.append((rel, n, mid))

    if stragglers:
        print("MODEL REGISTRY DRIFT — live caller pins a non-current Anthropic id:",
              file=sys.stderr)
        for rel, n, mid in stragglers:
            cur = models.ANTHROPIC_MODELS.get(models.tier_for(mid), "?")
            print(f"  {rel}:{n}  {mid}  (current = {cur})", file=sys.stderr)
        print("  Bump scripts/lib/models.py + update the caller, or add to "
              "REPRODUCIBILITY_PINS if intentionally frozen.", file=sys.stderr)
        return 1
    print(f"check-model-registry: OK — {len(models.LIVE_SELECTION_CALLERS)} live callers all "
          f"track current registry ids {sorted(CURRENT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
