#!/usr/bin/env python3
"""2-model LLM-judge jury blend (IFRNLLEI01PRD-1096b).

Reads two Ollama /api/generate responses (each whose `response` is a judge-rubric
JSON), blends them to mitigate single-model bias, and prints an Anthropic-style
envelope ({"content":[{"text": blended_json}], "model", "usage"}) for llm-judge.sh
to parse downstream. Blend = mean of the numeric dimensions + overall_score;
recommended_action = the MOST CONSERVATIVE of the two (reject > improve > approve).

Robust by design: if either juror is unparseable, falls back to the one that
parsed (so the judge never breaks). Exits non-zero only if BOTH fail, in which
case the caller keeps the primary single-model response.

Usage: judge_jury_blend.py <juror1.json> <juror2.json> <model1> <model2>
"""
import json
REDACTED_a7b84d63
import sys

DIMS = ["investigation_quality", "evidence_based", "actionability",
        "safety_compliance", "completeness", "overall_score"]
_ACTION_RANK = {"reject": 2, "improve": 1, "approve": 0}


def _extract_judge(path):
    """Pull the judge-rubric JSON out of an Ollama response file. Balanced-brace
    scan (NOT the fragile {[^}]+} regex) so nested objects parse."""
    try:
        env = json.load(open(path))
        text = env.get("response", "")
        usage = (env.get("prompt_eval_count", 0), env.get("eval_count", 0))
    except Exception:
        return None, (0, 0)
    # find the first balanced {...}
    start = text.find("{")
    if start < 0:
        return None, usage
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1]), usage
                except Exception:
                    return None, usage
    return None, usage


def main():
    if len(sys.argv) < 5:
        return 1
    j1, u1 = _extract_judge(sys.argv[1])
    j2, u2 = _extract_judge(sys.argv[2])
    m1, m2 = sys.argv[3], sys.argv[4]

    if j1 and j2:
        blended = dict(j1)
        for d in DIMS:
            try:
                blended[d] = round((float(j1.get(d, -1)) + float(j2.get(d, -1))) / 2, 2)
            except Exception:
                pass
        a1 = str(j1.get("recommended_action", "improve")).lower()
        a2 = str(j2.get("recommended_action", "improve")).lower()
        blended["recommended_action"] = a1 if _ACTION_RANK.get(a1, 1) >= _ACTION_RANK.get(a2, 1) else a2
        blended["jury"] = {"models": [m1, m2],
                           "overall": [j1.get("overall_score"), j2.get("overall_score")],
                           "actions": [a1, a2]}
        model = f"{m1}+{m2}-jury"
    elif j1 or j2:
        blended = j1 or j2
        model = m1 if j1 else m2
    else:
        return 1  # both failed -> caller keeps primary

    out = {"content": [{"type": "text", "text": json.dumps(blended)}], "model": model,
           "usage": {"input_tokens": u1[0] + u2[0], "output_tokens": u1[1] + u2[1]}}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
