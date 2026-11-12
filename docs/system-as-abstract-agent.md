# The system as an abstract agent

**Date:** 2026-04-20
**Scope:** Architectural overview of the claude-gateway platform at two
levels of abstraction, independent of any specific vendor or protocol.

The purpose of this document is to make the system analysable even when
the reader has no context on LibreNMS, YouTrack, Matrix, Ansible, or any
other concrete integration. The invariants captured here are the
non-negotiable properties of the system; the concrete implementations are
swappable.

---

## Level 1 — The system is a black box; inputs and outputs are concrete

At this level we hide the internals (n8n, OpenClaw, Claude Code, RAG,
SQLite, prompts, sub-agents) and enumerate what crosses the system
boundary.

### Inputs

Grouped by whether they **trigger** work or just **inform** it.

| Class | Origin |
|---|---|
| **Triggers (active work)** | Monitoring systems — availability/resource/metric alerts (LibreNMS, Prometheus, Synology DSM) |
| | Security systems — intrusion detectors, vulnerability scanners (CrowdSec, nuclei/nmap/testssl) |
| | CI/CD — pipeline failures (GitLab CI) |
| | Work-management — issue state transitions (YouTrack) |
| | Operators — chat commands, poll votes, reactions (Matrix) |
| | Operators — interactive shell sessions (`claude` CLI) |
| | Schedule — chaos exercises, health checks, evals, backfills, trial finalization (cron) |
| **Ambient (read-only context)** | CMDB — devices, IPs, VLANs (NetBox) |
| | Live device state — SSH, kubectl, hypervisor APIs (authoritative source of truth) |
| | Version control — IaC repos, CLAUDE.md, memory, wiki sources |
| | Internal RAG tables — transcripts, knowledge, lessons, diary, events |
| | External LLM providers — Anthropic, OpenAI, local Ollama |

### Outputs

Grouped by **reach** — which ones cross the human-in-the-loop (HITL) boundary.

| Class | Effect |
|---|---|
| **Autonomous (no approval)** | Non-destructive communications (chat messages, issue comments, low-risk auto-resolves) |
| | Observability (Prometheus metrics, OTel spans, Grafana dashboards) |
| | Knowledge writes (own SQLite tables — 39 of them) |
| | Log archives (syslog-ng, session archive tarballs) |
| | Self-modifying RAG surface (wiki recompilation, prompt-patch promotion, incident-knowledge rows) |
| **Human-in-the-loop (approval required)** | Infrastructure commands (SSH, kubectl, hypervisor ops, firewall config) |
| | Runbook executions (Ansible playbook launches) |
| | Code changes to IaC repos (commits / MRs) |
| | Workflow state transitions that change business meaning (ticket resolution, deployment gate) |

### One-sentence summary

**In:** triggers (automated + operator) + ambient context (CMDB / live
device / RAG / LLM).
**Out:** observability, knowledge accumulation, non-destructive
communication — and, *only after explicit human approval*,
infrastructure actions.

---

## Level 2 — Inputs and outputs are also black boxes; the system becomes a pure signature

At this level we stop naming the protocols and vendors. The system
reduces to a **deliberative agent with a human-supervised effect channel
and a self-modifying policy**.

### Pure signature

```
system : (Signal, Context) × (Memory, Policy) → (Action, Memory', Policy', Communication)
```

| Symbol | Meaning |
|---|---|
| `Signal` | An event that passed an attention filter. Anything claiming "this matters now." |
| `Context` | Queryable world state at the moment of the signal. Read-mostly. |
| `Memory` | Accumulated past — episodic (what happened), semantic (what's true), procedural (what to do). Read on every turn, write-mostly. |
| `Policy` | The current decision-making rules: prompts, guardrails, routing logic, thresholds. Slow-moving but mutable. |
| `Action` | An effect on the external world. May be empty. **Gated**. |
| `Memory'` | Updated accumulated past. Always at least Memory. Never shrinks. |
| `Policy'` | Updated rules. Occasionally modified — only when an external evaluator says so. |
| `Communication` | Everything an external human or adjacent system reads that is not itself an infrastructure-mutating `Action`. |

### Four equivalent lenses

Each lens is a different way to read the same signature. No one is
canonical; they illuminate different properties.

| Lens | Reading |
|---|---|
| **Control theory** | A feedback controller. Plant = infrastructure; sensors = signals; actuators = gated actions; reference = "healthy"; error signal = alerts; controller = the cascaded reasoning loop. Stability of the closed loop is a system property the designer can reason about. |
| **Reinforcement learning** | A partially-observable MDP. State = `Context × Memory`; reward = judge scores + incident outcomes; value function = the learned prompt policy; exploration gated by the eval flywheel + A/B trials. Bandit-style per-dimension optimization rather than monolithic RL. |
| **Three-stage filter** | Each signal passes through filters of increasing cost and capability: deterministic pattern match → LLM reasoning → human judgment. Each stage can short-circuit success or escalate. The cost-capability curve is the design lever. |
| **Classical agent** | Perceive → Reason → Act → Observe → Update. Three nested loops at different timescales: within-session (ReAct, seconds), across-session (memory accumulation, hours), across-month (policy evolution via prompt trials, weeks). Each loop reduces entropy at its own scale. |

### Technology-agnostic invariants

These must hold regardless of what concrete technology is plugged into
the I/O boxes. Any implementation that does not preserve these is a
different system.

1. **Actions that mutate external state pass through a human gate unless pre-classified safe.**
   The one property that separates this system from an autonomous agent.
   "Pre-classified safe" is itself a narrow, auditable channel.

2. **Memory never shrinks.**
   Every turn, every session, every judgment accretes. Policy changes
   must remain auditable back to a specific observation. Pruning is
   retention-based, never re-writing history.

3. **Policy change is externally judged.**
   The system cannot unilaterally decide its own rules have improved —
   the eval loop (judge + eval flywheel) + A/B trials (prompt-patch
   trials) supply ground-truth evaluation from outside the generator.
   No self-grading.

4. **Confidence is a first-class scalar.**
   Low confidence is a terminating signal, not an edge case. Every
   major decision surface outputs a number that can force `[POLL]`
   or halt.

5. **Every decision is three-tier.**
   Fast-cheap → deliberative → human. Each tier has right-of-refusal.
   A tier can decline to handle a case and escalate, but cannot
   unilaterally decide to stay silent.

### The isomorphism

At this abstraction level the system is **isomorphic to a competent
on-call rotation** — L1 → L2 → SRE. Same topology, same invariants,
same failure modes:

| Concrete L1/L2/SRE rotation | Abstract agent system |
|---|---|
| L1 takes the page, pattern-matches against runbooks | Tier 1 runs deterministic skills + fast LLM triage |
| If not in runbook, L1 pages L2 | Low-confidence or complex → Tier 2 deeper reasoning |
| L2 can execute changes only after approval | Tier 2 proposes via `[POLL]`, waits for human |
| L2 escalates to on-call SRE for high-risk | `[POLL]` surfaces to operator via chat |
| Retrospective after incident feeds runbooks | Session ends → `incident_knowledge`, `lessons_learned`, wiki recompilation |
| Team improves its runbook phrasing based on what works | Prompt-patch trials promote better instructions |
| On-call engineer is ultimate arbiter | Human approval is terminal gate |

The system does not replace the rotation — it realizes it in software
with a machine-readable memory and an optimizer wrapped around the
policy.

---

## What this abstraction supports

Use the Level 2 framing for:

- **Safety-invariant auditing.** If you can show any of the five
  invariants violated under a new feature, the feature changes the
  contract and must be re-evaluated.
- **Topology comparisons.** Is OpenAI Agents SDK the same shape? Yes —
  their `RunState` is our memory, their typed events are our `event_log`,
  their per-tool guardrails are our hooks. That's why the SDK audit
  surfaced concrete gaps but no structural mismatch.
- **Team-structure translation.** Operators ramping up on the system
  can read it as an L1/L2/SRE rotation, which they already know.
- **Substitution reasoning.** What if we replaced Matrix with Slack?
  The answer is "nothing changes at Level 2" — Matrix is just the
  `Communication` transport for that class.

## What this abstraction does not support

The Level 2 framing deliberately elides detail. Do not use it for:

- **Debugging specific incidents.** You need Level 0 (live device / logs).
- **Performance tuning.** Throughput, latency, and cost live at the
  concrete layer — RAG retrieval p95, Ollama batch size, SQLite WAL
  contention, etc.
- **Vendor / protocol evaluation.** Whether GitLab or GitHub, whether
  Claude or GPT — those are decisions at Level 1 and below.
- **Ops cost modelling.** Cost lives in the concrete LLM/hardware choices.

## Related

- [`README.md`](../README.md) — concise overview at Level 1.
- [`README.extensive.md`](../README.extensive.md) — full technical reference at Level 0 (implementation detail).
- [`docs/agentic-patterns-audit.md`](agentic-patterns-audit.md) — pattern-by-pattern scorecard (21 patterns, Level 1).
- [`docs/runbooks/`](runbooks/) — per-feature operator docs at Level 0.
- `.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory/openai_sdk_adoption_batch.md` —
  memory on the 2026-04-20 audit that used exactly this abstraction to
  map our system against the OpenAI Agents SDK.

---

*This document is an architectural snapshot, not a living spec. The pure
signature and the five invariants are the enduring part. The concrete
enumerations in Level 1 will drift as integrations change.*
