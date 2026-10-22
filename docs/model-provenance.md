# Model Provenance Chain

Last updated: 2026-06-28

This document tracks the AI models used across the claude-gateway agentic platform, their sources, versions, and trust classification per OWASP LLM03 (Supply Chain) and EU AI Act Art. 15(4).

> **2026-06-28 reorganization (MRs !116–!120):** model selection is now centralized. Claude Code (every `claude` invocation — dispatched remediation, `agent_as_tool`, `mr-review`, `parallel-dev`, interactive) is routed via the **`claude-provider.sh` switch** (`~/.claude/settings.json` env block). The pure-API eval layer (judge / RAGAS / frontier cross-check) routes via the **shared LiteLLM** (`nllitellm01`) for per-component spend tracking. Per the operator directive, the **only paid per-token APIs are Mistral + DeepSeek**; Anthropic is no longer used per-token. See [`config/model-routing.json`](../config/model-routing.json) for the single source of truth and the "Model Orchestration" section in `CLAUDE.md`.

## Active Models

### Claude Code plane (subscription, flat-rate) — switched via `claude-provider.sh`

| Provider | Model(s) | How selected | Use Case |
|----------|----------|--------------|----------|
| **Z.ai (GLM Coding Plan)** — *live default* | `glm-5.2` (Opus-equiv), `glm-4.7` (Sonnet-equiv) | `claude-provider.sh zai` writes `ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic` + `ANTHROPIC_AUTH_TOKEN` + opus→glm-5.2/sonnet·haiku→glm-4.7 into `~/.claude/settings.json` | **All Claude Code:** dispatched remediation (`--model opus`→glm-5.2), `agent_as_tool`, `mr-review`, `parallel-dev`, `audit-owasp`, interactive |
| Anthropic (Max OAuth, $0 marginal) — *revert target* | `claude-opus-4-8` (1M ctx), `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` | `claude-provider.sh anthropic` removes the Z.ai block → `~/.claude/.credentials.json` Max OAuth | Reserved revert / interactive (operator's own sessions benefit from Opus 1M context). Not the live default. |

**Authentication:** Z.ai token in `.env` (`ZAI_API_KEY`, gitignored, injected into settings.json). Anthropic = `~/.claude/.credentials.json` OAuth (`sk-ant-oat-*`, Max subscription, per-host). **Subscription auth cannot proxy through LiteLLM** — that is why Claude Code is routed direct via settings.json, not the API gateway.

### API plane (per-token, paid) — via the shared LiteLLM (`nllitellm01`, `:4000`)

Per the operator directive, the **only paid per-token APIs** in use. Components call LiteLLM's Anthropic-format `/v1/messages` with a per-component `x-litellm-tag` (→ per-component spend) and a gateway-scoped virtual key (`LITELLM_GATEWAY_KEY`). Local Ollama is the fallback (never Anthropic).

| Component | Model (via LiteLLM) | Provider | Fallback |
|-----------|---------------------|----------|----------|
| Frontier cross-check (eval anchor) | `mistral-large-latest` ("Le Chaton Fat") | Mistral | skip if down (anchor must stay non-local) |
| Judge max-effort (flagged sessions) | `mistral-large-latest` | Mistral | local `gemma3:12b` |
| RAGAS evaluation | `deepseek-v4-pro` | DeepSeek | local `gemma3:12b` |
| Judge haiku-backend (`JUDGE_BACKEND=haiku`) | `deepseek-v4-pro` | DeepSeek | local `gemma3:12b` |

**DeepSeek `deepseek-v4-pro` is a reasoning model** → returns `[thinking, text]` content blocks; all parsers join `type=='text'` blocks (the old `content[0].text` grabbed the empty thinking block). Models `deepseek-v4-flash` / `deepseek-v4-pro` available; `mistral-large-latest` is the Mistral flagship.

**Authentication:** `MISTRAL_API_KEY` + `DEEPSEEK_API_KEY` in `.env` (gitignored), provisioned into LiteLLM's postgres by the idempotent [`scripts/litellm-gateway-setup.sh`](../scripts/litellm-gateway-setup.sh). The LiteLLM **master key is fetched transiently over SSH, never stored** gateway-side. LiteLLM version pinned safe (**v1.85.0**, not the 1.82.7/1.82.8 malware releases).

### Tier 1: OpenClaw (Triage Agent) — RETIRED 2026-04-29

OpenClaw was retired (the `cc-cc` migration). The LXC `VMID_REDACTED` (`nl-openclaw01`) has since been **destroyed** ("not found on any node"). All 9 alert receivers now SSH-direct to `scripts/run-triage.sh` invoking Claude Code. The `oc-cc`/`oc-oc`/`cc-oc` operating modes are vestigial; `~/gateway.mode` is stale and slated for removal. See the "Operating Modes" section in `CLAUDE.md`.

### Tier 1 (legacy, retired 2026-04-28)

| Model | Provider | Status |
|-------|----------|--------|
| gpt-5.1 | OpenAI | Retired. `providers.openai` block removed from `openclaw.json`; service-account key flagged for revocation. |
| gpt-4o-mini | OpenAI | Retired (was fallback). |
| gpt-4o | OpenAI | Retired (was prior primary, migrated 2026-04-07 → GPT-5.1). |

### Local Models (Ollama)

_Corrected 2026-06-16 (IFRNLLEI01PRD-1097) to match the live env defaults; drift is now caught by `scripts/check-model-provenance-drift.py`._

| Model | Host | Port | Dimensions | Use Case (live env default) |
|-------|------|------|-----------|----------|
| nomic-embed-text | nl-gpu01 | 11434 | 768 | RAG embeddings (`EMBED_MODEL`) — incident_knowledge, wiki_articles, session_transcripts, agent_diary |
| gemma3:12b | nl-gpu01 | 11434 | -- | LLM-as-judge primary (`JUDGE_LOCAL_MODEL`) — session_judgment, RAGAS |
| qwen2.5:7b | nl-gpu01 | 11434 | -- | Query rewrite / RAG-Fusion / HyDE (`REWRITE_MODEL`), multi-chunk synthesis (`SYNTH_LOCAL_MODEL`), judge fallback (`JUDGE_LOCAL_FALLBACK`) |
| BAAI/bge-reranker-v2-m3 | nl-gpu01 | 11436 | -- | Cross-encoder rerank (`RERANK_BACKEND=crossencoder`); Ollama yes/no rerank fallback uses qwen2.5:7b |
| qwen3:4b / qwen3:30b-a3b / devstral-small-2 | nl-gpu01 | 11434 | -- | Pulled + available but NOT a current active default (kept for experiments/fallback) |

**Authentication:** None (local network only, 10.0.181.X/24)
**Provenance:** Models pulled from ollama.com registry; SHA-256 hashes verified by Ollama on download
**Data handling:** All inference local; no data leaves the network

## Model Hash Verification

To verify Ollama model integrity:

```bash
ssh nl-gpu01 "ollama show nomic-embed-text --modelfile" | grep -E '^FROM|^PARAMETER'
ssh nl-gpu01 "ollama list" | grep -E 'nomic-embed|qwen3|devstral'
```

Anthropic and OpenAI models are API-served; integrity is guaranteed by the provider's API TLS certificate chain.

## Trust Classification

| Model Source | Trust Level | Verification Method |
|-------------|-------------|-------------------|
| Z.ai (GLM) | Medium-High | TLS cert chain, bearer-token auth; Anthropic-compatible endpoint. Subscription + API. |
| Mistral API | High | TLS cert chain, API key auth, EU-hosted, commercial terms |
| DeepSeek API | Medium-High | TLS cert chain, API key auth, commercial terms. Reasoning model (v4-pro). |
| Anthropic (Max OAuth) | High | TLS cert chain, OAuth token auth, commercial terms. Revert target only (not the live default). |
| OpenAI API | Retired | Decommissioned 2026-04-28 (IFRNLLEI01PRD-746). |
| Ollama (local) | Medium | SHA-256 on download, but no ongoing integrity monitoring |
| Custom fine-tunes | N/A | No fine-tuned models in use |

## Supply Chain Risks

| Risk | Mitigation | Status |
|------|-----------|--------|
| Model poisoning (OWASP LLM04) | API-served models: provider responsibility. Local models: SHA-256 at download | Mitigated |
| Model version drift | Pinned model IDs where dated (`claude-haiku-4-5-20251001`, `deepseek-v4-pro`, `mistral-large-latest`); `latest` aliases accepted for the subscription plane (GLM Coding Plan serves current) | Mitigated |
| Credential compromise | Provider keys (`ZAI_API_KEY`, `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`) in gitignored `.env`; LiteLLM master key fetched transiently over SSH, never stored gateway-side; LiteLLM scoped virtual key (`LITELLM_GATEWAY_KEY`) limits blast radius. Anthropic OAuth (`sk-ant-oat-*`) auto-refreshes per host. OPENAI keys revoked 2026-04-28. | Tracked |
| LiteLLM supply-chain malware | Shared LiteLLM pinned to **v1.85.0** (PyPI `1.82.7`/`1.82.8` shipped credential-stealing malware — neither is in use) | Mitigated |
| Data leakage via API | Commercial API terms (Mistral/DeepSeek/Z.ai) govern data; local models have no external connectivity | Mitigated |
| Adapter/plugin poisoning | No adapters or fine-tunes in use; OpenClaw retired | N/A |

## ADR: No fine-tuning (IFRNLLEI01PRD-1097, 2026-06-16)

**Decision:** this platform does not train, fine-tune (LoRA/QLoRA/full), preference-align (DPO/RLHF), or quantize any model. It consumes off-the-shelf Claude (API + OpenClaw OAuth-Max) and pre-quantized local Ollama models.

**Rationale (against the LLM Engineer's Handbook fine-tuning gate, Ch 5):** the book itself says to start with prompt-engineering + RAG and fine-tune *only if* an eval harness proves they're insufficient AND enough data exists. Here the base agent model is **closed-weight (Claude)**, so LoRA/QLoRA/full-FT/DPO are structurally unavailable on it; the local Ollama models are used as-is. The system's behavioral-adaptation substitute is **prompt-policy iteration** (the prompt-patch A/B trials + risk-approval feedback loop), not weight updates. RAG (5-signal RRF + cross-encoder rerank) covers new/private knowledge. This is the book's recommended order, with fine-tuning correctly skipped — see [`book-applicability-map.md`](book-applicability-map.md) for which handbook chapters are N/A-by-design.

**Drift control:** `scripts/check-model-provenance-drift.py` fails if the local-model table above diverges from the live env defaults (judge/synth/rewrite/embed/rerank), so this doc can't silently go stale again. The provider/model selection for the subscription and API planes is governed by [`config/model-routing.json`](../config/model-routing.json) (resolved by [`scripts/lib/model_routing.py`](../scripts/lib/model_routing.py) `--list`/`--resolve`) and the live `claude-provider.sh status`; treat those as authoritative for "which model on which component".

## Review Schedule

Model provenance reviewed quarterly alongside the industry benchmark assessment.
Next review: 2026-07-15
