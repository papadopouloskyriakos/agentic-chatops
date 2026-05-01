# Model Provenance Chain

Last updated: 2026-04-28

This document tracks the AI models used across the claude-gateway agentic platform, their sources, versions, and trust classification per OWASP LLM03 (Supply Chain) and EU AI Act Art. 15(4).

## Active Models

### Tier 2: Claude Code (Primary Agent)

| Model | Provider | API | Version | Use Case |
|-------|----------|-----|---------|----------|
| claude-opus-4-6 | Anthropic | api.anthropic.com/v1/messages | Opus 4.6 (1M context) | Complex infrastructure tasks, flagged session judgment |
| claude-sonnet-4-6 | Anthropic | api.anthropic.com/v1/messages | Sonnet 4.6 | Routine tasks (via modelHint complexity classifier) |
| claude-haiku-4-5-20251001 | Anthropic | api.anthropic.com/v1/messages | Haiku 4.5 | Sub-agent inference, routine LLM-as-Judge, RAGAS evaluation |

**Authentication:** ANTHROPIC_API_KEY in .env (API key, not embedded in prompts)
**Subscription:** Claude Max (Tier 2 cost = $0 for interactive sessions)
**Data handling:** No training on user data per Anthropic's commercial terms

### Tier 1: OpenClaw (Triage Agent)

| Model | Provider | API | Version | Use Case |
|-------|----------|-----|---------|----------|
| claude-sonnet-4-6 | Anthropic (OAuth Max) | OpenClaw `claude-cli` provider → spawned `claude` CLI subprocess → api.anthropic.com/v1/messages | Sonnet 4.6 | Primary triage and investigation (migrated from GPT-5.1 2026-04-28, IFRNLLEI01PRD-746) |
| claude-opus-4-6 | Anthropic (OAuth Max) | same | Opus 4.6 | First fallback (high-value triage) |
| claude-opus-4-5 | Anthropic (OAuth Max) | same | Opus 4.5 | Second fallback |
| claude-sonnet-4-5 | Anthropic (OAuth Max) | same | Sonnet 4.5 | Third fallback |
| claude-haiku-4-5 | Anthropic (OAuth Max) | same | Haiku 4.5 | Fourth fallback (cost-optimized via Max sub) |

**Authentication:** `~/.claude/.credentials.json` (`sk-ant-oat-*` OAuth token, Max subscription, separate per host). Auto-refreshed by `claude` CLI.
**Cost:** $0 marginal (Max subscription).
**Data handling:** API usage, not training per Anthropic commercial terms.

### Tier 1 (legacy, retired 2026-04-28)

| Model | Provider | Status |
|-------|----------|--------|
| gpt-5.1 | OpenAI | Retired. `providers.openai` block removed from `openclaw.json`; service-account key flagged for revocation. |
| gpt-4o-mini | OpenAI | Retired (was fallback). |
| gpt-4o | OpenAI | Retired (was prior primary, migrated 2026-04-07 → GPT-5.1). |

### Local Models (Ollama)

| Model | Host | Port | Dimensions | Use Case |
|-------|------|------|-----------|----------|
| nomic-embed-text | nl-gpu01 | 11434 | 768 | Embedding generation for RAG (incident_knowledge, wiki_articles, session_transcripts) |
| qwen3:4b | nl-gpu01 | 11434 | -- | Query rewriting, HyDE generation, low-latency classification |
| qwen3:30b-a3b | nl-gpu01 | 11434 | -- | MoE reasoning (fallback for complex queries) |
| devstral-small-2 | nl-gpu01 | 11434 | -- | Code analysis fallback |

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
| Anthropic API | High | TLS cert chain, API key auth, commercial terms |
| OpenAI API | Retired | Was: TLS cert chain, API key auth, commercial terms. Decommissioned 2026-04-28 (IFRNLLEI01PRD-746). |
| Ollama (local) | Medium | SHA-256 on download, but no ongoing integrity monitoring |
| Custom fine-tunes | N/A | No fine-tuned models in use |

## Supply Chain Risks

| Risk | Mitigation | Status |
|------|-----------|--------|
| Model poisoning (OWASP LLM04) | API-served models: provider responsibility. Local models: SHA-256 at download | Mitigated |
| Model version drift | Pinned model IDs in all configs (claude-haiku-4-5-20251001, not "latest") | Mitigated |
| Credential compromise | ANTHROPIC_API_KEY tracked in credential_usage_log with 90-day rotation. OAuth tokens (`sk-ant-oat-*`) auto-refresh per host; expiry exposed via `claude_oauth_expires_at` Prometheus gauge. OPENAI_API_KEY revoked 2026-04-28. | Tracked |
| Data leakage via API | Commercial API terms prohibit training on data; local models have no external connectivity | Mitigated |
| Adapter/plugin poisoning | No adapters or fine-tunes in use; OpenClaw plugins are self-hosted | N/A |

## Review Schedule

Model provenance reviewed quarterly alongside the industry benchmark assessment.
Next review: 2026-07-15
