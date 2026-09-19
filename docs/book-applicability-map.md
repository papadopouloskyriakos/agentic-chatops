# LLM Engineer's Handbook — chapter applicability map

**Date:** 2026-06-16 (IFRNLLEI01PRD-1097)
**Why:** the handbook benchmark ([`llm-engineers-handbook-gap-analysis.md`](llm-engineers-handbook-gap-analysis.md)) graded this platform against the book. This file records which chapters are **N/A by design** because the platform consumes off-the-shelf models (no training) — so a future reviewer doesn't mistake a deliberate non-implementation for a gap. Decision record: the "No fine-tuning" ADR in [`model-provenance.md`](model-provenance.md).

| Handbook chapter | Applies here? | Why |
|---|---|---|
| 1 — LLM Twin / FTI architecture | ✅ Applies | Mapped onto the event-driven Runner + infragraph seed→learn→predict→eval FTI shape. |
| 2 — MLOps/LLMOps tooling | ✅ Applies (substituted) | n8n / SQLite / Prometheus / Ollama / Claude-CLI instead of ZenML/Comet/Opik/SageMaker — property-first, per the book's own anti-dogma rule. |
| 3 — Data engineering | ✅ Applies | infragraph ETL + session/knowledge ingestion (CDC via content_hash, IFRNLLEI01PRD-1091). |
| 4 — RAG feature pipeline | ✅ Applies | 5-signal RRF + cross-encoder rerank + LongContextReorder. |
| **5 — Supervised fine-tuning (LoRA/QLoRA/PEFT)** | ❌ **N/A by design** | Base agent model is **closed-weight Claude** — fine-tuning is structurally unavailable. Behavioral adaptation is done via prompt-policy iteration (prompt-patch A/B trials) + RAG, the book's recommended pre-fine-tuning order. |
| **6 — Preference alignment (DPO/RLHF)** | ❌ **N/A by design** (closed-weight) | Substitute: prompt-patch A/B trials + risk-approval feedback loop (IFRNLLEI01PRD-1079/-1096). No weight-level DPO. |
| 7 — Evaluating LLMs | ✅ Applies | LLM-as-judge + judge calibration + RAGAS + hard-eval (IFRNLLEI01PRD-1085/-1087/-1088/-1096). |
| **8 — Inference optimization: quantization-aware training** | ❌ **N/A by design** | No QAT (closed/pre-quantized models). The *runtime* half (KV-cache num_ctx, pre-quantized GGUF tiers, latency budget) ✅ applies. |
| 9 — RAG inference pipeline | ✅ Applies | Query rewrite + rerank + LCR live; self-query/metadata pre-filter in progress (IFRNLLEI01PRD-1092). |
| 10 — Inference deployment | ✅ Applies (substituted) | n8n background-launch + SSH dispatch + progress polling instead of SageMaker. |
| 11 + Appendix — MLOps/LLMOps + monitoring | ✅ Applies | CI validator gate, schema-versioning, OTel traces, QA harness (IFRNLLEI01PRD-1083/-1089/-1093/-1095). |

**Net:** chapters 5, 6, and the QAT half of 8 are N/A-by-design (closed-weight, off-the-shelf). Every other chapter's *properties* apply and are tracked in the epic.
