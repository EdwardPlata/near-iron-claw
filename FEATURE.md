# FEATURE: Pipeline Creator API

> Spec: [`SPEC.md` §Feature](SPEC.md) · Roadmap: [`ROADMAP.md`](ROADMAP.md) · Code:
> [`src/near_iron_claw/pipeline/`](src/near_iron_claw/pipeline)

Design informed by two subagents (an `api-designer` for the REST surface and a `data-engineer`
for the pipeline abstraction + Apify integration), then scoped to a shippable, fully-tested MVP.

## 1. Problem

Users want to point an LLM at a data source — an [Apify](https://apify.com) actor/dataset or
their **own HTTP ingestion channel** — describe a goal in plain English, and get back a
**structured, executable data pipeline** (extract → transform → load) they can inspect and
dry-run. Today that means hand-writing glue code per source.

## 2. Goals & non-goals

**Goals (MVP):** design a pipeline from `{goal, channel}` via the LLM; pluggable ingestion
connectors (`apify-actor`, `apify-dataset`, `custom-http`); a bounded **dry-run** that fetches a
sample and applies the pipeline's transforms; graceful degradation to a deterministic pipeline
when the LLM key is unavailable.

**Non-goals (MVP → see [`ROADMAP.md`](ROADMAP.md)):** auth/API keys, rate limiting, idempotency
keys, cursor pagination, full (non-dry) runs to external destinations, scheduling, durable
persistence, secret-manager indirection.

## 3. Architecture

```
FastAPI app  (near_iron_claw.pipeline.api:app)
  ├─ POST /v1/pipelines ─────▶ PipelineDesigner ──▶ NearAIClient ──▶ NEAR AI Cloud
  │                                │  (LLM designs a PipelineSpec as JSON; validated)
  │                                └─ degrade ─▶ deterministic rule-based spec
  ├─ POST /v1/pipelines/{id}/dry-run ─▶ Connector.fetch(sample) ─▶ transforms.execute
  │        apify-actor  → POST /v2/acts/{id}/run-sync-get-dataset-items
  │        apify-dataset→ GET  /v2/datasets/{id}/items
  │        custom-http  → user URL (SSRF-guarded) + dot-path extract
  ├─ GET  /v1/channels · GET /v1/pipelines · GET /v1/pipelines/{id}
  └─ GET  /health
```

Reuses the existing [`NearAIClient`](src/near_iron_claw/client.py) (sync httpx). FastAPI runs the
sync route handlers in a threadpool, so no async rewrite is needed. Connectors accept an injected
`httpx.Client` (a `MockTransport` in tests), exactly like `NearAIClient`.

## 4. Modules ([`src/near_iron_claw/pipeline/`](src/near_iron_claw/pipeline))

| File | Responsibility |
|------|----------------|
| [`models.py`](src/near_iron_claw/pipeline/models.py) | Pydantic v2 models: channels (discriminated `type`), whitelisted transforms (discriminated `op`), `PipelineSpec`, request/response, error envelope. |
| [`transforms.py`](src/near_iron_claw/pipeline/transforms.py) | Safe declarative executor — pure functions in a dispatch table; **no `eval`/`exec`**. |
| [`connectors.py`](src/near_iron_claw/pipeline/connectors.py) | `apify-actor` / `apify-dataset` / `custom-http` connectors + registry; SSRF guard; sample/timeout caps. |
| [`designer.py`](src/near_iron_claw/pipeline/designer.py) | LLM prompt → JSON → `PipelineSpec` (parse, validate, one repair retry); deterministic fallback. |
| [`store.py`](src/near_iron_claw/pipeline/store.py) | `PipelineStore` protocol + thread-safe in-memory implementation. |
| [`api.py`](src/near_iron_claw/pipeline/api.py) | FastAPI app, routes, dependency wiring, error-envelope handlers. |

## 5. Data model

- **Channels** (discriminated union on `type`): `apify-actor` (`actor_id`, `run_input`,
  `apify_token`), `apify-dataset` (`dataset_id`, `apify_token`), `custom-http` (`url`, `method`,
  `headers`, `body`, `records_path`). Secret fields (`apify_token`, `headers`) are **scrubbed
  before storage and never echoed** in responses (F-NFR1).
- **Transforms** (discriminated union on `op`, whitelist only): `select_fields`, `drop_fields`,
  `rename`, `filter`, `limit`, `dedupe`, `flatten`, `cast`, `add_field`. Each is a pure
  `list[dict] → list[dict]` function; the executor deep-copies input per step.
- **`PipelineSpec`**: `name`, `description`, `goal`, scrubbed `source`, ordered `steps`
  (`phase` ∈ extract/transform/load, each transform step carries `ops`), `load` target, `tags`.
- **`Pipeline`** (stored/returned): `pipeline_id`, `status`, scrubbed channel, `steps`, `load`,
  `meta {llm_used, llm_model, fallback_reason, step_count, created_at}`.

## 6. LLM designer

System prompt embeds the goal, the channel's **non-secret** shape, and the exact
`PipelineSpec`/transform-op schema, instructing JSON-only output. Flow: strip markdown fences →
`json.loads` → `PipelineSpec.model_validate` → **one repair retry** with the validation errors →
on any `NearAIError` (auth/timeout/parse) fall back to the deterministic rule-based generator and
set `llm_used=false` + `fallback_reason`. Every create returns **HTTP 201** regardless — the
client treats `llm_used=false` as an informational warning (same pattern as the deployed stack).

## 7. Security

- Secrets (`apify_token`, custom headers) are transient: used to fetch, then **scrubbed** — never
  persisted in a `PipelineSpec` nor returned (asserted in tests). Apify token may also come from
  the `APIFY_TOKEN` env var.
- **No code execution**: transforms are a closed whitelist dispatched from a table; unknown ops
  can't deserialize (Pydantic discriminator).
- **SSRF guard** on `custom-http`: only `http(s)`, and private/loopback/link-local/metadata hosts
  are rejected before any request.
- Dry-run is bounded: `sample_size` default 10, max 100, with a per-connector timeout.

## 8. Error model

Single envelope `{"error": {"code", "message", "detail?"}}` with correct status codes
(`400 validation_error`, `404 not_found`, `415 unsupported_media_type`,
`422 unprocessable` for unreachable/failed channels, `502 llm_upstream_error`). Secrets never
appear in error messages.

## 9. Testing

Fully offline: FastAPI [`TestClient`](https://fastapi.tiangolo.com/reference/testclient/), the LLM
mocked via `NearAIClient` + `httpx.MockTransport`, and Apify/custom-http mocked the same way.
Covers: transform ops, connectors (incl. SSRF rejection), the designer's happy path + repair +
degrade, secret scrubbing (a token in a request never appears in the stored spec/response), and
every endpoint. See [`tests/pipeline/`](tests/pipeline).

## 10. How to run

```bash
pip install -e ".[api]"
uvicorn near_iron_claw.pipeline.api:app --reload   # then open http://127.0.0.1:8000/docs
```
