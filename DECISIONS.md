# DECISIONS.md — architecture choices & known gaps

## Choices (vs recommended stack)
1. **DB: SQLite default, Postgres via DATABASE_URL.** Keeps `pytest`/local runs zero-dep;
   docker-compose uses `pgvector/pg16`. Vectors stored as JSON text so both work without pgvector.
2. **Queue: Celery + Redis, with eager/inline fallback.** `enqueue_ingest` runs inline when
   Redis is unreachable so the API/tests work without infra. Documented, not silent.
3. **Parsing: `ast` (Python) + regex heuristics (JS/TS/others); tree-sitter opportunistic.**
   `try_treesitter()` returns None when grammars aren't installed; deterministic parsers are
   authoritative and covered by fixture tests. Rationale: reproducible offline builds.
4. **Embeddings: TF-IDF hash fallback default; sentence-transformers optional (`EMBEDDING_BACKEND=st`).**
   Code retrieval is keyword-heavy; TF-IDF is offline/deterministic. Swap-able interface.
5. **LLM: hand-rolled retrieval+prompt layer (no LangChain), provider `anthropic|openai|offline`.**
   Default `offline` = extractive answers composed only from retrieved evidence — grounded by
   construction, demoable without keys. Live LLMs used when keys are set; citation guard runs either way.
6. **Modules heuristic:** top-level dir after stripping generic roots (`src/app/backend/...`),
   max 2 levels (`orders`, `inventory/pricing`). Explainable + language-agnostic.
7. **Credential storage:** Fernet when `CREDENTIAL_FERNET_KEY` set, else base64-obfuscated.
   Prod TODO: real secret manager (see Known Gaps).

## Known Gaps (`# TODO(agent)` search)
- GitHub OAuth callback is a stub; PAT-per-project is the supported private-repo path.
- `try_treesitter` grammar loading not wired (env-specific); regex/ast path is real.
- Rate limit is in-memory per process (needs Redis for multi-worker).
- No k8s manifests yet (docker-compose only).
- Embeddings recomputed fully on re-sync (no incremental vector update).
