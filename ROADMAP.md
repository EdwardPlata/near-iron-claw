# ROADMAP — Pipeline Creator API

Phased plan for the [Pipeline Creator feature](FEATURE.md). Each phase is independently shippable.
✅ = done, 🔜 = next, 🗓️ = planned.

## Phase 1 — MVP: design + dry-run ✅ (this change)

- ✅ `PipelineSpec` + whitelisted transform ops (safe, declarative).
- ✅ Ingestion connectors: `apify-actor`, `apify-dataset`, `custom-http` (SSRF-guarded).
- ✅ LLM `PipelineDesigner` with JSON validation, one repair retry, and deterministic degrade.
- ✅ FastAPI app: `POST /v1/pipelines`, `GET /v1/pipelines`, `GET /v1/pipelines/{id}`,
  `POST /v1/pipelines/{id}/dry-run`, `GET /v1/channels`, `GET /health`.
- ✅ In-memory store, error envelope, secret scrubbing.
- ✅ Full offline test suite; ruff-clean; installed via the `api` extra.

## Phase 2 — Execution & destinations 🔜

- 🔜 Full (non-dry) runs with pagination over the whole source (Apify dataset paging, custom-http
  cursor pagination hints).
- 🔜 Load targets beyond `return`/`jsonl`: **Supabase** (reuse the deployed project's tables),
  Postgres, webhook.
- 🔜 Run records + status (`queued`/`running`/`succeeded`/`failed`) persisted per run.
- 🔜 Stream/emit large results without buffering everything in memory.

## Phase 3 — Persistence & multi-tenant 🗓️

- 🗓️ Durable store: move pipelines/runs into Supabase (RLS-locked, like `app_config`/`messages`).
- 🗓️ Secret indirection: store a `secret_ref` (name) instead of inline tokens; resolve from a
  `SecretsBackend` (env → Vault/AWS Secrets Manager).
- 🗓️ Per-tenant isolation and ownership on pipelines.

## Phase 4 — Hardening & DX 🗓️

- 🗓️ AuthN/Z: service API keys (Bearer), per-key **rate limits** (`POST /v1/pipelines` is the
  expensive one), `Retry-After`.
- 🗓️ **Idempotency-Key** on `POST` endpoints; **cursor pagination** on list endpoints.
- 🗓️ Observability: structured logs (secret-redacted), request ids, metrics, tracing.
- 🗓️ A Python SDK + CLI subcommand (`near-iron-claw pipeline create …`).

## Phase 5 — Product surface 🗓️

- 🗓️ Wire the API into the deployed [Vercel + Supabase stack](DEPLOY.md) as a new middleware
  endpoint with a small pipeline-builder UI.
- 🗓️ Scheduling / recurring runs (cron), backfills, and alerting on failures.
- 🗓️ A channel marketplace: register new connectors via a plugin interface (`GET /v1/channels`
  already advertises the catalog).

## Deferred / explicitly out of scope

Arbitrary code in transforms (security), synchronous long-running full runs over the HTTP request
(use background workers in Phase 2+), and non-JSON source formats (CSV/XML ingestion) until there
is demand.
