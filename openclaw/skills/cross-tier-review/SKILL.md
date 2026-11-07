---
name: cross-tier-review
description: Cross-tier review protocol — chain of verification for REVIEW REQUEST messages from Claude Code (Tier 2). Includes 5-step checklist and REVIEW_JSON output format.
allowed-tools: Bash
user-invocable: false
metadata:
  openclaw:
    always: true
---

# Cross-Tier Review Protocol — Chain of Verification

When you see "REVIEW REQUEST:" in an infra room, Claude Code (Tier 2) is asking you
to review its work because its confidence was below 0.7. You MUST perform a structured
verification before giving your verdict.

## Verification Checklist (execute ALL steps)

1. **CLAIM CHECK:** What factual claims does the analysis make? Use the `exec` tool to
   independently verify at least ONE claim (e.g., check a service status, query YT issue,
   look up a host in NetBox). Do NOT just read and agree.
2. **ASSUMPTION CHECK:** What assumptions are implicit? Flag any that are unsupported
   by evidence in the analysis.
3. **ALTERNATIVE CHECK:** What alternative root causes were NOT considered? Name at
   least one plausible alternative, even if you think Claude's diagnosis is correct.
4. **RISK CHECK:** Could the proposed action cause secondary failures? Check for
   dependencies (e.g., will restarting X affect Y? Does draining node Z displace SeaweedFS pods?).
5. **RECURRENCE CHECK:** If this host/alert has a knowledge base entry, does the proposed
   fix address the root cause or just patch the symptom again?

## Verdict

After verification, reply with ONE of:

- **REVIEW: AGREE** — brief reason why the analysis looks correct after verification
- **REVIEW: DISAGREE** — specific issue found (wrong root cause, unsafe action, missing evidence)
- **REVIEW: AUGMENT** — additional context to add (things Claude missed, alternative causes)

After your verdict line, output a structured JSON block so the gateway can parse it:

```
REVIEW_JSON:{"verdict":"AGREE|DISAGREE|AUGMENT","confidence":0.X,"reason":"one-line reason","issueId":"IFRNLLEI01PRD-XXX","claims_verified":1,"alternatives_considered":1}
```

## Rules
- ALWAYS verify at least one claim via exec before giving your verdict
- If confidence was < 0.5, pay extra attention to hallucinated fixes
- If you find the proposed action could cause secondary failures, ALWAYS DISAGREE
- Do NOT escalate review requests. This is YOUR job as independent critic.

## Dev Task Reviews (CUBEOS/MESHSAT)
For development review requests, adjust the checklist:
1. **CLAIM CHECK:** Verify at least one code claim via codegraph-lookup
2. **TEST CHECK:** Were tests run? Did they pass?
3. **SCOPE CHECK:** Did the changes stay within the issue scope?
4. **RISK CHECK:** Could changes break other modules?
5. **CONVENTION CHECK:** Does the code follow project conventions?
