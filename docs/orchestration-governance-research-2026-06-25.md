# Orchestration & Governance Control-Plane — OSS Research (2026-06-25)

> Research run via claude.ai (web search) from the prompt in `docs/runbooks/` / `/tmp/orchestration-governance-research-prompt.md`. Feeds epic **IFRNLLEI01PRD-1421**. Decisive answer: **compose Healthchecks.io + Langfuse, BUILD the 3 thin bricks; do NOT adopt a platform.**


## TL;DR
- **The need is real and recognized**, but the answer for a single operator is **compose-and-build, not adopt-a-platform**: wrap your existing Prometheus substrate with **Healthchecks.io** (component liveness registry, brick #1) and add **Langfuse** for LLM/agent trace visibility (brick #2/#3), then **build the registry manifest, interaction graph, and orchestration benchmark yourself** as a few hundred lines on top of SQLite + Prometheus. This is option (b)+(c), decisively — not (a).
- **Skip the agent-building frameworks entirely** (LangGraph, CrewAI, AutoGen, Semantic Kernel, OpenAI Agents SDK, Google ADK, Microsoft Agent Framework, Mastra): your system already exists, so adopting them is a rewrite, not an incorporation. **Skip the heavy orchestrators as platforms** (Temporal, Airflow, Dagster, Prefect) — re-platforming 100 crons + 27 n8n flows onto a DAG engine is exactly the rewrite you're trying to avoid — though **Dagster's external-asset + freshness-check model is the single best design template to copy in-house**.
- **Your three bricks are genuinely thin on the substrate you already run.** A declared YAML manifest + a `node_exporter` textfile-collector liveness check + a SQLite-introspection script that diffs declared-vs-observed reads/writes/cron-slots is the highest-leverage, lowest-lock-in path. The OSS catalog/policy/chaos heavyweights (Backstage, OPA, Chaos Mesh, LitmusChaos) are all built for Kubernetes fleets and large teams and are over-engineered for one person.

## Key Findings

### 1. The need is real and recognized — governing a federation is a named discipline
The problem you hit — components "silently dark" because nothing governs the whole — is the textbook failure mode that the SRE and emerging AgentOps literature now explicitly names.

- **AgentOps as a discipline.** The CSIRO/Data61 paper *"AgentOps: Enabling Observability of LLM Agents"* (Dong, Lu, Zhu; arXiv:2411.05285, Nov 2024) argues that agent autonomy makes observability a safety requirement: *"enabling observability in agents is necessary to ensuring AI safety, as stakeholders can gain insights into the agents' inner workings, allowing them to proactively understand the agents, detect anomalies, and prevent potential failures."* It proposes "a comprehensive taxonomy of AgentOps, identifying the artifacts and associated data that should be traced throughout the entire lifecycle of agents" — exactly your registry + interaction-graph need.
- **OpenTelemetry GenAI SIG** (Guangya Liu/IBM, Sujay Solomon/Google, Mar 2025) frames fleet-scale agents as needing dedicated observability: *"with this evolution comes the critical need for AI agent observability, especially when scaling these agents to meet enterprise needs. Without proper monitoring, tracing, and logging mechanisms, diagnosing issues, improving efficiency, and ensuring reliability in AI agent-driven applications will be challenging."*
- **Gartner** reports a 1,445% surge in multi-agent-system inquiries (Q1 2024 → Q2 2025) and advises teams to *"adopt frameworks for governance, observability and compliance from the start."* (Gartner also *predicts* — future tense — that 40% of enterprise applications will embed AI agents by the end of 2026, up from less than 5% in 2025; treat as a forecast, not a measured fact.)
- **Control plane vs. data plane** is the canonical pattern your three bricks instantiate: the control plane declares intent and enforces policy ("write once, enforce everywhere"); the data plane (your crons/n8n/Claude Code) executes. The defining property is that catalogs/policy live *out of band* from execution — which is precisely why your holistic health-check being unscheduled went unnoticed.
- **The meta-monitoring / dead-man's-switch pattern** is the SRE canon answer to "who watches the watcher": Google's SRE book defines the four golden signals and treats silent failures (HTTP 200 but wrong/no content) as a first-class hazard; Grafana, HelloFresh, and the Prometheus `Watchdog`/Dead Man's Snitch pattern all implement an always-firing alert routed to an *external* system that pages when the heartbeat stops. Your missing "holistic health-check that was itself never scheduled" is the exact gap this pattern closes.

**When is it worth it vs. over-engineering?** The YAGNI lens matters here: for a single operator you should *not* "stand up a Kafka + a Kubernetes operator + a Temporal cluster." But governance here is not speculative future-proofing — you have *evidence* (an audit found weeks-to-months of dark components). That is the "evidence before elegance" threshold that justifies building the control plane now. The discipline is to build the *thin* version.

### 2. Established patterns and their canonical references
| Pattern | What it is | Canonical reference(s) |
|---|---|---|
| Control plane / data plane | Separate intent+policy from execution | Kubernetes, Istio; widely applied to agent "control planes" |
| Software/service catalog | Registry of every component + owner + metadata | Backstage Software Catalog ("No more orphan software hiding in the dark corners") |
| Capability/tool & agent registry + discovery | Machine-readable descriptors others query | MCP registry; A2A "Agent Cards" + registry |
| Policy-as-code engine | Externalized allow/deny decisions | Open Policy Agent (Rego), Cerbos (YAML) |
| Orchestration DAG + liveness/freshness | Declared dependencies + "is this asset stale?" | Dagster assets + Freshness Policies / Asset Checks |
| Heartbeat / dead-man's switch | Alert when an expected signal stops | Prometheus Watchdog; Healthchecks.io; Dead Man's Snitch |
| Distributed tracing for agents | Spans for LLM calls, tool calls, agent steps | OpenTelemetry GenAI semantic conventions; OpenInference |
| Chaos / steady-state hypothesis | Inject failure, verify graceful degradation | Chaos Toolkit (steady-state hypothesis), Chaos Mesh, LitmusChaos |

### 3. The candidate landscape — ranked

The decisive filter: **can it WRAP an existing cron + n8n + SQLite + Prometheus + Claude-Code federation without a rewrite?** Tools that require you to re-author your workflows as their primitives fail this test for a solo operator, regardless of quality.

#### RANKED COMPARISON TABLE

| Rank | Candidate | Brick(s) | Maturity / adoption | License | Wraps without rewrite? | Integration effort on this stack | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | **Build in-house** (YAML manifest + textfile-collector liveness + SQLite-introspection interaction graph + replay benchmark) | #1, #2, #3 | N/A (your code) | N/A | Yes — it *is* the existing substrate | Low–Med | **BUILD** |
| 2 | **Healthchecks.io** | #1 (liveness/cadence/kill-switch detection) | ~9,958★, mature, run solo by its own author | BSD-3 | Yes — crons/n8n ping a URL; no workflow changes | Low | **ADOPT** |
| 3 | **Langfuse** | #2/#3 (LLM session tracing, agent graphs, eval scoring) | ~22,000★, large OSS category leader | MIT (core; EE folder commercial) | Yes — OTel-native; Claude Code + n8n integrations exist | Low–Med | **ADOPT** |
| 4 | **OpenTelemetry GenAI + OpenInference** | #2/#3 (vendor-neutral instrumentation) | Standard, CNCF-backed; Claude Code exports OTel | Apache-2.0 | Yes — instrument, don't rewrite | Med | **ADAPT** (as the wire format feeding #3) |
| 5 | **Dagster** | #1/#3 (asset graph, freshness checks, external assets) | ~15,746★, Apache-2.0, very active | Apache-2.0 | Partially — external assets observe without rewrite, but value comes from migrating scheduling | Med–High | **ADAPT** (copy the model; optionally wrap later) |
| 6 | **Prometheus textfile collector / Alertmanager Watchdog** | #1/#3 (you already run this) | De-facto standard | Apache-2.0 | Yes — already the substrate | Low | **ADOPT** (extend what exists) |
| 7 | **Chaos Toolkit** | #3 (steady-state hypothesis, CLI, pip-installable) | Moderate; framework-style | Apache-2.0 | Yes — define experiments as JSON/YAML, no K8s required | Med | **ADAPT** |
| 8 | **Open Policy Agent** | policy engine | ~11,884★, CNCF graduated | Apache-2.0 | Yes (sidecar) but Rego learning curve; overkill for 1 person | Med | **SKIP (for now)** |
| 9 | **Cerbos** | policy engine | ~4,448★ | Apache-2.0 (Hub commercial) | Yes; YAML policies, lighter than OPA | Med | **SKIP (for now)** |
| 10 | **Backstage** | #1 (catalog) | ~33,690★, CNCF | Apache-2.0 | Catalog YAML can describe components, but… | High (needs 3–12 eng, 6–12 mo to productionize) | **SKIP** |
| 11 | **Port / Roadie / OpsLevel / Clutch** | #1 (catalog) | Commercial / managed-Backstage | Mixed / SaaS | Yes but cloud-SaaS lock-in | Low–Med | **SKIP** (violates no-SaaS constraint) |
| 12 | **Temporal / Airflow / Prefect / Kestra / Windmill** | orchestrator | Mature (Prefect ~22.5k★, Kestra ~18k★, Windmill ~16.8k★) | Apache-2.0 (Windmill AGPLv3 core) | No — value requires re-authoring workflows as their primitives | High | **SKIP** (rewrite) |
| 13 | **Arize Phoenix / AgentOps / Helicone** | #2/#3 (LLM observability) | Phoenix strong, OTel-native | Phoenix ELv2; others mixed | Yes (OTel) | Med | **SKIP** (Langfuse covers this; ELv2 less permissive) |
| 14 | **Chaos Mesh / LitmusChaos** | #3 | CNCF sandbox/incubating | Apache-2.0 | No — Kubernetes-native (CRDs, operators) | High | **SKIP** (you have no K8s) |
| 15 | **LangGraph / CrewAI / AutoGen / Semantic Kernel / OpenAI Agents SDK / Google ADK / MS Agent Framework / Mastra** | agent-building | Various | Various | No — these BUILD agents; adoption = rewrite | Very High | **SKIP** (wrong category) |
| 16 | **MCP Registry / A2A / LF Agent Name Service** | #2 (agent discovery) | Emerging; AANS already judged too immature by this team | Open | Partially | Med | **SKIP (watch)** |

### 4. Why the agent-building frameworks are the wrong category
LangGraph, CrewAI, AutoGen, Semantic Kernel, the OpenAI Agents SDK/Swarm, Google's ADK, Microsoft Agent Framework, and Mastra are all **frameworks for *building* agent applications**. The OpenTelemetry team draws the exact distinction you need: *"AI agent application refer to individual AI-driven entities… AI agent framework provide the necessary infrastructure to develop, manage, and deploy AI agents."* Your federation already exists and already works. Adopting any of these means re-expressing your alert-triage→LLM→risk→gate→execute→reconcile pipeline in their abstractions — a rewrite of the data plane, which is explicitly what you do not want. They solve a problem you already solved. **SKIP all of them.**

## Details

### Brick #1 — Component registry: ADOPT Healthchecks.io + BUILD the manifest
The registry has two halves: (a) a **declared manifest** of what *should* run, and (b) a **mechanism that proves liveness** and fires when a component goes dark.

- **Build the manifest** as a version-controlled YAML/SQLite table: one record per component with `{trigger, cadence, liveness_metric, tables_written, kill_switch}`. This is the single source of truth your audit lacked. A few hundred lines; it is the "uninstall plan / system of record" the YAGNI playbook recommends.
- **Adopt Healthchecks.io for liveness.** It is BSD-3 licensed, self-hostable on SQLite/Postgres, written in Python/Django, and is *purpose-built for exactly this*: *"A failed cron job often has no immediate visible consequences and can go unnoticed for a long time."* Each cron/n8n workflow pings a unique URL on success; if a ping doesn't arrive within Period+Grace, it alerts. Critically, it catches the **scheduling failure** (job never ran) that Prometheus `absent()` rules miss and that caused your dark components. The strongest proof it's operable solo: Healthchecks.io is itself a one-person business — per founder Pēteris Caune's July 2024 post "Running One-man SaaS, 9 Years In," *"Yes, Healthchecks.io is still a one-man business,"* then serving 652 paying customers at ~$14k MRR. One developer in Latvia runs the whole product *and* its monitoring.
- **Why not Backstage here?** Backstage *is* the canonical software catalog ("No more orphan software hiding in the dark corners of your software ecosystem"), but per Roadie's State of Backstage research it *"requires a dedicated team of 3-12 engineers and a 6-12 month investment to become production-ready,"* releases monthly, and (per r/DevOps practitioners) "is not an 'other duties as assigned' sort of tool to own." For one operator that is wildly over-engineered. **SKIP.**

### Brick #2 — Interaction graph: BUILD on SQLite introspection, feed visibility from Langfuse/OTel
This is the brick **no OSS product gives you off the shelf**, because the overlaps/gaps you care about are *specific to your substrate*: who reads/writes which SQLite table, who holds which lock, who occupies which cron time-slot, who emits which metric, who fires which hook.

- **Build it** as an introspection job: parse the manifest's declared `tables_written`/`tables_read`, and reconcile against *observed* reality — SQLite has full schema introspection, and you can diff declared-vs-observed writes (e.g., last-write timestamps per table) to surface the exact failure that took 4 analytics tables dark: a **handoff that neither side owns**. Render as a graph (component → {tables, locks, cron-slots, metrics, hooks}); overlaps = two writers of one table (conflict) or two identical readers (redundancy); gaps = a declared consumer with no producer.
- **The design template to copy is Dagster's**, not to adopt: Dagster's *asset graph* tracks *data dependencies* ("data asset Y is derived from data asset X"), distinct from execution DAGs, and its **external assets** let you "use Dagster for lineage, observability, data quality, alerting… without migrating scheduling and orchestration infrastructure." That is conceptually your interaction graph. You *could* wrap your federation as Dagster external assets later; for now, copying the model in ~hundreds of lines avoids the Med–High effort of running the Dagster daemon + webserver.
- **Layer Langfuse for the LLM half.** The interaction graph's *agent* edges (which Claude Code session fired, what tools it called, what it changed) are exactly what Langfuse captures: hierarchical traces of "every LLM call, tool invocation, and retrieval step," agent-graph visualization, sessions, and it has **first-party Claude Code and n8n integrations** and is OTel-native. Self-host via Docker; MIT-licensed core.

### Brick #3 — Orchestration benchmark + chaos: BUILD the replay harness, copy freshness checks, optionally use Chaos Toolkit
- **Score the whole** by building a **replay harness**: feed a stream of historical (or synthetic) incidents and assert, per incident, that the right components fired in the right order, with the correct end-state, no conflict, no gap. This is an application-specific evaluation — no OSS scores *your* pipeline's correctness. Langfuse's datasets/experiments + LLM-as-judge can score the *LLM* steps; the *orchestration* assertions are yours to write.
- **For "inject a component going dark and verify detection,"** you can do this with almost no new tooling: disable a cron / pause an n8n workflow and confirm brick #1 (Healthchecks.io + the manifest diff) detects it and the system degrades gracefully. If you want a formal harness, **Chaos Toolkit** (Apache-2.0, `pip install`, no Kubernetes) is the right fit because it codifies a **steady-state hypothesis** then perturbs it — and unlike **Chaos Mesh/LitmusChaos**, it does not require a Kubernetes cluster (which you don't have). ADAPT Chaos Toolkit; SKIP the K8s-native chaos tools.
- **Copy Dagster's freshness-check semantics** for the "is this asset overdue?" logic: a freshness policy that fails if an asset isn't materialized within a window is directly portable to "this analytics table should be written every hour; alert if not." You already have the timestamps in SQLite and the alerting path in Prometheus/Alertmanager.

### The build-it-yourself case, concretely
Each brick is small *because you already run the substrate*:
- **Liveness/metrics:** the Prometheus `node_exporter` **textfile collector** is designed for exactly "monitoring cronjobs… anything involving subprocesses": a job writes `*.prom` files (atomically) that get scraped. You already emit Prometheus textfile metrics — brick #1's liveness signal is an extension of what exists, plus an Alertmanager `Watchdog`-style always-firing rule routed to an external dead-man's switch.
- **Registry/graph storage:** one more SQLite DB (or tables) — your existing shared substrate.
- **The hard, valuable, un-buyable part** (the interaction graph's overlap/gap detection and the orchestration replay benchmark) is *inherently bespoke*. No catalog/orchestrator/observability product models "component → SQLite tables/locks/cron-slots" or scores your specific incident pipeline. Building it is not reinventing a wheel; it's the part with no wheel to buy.

### Licensing & lock-in notes
All recommended tools are permissive/self-hostable: Healthchecks.io (BSD-3), Langfuse (MIT core), Prometheus/OTel/OpenInference (Apache-2.0), Chaos Toolkit (Apache-2.0), Dagster (Apache-2.0). Watch Langfuse's `ee/` folder (commercial) and Windmill's AGPLv3 core if you ever reconsider it. Avoid the managed catalogs (Port/Roadie/OpsLevel) — they reintroduce the cloud-SaaS lock-in you're explicitly avoiding.

## Recommendations

**Decisive answer: option (b) compose two focused tools + option (c) build the three thin bricks — NOT (a) adopt one platform.** No single OSS platform fits a single-operator cron-federation cleanly; the catalog/orchestrator heavyweights are built for teams and Kubernetes, and the agent frameworks would force a rewrite. Compose Healthchecks.io (liveness) + Langfuse (LLM visibility) and build the manifest, interaction graph, and benchmark yourself on Prometheus + SQLite.

**Staged next steps:**

1. **Week 1 — Stop the bleeding (brick #1 minimum viable).** Write the YAML manifest of all ~100 crons + 27 n8n flows + subsystems with `{trigger, cadence, liveness_metric, table_written, kill_switch}`. Self-host Healthchecks.io (Docker) and add a success-ping to every cron and n8n workflow. Add one Alertmanager always-firing `Watchdog` routed to an *external* dead-man's switch so the monitor-of-monitors can never again be silently unscheduled. **Benchmark to advance:** every declared component pings or alerts within one cadence cycle.

2. **Weeks 2–4 — Interaction graph + LLM visibility (brick #2).** Build the SQLite-introspection diff: declared-vs-observed table writes (last-write timestamp per table), cron-slot collisions, metric ownership. Emit the graph as a `*.prom` textfile + a simple queryable view. Stand up self-hosted Langfuse and route Claude Code sessions (OTel) + n8n LLM steps into it. **Benchmark to advance:** the graph mechanically flags any table with a declared consumer but no recent producer (the "dark analytics table" failure) and any double-writer.

3. **Weeks 5–8 — Orchestration benchmark + chaos (brick #3).** Build the incident-replay harness asserting correct component firing order and end-state per incident. Add Dagster-style freshness checks for every data-producing component. Introduce Chaos Toolkit experiments that disable a component and assert brick #1 detects it and the pipeline degrades gracefully. **Benchmark to advance:** a deliberately darkened component is detected automatically within its cadence + grace window, and the replay harness produces a pass/fail score for a batch of incidents.

**Thresholds that would change this recommendation:**
- If you add **a second operator / small team**, re-evaluate Backstage (catalog) and a real orchestrator — the team-scale overhead becomes justified.
- If you migrate onto **Kubernetes**, Chaos Mesh/LitmusChaos and OPA-as-admission become reasonable.
- If the federation grows past roughly **a few hundred components or multiple machines**, wrapping execution in Dagster (external assets first, then scheduling) or Temporal becomes worth the migration cost.
- If you need **policy enforcement on agent actions** (who/what an LLM session may touch), add Cerbos (lighter than OPA) before OPA.

## Caveats
- **Adoption numbers are point-in-time** (mid-2026) GitHub stars from org-listing pages and self-reported figures; they fluctuate and Kestra's exact count could not be confirmed from GitHub's own counter (third-party "over 18k").
- **OpenTelemetry GenAI semantic conventions are still in "Development"/experimental status** (v1.36 transition baseline; agent-span and MCP conventions are new and "moving fast"). Build the instrumentation behind a thin adapter so attribute renames don't ripple.
- **"Build it yourself" has a real maintenance tail** — the YAGNI literature's warning about "debugging the void" applies. Keep each brick small and delete-able; the goal is governance, not a second platform to govern.
- **Langfuse and Cerbos are open-core**; core features are MIT/Apache but some enterprise capabilities are gated. Verify the specific features you need are in the OSS tier.
- The recommendation assumes the system genuinely **stays single-operator and self-hosted**; every "threshold" above is a real trigger to revisit.