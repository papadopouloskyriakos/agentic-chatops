#!/usr/bin/env python3
"""write-workspace-guardrail-metrics.py — IFRNLLEI01PRD-1663 (Global Workspace paper takeaways).

Makes the 4 workspace-paper guardrails OWNED by the orchestrator control-plane so
they cannot drift dark once activated (the dark-component failure class the registry
exists to prevent). A benign READ-ONLY observer: it reports each guardrail's state,
never changes it.

Emits (node_exporter textfile collector -> discovered by the registry as prom:workspace_guardrail):
  workspace_guardrail_feature_active{feature}          1/0 — is the guardrail switched ON
  workspace_guardrail_prompt_patch_injectable{dimension} 1/0 — would the patch pass the Build Prompt
                                                       filter (active && !expired). Detects the
                                                       "activated-but-silently-dropped" drift.
  workspace_guardrail_last_run_timestamp               freshness / dead-man for THIS writer.

  (The silent-cognition guard, IFRNLLEI01PRD-1665, now fires in the Runner's Prepare Result node
  (Phase 5) — it suppresses an [AUTO-RESOLVE] lacking a fenced evidence block — so its on/off state
  is feature_active{silent_cognition_guard}; there is no demotions counter because Prepare Result has
  no queryable table. Its firing is operator-visible via the reply's GUARDRAIL EVIDENCE-MISSING banner.)

Not a mutation: no sentinel is touched, no patch flipped, no DB write. Safe to run live even while
every guardrail is OFF (it just reports "off"). Invoked by write-governance-metrics.py each cycle
(the autonomy-gate metrics writer, */15) so its .prom stays fresh without a new scheduler job.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get(
    "WORKSPACE_GUARDRAIL_OUT",
    "/var/lib/node_exporter/textfile_collector/workspace_guardrail.prom",
)
DB_PATH = os.environ.get("GATEWAY_DB", os.path.expanduser("~/gateway-state/gateway.db"))
PATCHES = os.path.join(REPO, "config", "prompt-patches.json")
CANARY_PROM = "/var/lib/node_exporter/textfile_collector/synthetic_canary.prom"

# The two staged prompt-patch dimensions this epic owns (items 1 & 3).
PATCH_DIMS = ("reasoning_transparency", "reflection_checkpoint")


def _sentinel_on(name: str) -> bool:
    """Mirror classify-session-risk.py::_envflag — env wins, else ~/gateway.<name>."""
    v = os.environ.get(name.upper())
    if v is not None:
        return v not in ("", "0", "false", "False", "no", "NO")
    return os.path.exists(os.path.expanduser(f"~/gateway.{name}"))


def _patches():
    try:
        return json.load(open(PATCHES))
    except Exception:
        return []


def _patch_injectable(patches: list, dimension: str) -> int:
    """1 iff a patch for this dimension would pass the Build Prompt node's filter
    (active && (!expires_at || expires_at > now)). Same predicate the Runner uses."""
    now = dt.datetime.now(dt.timezone.utc)
    for p in patches:
        if p.get("dimension") != dimension:
            continue
        if not p.get("active"):
            continue
        exp = p.get("expires_at")
        if exp:
            try:
                if dt.datetime.fromisoformat(exp.replace("Z", "+00:00")) <= now:
                    continue
            except Exception:
                pass
        return 1
    return 0


def _canary_caveat_present() -> int:
    try:
        return 1 if "eval_awareness_caveat" in open(CANARY_PROM).read() else 0
    except Exception:
        return 0


def _suppressions() -> tuple[int, int]:
    """(silent-cognition suppressions, total AUTO-RESOLVE replies) from session_transcripts —
    the ONLY live signal that the item-2 guard actually FIRES. The Prepare Result node rewrites
    [AUTO-RESOLVE] -> [AUTO-RESOLVE-SUPPRESSED:EVIDENCE-MISSING], and the final reply lands in
    session_transcripts.content. Read the suppression count against the AUTO-RESOLVE base rate:
    feature_active=1 with a healthy base rate but 0 suppressions over a long window is a hint the
    flag/regex plumbing broke (or, benignly, that every auto-resolve is properly evidenced)."""
    try:
        c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    except Exception:
        return 0, 0
    try:
        s = c.execute("SELECT COUNT(*) FROM session_transcripts WHERE content LIKE '%SUPPRESSED:EVIDENCE-MISSING%'").fetchone()[0]
        a = c.execute("SELECT COUNT(*) FROM session_transcripts WHERE content LIKE '%[AUTO-RESOLVE%'").fetchone()[0]
        return int(s or 0), int(a or 0)
    except Exception:
        return 0, 0
    finally:
        c.close()


def build() -> str:
    patches = _patches()
    guard_on = 1 if _sentinel_on("silent_cognition_guard") else 0
    rt_inj = _patch_injectable(patches, "reasoning_transparency")
    rc_inj = _patch_injectable(patches, "reflection_checkpoint")
    caveat = _canary_caveat_present()
    supp, autoresolves = _suppressions()
    ts = int(dt.datetime.now(dt.timezone.utc).timestamp())

    L = []
    L.append("# HELP workspace_guardrail_feature_active Whether each Global-Workspace-paper guardrail is switched ON (1) or staged/off (0). Ref IFRNLLEI01PRD-1663.")
    L.append("# TYPE workspace_guardrail_feature_active gauge")
    L.append(f'workspace_guardrail_feature_active{{feature="silent_cognition_guard"}} {guard_on}')
    L.append(f'workspace_guardrail_feature_active{{feature="reasoning_transparency"}} {rt_inj}')
    L.append(f'workspace_guardrail_feature_active{{feature="reflection_checkpoint"}} {rc_inj}')
    L.append(f'workspace_guardrail_feature_active{{feature="canary_eval_awareness_caveat"}} {caveat}')
    L.append("# HELP workspace_guardrail_prompt_patch_injectable 1 iff the staged prompt patch would pass the Build Prompt node filter (active && not-expired) — detects an activated-but-silently-dropped patch.")
    L.append("# TYPE workspace_guardrail_prompt_patch_injectable gauge")
    L.append(f'workspace_guardrail_prompt_patch_injectable{{dimension="reasoning_transparency"}} {rt_inj}')
    L.append(f'workspace_guardrail_prompt_patch_injectable{{dimension="reflection_checkpoint"}} {rc_inj}')
    L.append("# HELP workspace_guardrail_suppressions_total Real firings of the item-2 evidence-missing guard, counted from session_transcripts (the [AUTO-RESOLVE]->SUPPRESSED rewrite lands in the reply). The live 'is it firing' signal.")
    L.append("# TYPE workspace_guardrail_suppressions_total gauge")
    L.append(f"workspace_guardrail_suppressions_total {supp}")
    L.append("# HELP workspace_guardrail_autoresolve_replies_total AUTO-RESOLVE replies seen in session_transcripts — the base rate to read suppressions against (suppressions=0 with a healthy base rate + feature_active=1 over a long window hints the flag/regex plumbing broke).")
    L.append("# TYPE workspace_guardrail_autoresolve_replies_total gauge")
    L.append(f"workspace_guardrail_autoresolve_replies_total {autoresolves}")
    L.append("# HELP workspace_guardrail_last_run_timestamp Unix time this guardrail-health writer last ran (registry liveness / dead-man).")
    L.append("# TYPE workspace_guardrail_last_run_timestamp gauge")
    L.append(f"workspace_guardrail_last_run_timestamp {ts}")
    return "\n".join(L) + "\n"


def main() -> int:
    text = build()
    try:
        tmp = OUT + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, OUT)
    except Exception as e:
        print(f"[workspace-guardrail] metric write failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
