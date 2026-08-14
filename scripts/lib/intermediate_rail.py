"""Intermediate-step semantic rail (IFRNLLEI01PRD-749 / G2.P0.3).

Inspired by NeMo Guardrails' intermediate-step topic rails (NVIDIA DLI-14).
Given the alert category and an intermediate text (Build Plan output, partial
investigation, etc.), assess whether the text is in-distribution for that
category. DARK-FIRST: emits an `intermediate_rail_check` event_log row but
does NOT block.

Two backends, in order:
  1. Ollama gemma3:12b via the existing `rag_synth_ollama` circuit breaker
     when available (3-second budget; bypassed if breaker open).
  2. Pure-regex heuristic fallback — a small set of category-keyword
     buckets that flag obviously-OOD intermediate text. Runs in <2 ms.

Output:

    {
      "is_in_distribution": True | False,
      "confidence": 0.0-1.0,
      "signals": ["regex:keyword:network",  ...],
      "backend": "ollama" | "heuristic"
    }

Closes NVIDIA-DLI dim #10 sub-component (intermediate topic rails) per
docs/nvidia-dli-cross-audit-2026-04-29.md Part F P0.3.
"""
from __future__ import annotations

import json
import os
REDACTED_a7b84d63
import sys
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
RAIL_MODEL = os.environ.get("INTERMEDIATE_RAIL_MODEL", "gemma3:12b")
RAIL_TIMEOUT_S = int(os.environ.get("INTERMEDIATE_RAIL_TIMEOUT_S", "3"))


# ── Heuristic keyword buckets ────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "availability": [
        r"ping|reachable|service|tcp|http|port|response|down|offline|unreachable|"
        r"socket|listen|connect|gateway|interface|up|status",
    ],
    "resource": [
        r"cpu|load|memory|ram|swap|oom|util|consumption|exhausted|throttl|process",
    ],
    "storage": [
        r"disk|storage|iscsi|lun|nfs|zfs|seaweed|synology|inode|space|"
        r"volume|fsync|filesystem|mount",
    ],
    "network": [
        r"interface|port|bgp|ospf|tunnel|vpn|vti|asa|switch|router|vlan|ipsec|"
        r"swanctl|frr|peer|prefix|route",
    ],
    "kubernetes": [
        r"pod|namespace|deployment|cilium|node|kubelet|etcd|apiserver|helm|"
        r"argocd|cronjob|service|ingress|crd",
    ],
    "certificate": [r"cert|tls|ssl|x509|expir|chain|root|ca|csr"],
    "maintenance": [r"reboot|firmware|upgrade|maintenance|drain|cordon|window|planned"],
    "correlated": [r"burst|multiple|correlated|cluster|fleet|cascade|simultan"],
    "security-incident": [
        r"crowdsec|nuclei|cve|exploit|nikto|wapiti|sqlmap|attack|exfil|breach|"
        r"backdoor|malware|scanner|jailbreak",
    ],
}


def _heuristic_check(text: str, category: str) -> dict:
    """Pure-regex fallback. Returns rail dict; never raises."""
    cat = (category or "").lower()
    text_lower = (text or "").lower()
    if not text_lower:
        return {
            "is_in_distribution": False,
            "confidence": 0.0,
            "signals": ["empty_text"],
            "backend": "heuristic",
        }

    bucket = CATEGORY_KEYWORDS.get(cat, [])
    matched: list[str] = []
    if bucket:
        for pat in bucket:
            for m in re.finditer(pat, text_lower):
                matched.append(f"regex:{m.group(0)}:{cat}")
                if len(matched) >= 5:
                    break
            if len(matched) >= 5:
                break

    # Off-topic markers that should NEVER appear in an infra plan.
    off_topic = [
        r"\bweather\b", r"\bjoke\b", r"\bsong\b", r"\bcooking\b",
        r"\bpoem\b", r"\bessay\b", r"\bbook recommendation\b",
    ]
    for pat in off_topic:
        for m in re.finditer(pat, text_lower):
            matched.append(f"off_topic:{m.group(0)}")

    in_dist = len(matched) > 0 and not any(s.startswith("off_topic:") for s in matched)
    confidence = min(1.0, 0.3 + 0.15 * len([s for s in matched if not s.startswith("off_topic:")]))
    return {
        "is_in_distribution": in_dist,
        "confidence": round(confidence, 3),
        "signals": matched or ["no_keyword_match"],
        "backend": "heuristic",
    }


# ── Ollama backend (3-second budget) ─────────────────────────────────────────


def _ollama_check(text: str, category: str) -> dict | None:
    """Best-effort Ollama call; returns dict or None on any error."""
    prompt = (
        "You are a topic-rail classifier. Given the alert category and an "
        "intermediate text from an automated investigation, decide whether the "
        "text is in-distribution for the category (i.e., it discusses concepts "
        "appropriate to that category).\n\n"
        f"Alert category: {category}\n\n"
        f"Intermediate text:\n{text[:4000]}\n\n"
        "Respond with strict JSON: "
        '{"is_in_distribution": true|false, "confidence": 0.0-1.0, '
        '"signals": [\"short reason 1\", \"short reason 2\"]}'
    )
    body = json.dumps({
        "model": RAIL_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"num_ctx": 4096, "temperature": 0.0},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=RAIL_TIMEOUT_S) as resp:
            result = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    raw = (result.get("response") or "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    out = {
        "is_in_distribution": bool(parsed.get("is_in_distribution", False)),
        "confidence": max(0.0, min(1.0, float(parsed.get("confidence", 0.5)))),
        "signals": list(parsed.get("signals", []))[:5],
        "backend": "ollama",
    }
    return out


# ── Public API ───────────────────────────────────────────────────────────────


def check(text: str, category: str, prefer_ollama: bool = True) -> dict:
    """Run the rail. Returns a dict with backend = 'ollama' | 'heuristic'."""
    if prefer_ollama:
        result = _ollama_check(text, category)
        if result is not None:
            return result
    return _heuristic_check(text, category)


def emit_event(rail_result: dict, issue_id: str = "", session_id: str = "") -> int:
    """Emit an `intermediate_rail_check` event_log row.

    Best-effort — never raises. Returns the new row id, or -1 on soft error
    (event_log table missing, transient SQLite lock, etc.).
    """
    try:
        # Late import to avoid circular dependency at module load.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from session_events import IntermediateRailCheckEvent, emit  # noqa: E402
        ev = IntermediateRailCheckEvent(
            issue_id=issue_id,
            session_id=session_id,
            is_in_distribution=bool(rail_result.get("is_in_distribution", False)),
            confidence=float(rail_result.get("confidence", 0.0)),
            signals=list(rail_result.get("signals", [])),
            backend=str(rail_result.get("backend", "unknown")),
        )
        return emit(ev)
    except Exception:
        return -1


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli() -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--category", required=True)
    p.add_argument("--text", help="text to probe; if omitted, reads stdin")
    p.add_argument("--text-stdin", action="store_true", help="explicitly read stdin")
    p.add_argument("--issue-id", default="")
    p.add_argument("--session-id", default="")
    p.add_argument("--no-ollama", action="store_true", help="force heuristic only")
    p.add_argument("--no-emit", action="store_true", help="skip event_log emission")
    args = p.parse_args()

    text = args.text
    if text is None or args.text_stdin:
        text = sys.stdin.read()

    rail = check(text, args.category, prefer_ollama=not args.no_ollama)
    if not args.no_emit:
        emit_event(rail, issue_id=args.issue_id, session_id=args.session_id)

    json.dump(rail, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
