# Architecture

## Data flow

```text
Explicit CLI command
  ├── offline JSON fixtures (default)
  └── reviewed arXiv query + --allow-network
         ↓ size/schema/URL/XML checks
       Paper records
         ↓ SQLite transaction + stable ID + content hash
       Local index (maximum 5,000 papers)
         ├── BM25 ranking → exact excerpt extraction → citation verifier
         │                      └── optional loopback model chooses existing IDs
         └── daily changed-record selection → Markdown + JSON brief

Loopback dashboard → local read APIs + evidence query API
Finite watcher → bounded ingestion + local brief writer
```

## Modules

- `models.py`: typed records, validation, stable identity, hash, shared tokenization.
- `sources.py`: local JSON, reviewed arXiv source config, public-DNS validation, pinned TLS connection, bounded UTF-8 Atom parsing.
- `store.py`: SQLite transactions, atomic upserts, request budget, ingestion audit totals.
- `retrieval.py`: BM25 with query-coverage weighting, sentence selection, provenance checks, abstention.
- `local_model.py`: optional Ollama evidence-ID selection with strict output validation and fallback.
- `briefs.py`: changed-record digest and escaped Markdown export.
- `scheduler.py`: finite foreground cycles, exclusive lock, stop-on-error behavior.
- `web.py`: loopback-only stdlib HTTP server, fixed routes, same-origin protections, no source mutation APIs.
- `evaluation.py`: deterministic synthetic regression checks.

## Identity and evidence

The paper key is the first 20 hex characters of SHA-256 over `source + NUL + external_id`. arXiv version suffixes are removed from stable identifiers; the versioned URL is retained. Content hash covers normalized validated metadata and abstract. Updating a paper preserves its first-seen timestamp but changes `updated_at` and its content hash.

A citation contains paper ID, title, source, version URL, exact quote, half-open character offsets, content hash, and synthetic status. The verifier re-reads the current record and checks quote/offset/hash/URL agreement. A previously returned citation fails verification after its source version changes. The index does not preserve an archive of old versions, so retain exported evidence if historical provenance is needed.

## Retrieval decisions

BM25 avoids a mandatory embedding model and index dependency. Titles receive double term weight. Scores are ranking signals only, not probabilities. Sentences need at least two distinct matching query tokens, or one when the question has only one informative token. At most one sentence per paper is returned, capped at four papers by the CLI and UI.

This heuristic is intentionally simple. It cannot infer entailment or resolve negation. For example, “evidence against X” and “evidence for X” may match the same terms. Read the quotations and full papers. The evaluation set confirms regression behavior on synthetic examples, not semantic coverage.

## Local-model boundary

The optional model receives the current question and candidate excerpts only. It returns evidence IDs. It cannot make source requests, run tools, write reports, send messages, or append arbitrary prose to an answer. The verifier still checks selected excerpts. Malformed JSON, wrong types, unknown IDs, duplicates, timeout, and oversized output fall back to deterministic extraction.

The adapter does not install Ollama or pull models. The loopback endpoint is fixed. Use a trusted local-only runtime; an HTTP service on loopback can itself forward data elsewhere, which this program cannot control. A small 1–3B quantized model is a practical starting choice for an 8 GB Mac, but memory/latency depend on the runtime and are not guaranteed.

## Resource bounds

| Resource | Bound |
| --- | --- |
| Indexed papers | 5,000 |
| Papers per local batch | 500 |
| Configured live queries | 5 |
| Live results per query | 1–100 |
| Input/source response | 2 MB |
| Abstract | 24,000 characters |
| Question | 3,000 characters |
| Live requests per named source per UTC day | 1–24, default 8 |
| Request timeout | 20 seconds for arXiv; 30 seconds for optional model |
| Watch cycles | 1–24 |
| Watch interval | 300–86,400 seconds |
| Scheduled waits per watch invocation | At most 24 hours |
| Local-model context / generated tokens | 2,048 / 128 |

Timeouts are socket-operation timeouts, not hard wall-clock deadlines against a server that slowly trickles data. Response size caps still apply. The stdlib web server is sequential and intended for one local user, not concurrent public traffic. A larger corpus or embedding model would need measured resource and evaluation work before claiming support.
