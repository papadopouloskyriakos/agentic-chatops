# Asymmetric Embedding Prefixes

`nomic-embed-text` is asymmetric-trained: a single model but with different prefixes
at inference time to optimize the query-versus-document retrieval signal.

## The two prefixes

- **`search_query: `** is prepended when embedding the USER QUERY in `kb-semantic-search.py:embed_query()`.
- **`search_document: `** is prepended when embedding a DOCUMENT for storage in
  `kb-semantic-search.py:embed_document()` and `scripts/archive-session-transcript.py`,
  `scripts/agent-diary.py`, `scripts/ragas-eval.py`.

## Why the difference matters

The nomic-embed-text model was trained with distinct task markers so the query
and document embeddings are not symmetric — the vector space is skewed to place
a well-phrased query close to its matching document, not close to other queries.
Using the WRONG prefix (or no prefix) costs roughly 2-5 precision points because
the cosine similarity then measures something the model wasn't trained to
minimize — this is why a document embedded without the prefix will retrieve less
reliably when hit with a correctly-prefixed query.

## When each prefix is used — single-line reference

- Query side → `search_query:` (one function: `embed_query`).
- Document side → `search_document:` (one function: `embed_document`, everything else).

## Related

- `feedback_ollama_num_ctx_vram.md` — also set `num_ctx` on every Ollama embed call.
- `scripts/migrate-embeddings.py` — the original re-embed of 929 historical rows
  applied `search_document:` to every stored vector.

## Signal of the difference

Compare the cosine of the same text embedded both ways versus itself: the
`search_query` and `search_document` embeddings of an identical string will NOT
be cosine 1.0 — they diverge by roughly 0.10-0.15 cosine (measured 2026-04-17
during the G7 migration). That divergence is precisely the asymmetric shift,
the signal we exploit for retrieval.
