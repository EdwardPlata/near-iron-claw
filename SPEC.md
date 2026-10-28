# near-iron-claw — Spec Kit

Spec-driven definition of the `near-iron-claw` client. See [`CONNECTING.md`](CONNECTING.md)
for the raw connection facts and [`README.md`](README.md) for usage.

## 1. Purpose

Provide a small, well-engineered **Python library + CLI** for talking to
**NEAR AI Cloud** (the hosted IronClaw endpoint), an **OpenAI-compatible** LLM gateway at
`https://cloud-api.near.ai/v1`. It turns the ad-hoc `curl` recipes in `CONNECTING.md` into a
tested, reusable package.

## 2. Goals

- **G1** — Load and validate connection config from `.env` / environment, never printing secrets.
- **G2** — List available models (`GET /v1/models`).
- **G3** — Run chat completions (`POST /v1/chat/completions`), blocking and streaming.
- **G4** — A `verify` health-check that distinguishes "gateway reachable" from "key valid",
  mirroring the guidance in `CONNECTING.md`.
- **G5** — Usable as a library (`from near_iron_claw import NearAIClient`) and a CLI
  (`near-iron-claw ...`).
- **G6** — Fully tested offline (mocked HTTP); CI green with no network or API key.

## 3. Non-goals

- Building IronClaw itself from Rust source.
- A web service / server (this is a client).
- Model fine-tuning, embeddings, or agent tool-loops (future work).

## 4. Requirements

### Functional
| ID | Requirement |
|----|-------------|
| FR1 | `Settings.load()` reads `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (+ OpenAI/NEAR aliases) from `.env`/env with sensible defaults. |
| FR2 | Missing/placeholder API key raises a clear `ConfigError` before any network call. |
| FR3 | `client.list_models()` returns model ids from the gateway. |
| FR4 | `client.chat(messages, ...)` returns the assistant message; supports `model`, `max_tokens`, `temperature`. |
| FR5 | `client.stream_chat(...)` yields incremental content deltas (SSE). |
| FR6 | HTTP/auth failures raise typed errors (`AuthError`, `RateLimitError`, `APIStatusError`, `APIConnectionError`). |
| FR7 | CLI subcommands: `config`, `models`, `chat`, `verify`; `--json` for machine output. |
| FR8 | `verify` reports gateway reachability and key validity separately and exits non-zero on failure. |

### Non-functional
| ID | Requirement |
|----|-------------|
| NFR1 | Secrets are redacted in all output/logs/reprs. |
| NFR2 | Configurable timeout + bounded retries with backoff on transient errors. |
| NFR3 | Python 3.9+; runtime deps limited to `httpx` and `python-dotenv`. |
| NFR4 | 100% of tests pass offline via `httpx.MockTransport`; a live smoke test skips when no valid key. |
| NFR5 | Type-hinted public API; documented in README. |

## 5. Architecture

```
src/near_iron_claw/
  __init__.py     public exports: NearAIClient, Settings, errors, __version__
  config.py       Settings dataclass + .load() + redaction helpers
  errors.py       exception hierarchy
  client.py       NearAIClient (httpx) — list_models, chat, stream_chat, verify
  cli.py          argparse CLI — config/models/chat/verify (+ --json)
  __main__.py     `python -m near_iron_claw`
```

Design: thin, synchronous httpx wrapper. The OpenAI-compatible surface means the same client
works against any slug the gateway exposes (`anthropic/claude-*`, `openai/gpt-*`, etc.).

## 6. Acceptance criteria

- [ ] `pip install -e .` exposes the `near-iron-claw` console script.
- [ ] `near-iron-claw config` prints resolved settings with the key redacted.
- [ ] `near-iron-claw verify` cleanly reports gateway-up + key-status and sets exit code.
- [ ] `near-iron-claw models` / `chat` work against a valid key (manual), mocked in tests.
- [ ] `pytest` passes with no network access and no API key set.
- [ ] CI (GitHub Actions) runs lint + tests on push/PR and is green.
- [ ] `/code-review` and `/security-review` findings addressed.

## 7. Known constraints

- The key committed at setup returns **HTTP 401** on `/chat/completions`
  (`api.near.ai` was retired 2025-10-31 → 410). A valid dashboard key from
  <https://cloud.near.ai> is required for live calls; the code degrades gracefully without one.

---

# Feature: Pipeline Creator API (v1)

Detailed design in [`FEATURE.md`](FEATURE.md); phased plan in [`ROADMAP.md`](ROADMAP.md).

## F1. Purpose
A **FastAPI** service that turns a natural-language ingestion goal + a source **ingestion
channel** (an [Apify](https://apify.com) actor/dataset, or the user's own HTTP endpoint) into a
**structured, executable data pipeline** designed by the LLM on NEAR AI Cloud (via
[`NearAIClient`](src/near_iron_claw/client.py)). It also dry-runs the pipeline against a sample.

## F2. Goals
- **FG1** — `POST /v1/pipelines`: given `{goal, channel}`, the LLM designs an ordered
  extract→transform→load `PipelineSpec` (validated JSON), persisted with an id.
- **FG2** — Pluggable **ingestion connectors**: `apify` and `custom-http` out of the box, behind
  one interface so users can add their own channels.
- **FG3** — `POST /v1/pipelines/{id}/run` (dry-run): fetch a bounded sample from the channel and
  apply the pipeline's **declarative** transforms; return the sample + record count.
- **FG4** — `GET /v1/channels`, `GET /v1/pipelines`, `GET /v1/pipelines/{id}`, `GET /health`.
- **FG5** — **Graceful degradation**: if the LLM key is unavailable, fall back to a deterministic
  rule-based pipeline and flag `degraded: true` (mirrors the deployed stack's behavior).

## F3. Non-goals (v1)
- Scheduling / recurring runs, durable orchestration, or a UI (see [`ROADMAP.md`](ROADMAP.md)).
- Arbitrary code execution in transforms — only a **whitelist** of declarative ops.

## F4. Functional requirements
| ID | Requirement |
|----|-------------|
| F-FR1 | `POST /v1/pipelines` validates the body, invokes the LLM designer, and returns a `PipelineSpec` + id. |
| F-FR2 | Ingestion channels are polymorphic (`type: apify | custom-http`) with per-type config. |
| F-FR3 | The Apify connector supports `run-sync-get-dataset-items` (actor) and dataset-items fetch, Bearer auth. |
| F-FR4 | Transforms are limited to a safe whitelist: `select_fields`, `rename`, `filter`, `limit`, `dedupe`, `flatten`. |
| F-FR5 | Dry-run returns at most `sample_size` records (bounded, default 10, max 100) with a timeout. |
| F-FR6 | LLM output is parsed as JSON and validated against `PipelineSpec`; invalid output → repair or degrade. |
| F-FR7 | All errors use one envelope `{error: {code, message, detail?}}` with correct HTTP status codes. |

## F5. Non-functional requirements
| ID | Requirement |
|----|-------------|
| F-NFR1 | Secrets (Apify token, LLM key) are **never** stored in a persisted `PipelineSpec` or returned in responses. |
| F-NFR2 | No arbitrary code exec; connectors enforce sample/timeout caps (SSRF-aware for custom-http). |
| F-NFR3 | Runtime deps limited to `fastapi`, `pydantic>=2`, `uvicorn`, `httpx`; installed via the `api` extra. |
| F-NFR4 | Fully testable offline: FastAPI `TestClient`, mocked Apify (`httpx.MockTransport`) and mocked LLM. |
| F-NFR5 | Type-hinted; ruff-clean; covered by CI. |

## F6. Acceptance criteria
- [ ] `pip install -e ".[api]"` then `uvicorn near_iron_claw.pipeline.api:app` serves the API + `/docs`.
- [ ] `POST /v1/pipelines` designs a valid pipeline (LLM mocked in tests; degrades without a key).
- [ ] Apify + custom-http dry-runs return a bounded sample (mocked upstream in tests).
- [ ] No secret ever appears in a stored spec or response (asserted in tests).
- [ ] `pytest` green offline; `ruff check .` clean; `/code-review` + `/security-review` addressed.
