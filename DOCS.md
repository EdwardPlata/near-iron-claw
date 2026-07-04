# near-iron-claw — Developer Documentation

A complete tour of the codebase: what every piece does, how the layers fit together, how to
run and test it locally, and **how to design and ship a new feature**. Every path below is a
clickable link into the repo.

> New here? Read this top-to-bottom once, then jump to [Start a new feature](#8-start-a-new-feature).

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [The big picture (architecture)](#2-the-big-picture-architecture)
3. [Repository map](#3-repository-map)
4. [The Python core — library + CLI](#4-the-python-core--library--cli)
5. [The deployed stack — Supabase + Vercel](#5-the-deployed-stack--supabase--vercel)
6. [Data model](#6-data-model)
7. [Local development](#7-local-development)
8. [Start a new feature](#8-start-a-new-feature)
9. [Testing & CI](#9-testing--ci)
10. [Deployment & redeploy](#10-deployment--redeploy)
11. [Reference](#11-reference)

---

## 1. What this project is

`near-iron-claw` is a small, well-tested client for **NEAR AI Cloud** — the hosted
[IronClaw](https://github.com/nearai) endpoint, an **OpenAI-compatible** LLM gateway at
`https://cloud-api.near.ai/v1`. The raw connection facts live in [`CONNECTING.md`](CONNECTING.md);
the formal requirements live in [`SPEC.md`](SPEC.md).

It exists in two forms that share one design (a thin, resilient middleware over an
OpenAI-compatible gateway):

- **A Python library + CLI** (`near_iron_claw`) — the reference implementation. See
  [section 4](#4-the-python-core--library--cli).
- **A deployed web stack** (Supabase backend + Vercel frontend) that wraps the same pattern as
  a live chat app with a provider-fallback chain, request logging, and graceful degradation. See
  [section 5](#5-the-deployed-stack--supabase--vercel) and [`DEPLOY.md`](DEPLOY.md).

## 2. The big picture (architecture)

Every layer is a **middleware**: it validates, adds a concern, and forwards.

```
Browser  ─POST /api/chat─▶  Vercel fn  ─▶  Supabase edge fn  ─▶  LLM provider(s)
(web/)                      (api/*.js)      (functions/chat)      (NEAR AI + fallbacks)
   ▲                            │                  │
   └────── GET /api/logs ───────┴──▶ Supabase `logs` fn ──▶ request_logs table
```

- The **NEAR AI key never reaches the browser or Vercel** — it lives only in the RLS-locked
  `app_config` row and is read by the Supabase edge function's service role.
- If no provider answers, the chain **degrades gracefully** to a `200` echo instead of failing,
  and logs the failure. See [`supabase/functions/chat/index.ts`](supabase/functions/chat/index.ts).

The Python library ([`src/near_iron_claw/client.py`](src/near_iron_claw/client.py)) is the same
pattern condensed into one class, `NearAIClient`.

## 3. Repository map

### Python core
| Path | What it does |
|------|--------------|
| [`src/near_iron_claw/__init__.py`](src/near_iron_claw/__init__.py) | Public exports: `NearAIClient`, `Settings`, the error types, `__version__`. |
| [`src/near_iron_claw/config.py`](src/near_iron_claw/config.py) | `Settings.load()` — reads `.env`/env, applies aliases; `redact()` for secret-safe display. |
| [`src/near_iron_claw/errors.py`](src/near_iron_claw/errors.py) | Typed exception hierarchy rooted at `NearAIError`. |
| [`src/near_iron_claw/client.py`](src/near_iron_claw/client.py) | `NearAIClient`: `list_models`, `chat`, `stream_chat`, `verify` + retries. |
| [`src/near_iron_claw/cli.py`](src/near_iron_claw/cli.py) | argparse CLI: `config` / `models` / `chat` / `verify` (+ `--json`, `--stream`). |
| [`src/near_iron_claw/__main__.py`](src/near_iron_claw/__main__.py) | Enables `python -m near_iron_claw`. |

### Tests
| Path | What it covers |
|------|----------------|
| [`tests/conftest.py`](tests/conftest.py) | Fixtures (`make_client` with `httpx.MockTransport`) + `--run-live` gating. |
| [`tests/test_config.py`](tests/test_config.py) | Config loading, alias precedence, redaction, retry-floor. |
| [`tests/test_client.py`](tests/test_client.py) | HTTP behavior, retries, streaming, typed errors, malformed responses. |
| [`tests/test_verify.py`](tests/test_verify.py) | The `verify()` health-check and its reachable-vs-key-valid split. |
| [`tests/test_cli.py`](tests/test_cli.py) | CLI subcommands, `--json`, flag guards, secret redaction. |
| [`tests/test_live_smoke.py`](tests/test_live_smoke.py) | Optional live tests (skipped without `--run-live` + a valid key). |

### Deployed stack
| Path | What it does |
|------|--------------|
| [`supabase/functions/chat/index.ts`](supabase/functions/chat/index.ts) | Backend middleware: provider fallback chain, logging, graceful degrade, persistence. |
| [`supabase/functions/logs/index.ts`](supabase/functions/logs/index.ts) | Read-only recent `request_logs` (no secret columns). |
| [`api/chat.js`](api/chat.js) | Vercel middleware → Supabase `chat` edge function. |
| [`api/logs.js`](api/logs.js) | Vercel middleware → Supabase `logs` edge function. |
| [`api/health.js`](api/health.js) | Readiness probe (checks backend reachability). |
| [`web/index.html`](web/index.html) | Chat UI + Logs panel (vanilla JS, no build). |
| [`vercel.json`](vercel.json) | `builds` (static `web/` + Node `api/`) + `routes`. |
| [`.vercelignore`](.vercelignore) | Keeps the Python package out of the Vercel build. |

### Config, docs, tooling
| Path | What it does |
|------|--------------|
| [`pyproject.toml`](pyproject.toml) | Packaging (hatchling), the `near-iron-claw` console script, deps, ruff + pytest config. |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI: ruff + pytest on Python 3.9 / 3.11 / 3.12. |
| [`scripts/smoke.sh`](scripts/smoke.sh) | End-to-end smoke test of the live middleware chain (8 assertions). |
| [`.env.example`](.env.example) | Template for the connection config; copy to `.env`. |
| [`README.md`](README.md) | Quick start for the Python library + CLI. |
| [`SPEC.md`](SPEC.md) | The spec kit — goals, requirements, acceptance criteria. |
| [`CONNECTING.md`](CONNECTING.md) | Raw NEAR AI Cloud connection facts + `curl` recipes. |
| [`DEPLOY.md`](DEPLOY.md) | The deployed stack — URLs, secrets model, redeploy steps. |
| [`.claude/README.md`](.claude/README.md) | The curated Claude Code agent toolkit for this repo. |

## 4. The Python core — library + CLI

The reference implementation. Install and use it as described in [`README.md`](README.md).

### As a library
```python
from near_iron_claw import NearAIClient, Settings

with NearAIClient(Settings.load()) as client:
    print(client.list_models())
    print(client.chat([{"role": "user", "content": "ping"}], max_tokens=16))
```

Key pieces (all in [`src/near_iron_claw/`](src/near_iron_claw)):

- **[`Settings`](src/near_iron_claw/config.py)** — immutable config resolved from `.env` +
  environment. Accepts the `LLM_*`, `OPENAI_*`, and `NEAR_AI_*` aliases (see
  [Reference](#env-vars)). `Settings.redacted()` and `redact()` guarantee the key is never
  printed in full.
- **[`NearAIClient`](src/near_iron_claw/client.py)** — a thin, synchronous
  [`httpx`](https://www.python-httpx.org/) wrapper:
  - `list_models()` → sorted model ids
  - `chat(messages, …)` → assistant text (blocking)
  - `stream_chat(messages, …)` → yields SSE content deltas
  - `verify()` → a [`VerifyResult`](src/near_iron_claw/client.py) that reports **gateway
    reachability and key validity separately** (a public `/models` 200 does *not* prove the key —
    the key is proven with a minimal `/chat/completions` call).
  - Retries are **method-aware**: `429` retries for any method; `5xx` retries only for idempotent
    `GET` (so a `POST` completion is never silently re-billed).
- **[Errors](src/near_iron_claw/errors.py)** — catch everything with `NearAIError`, or be precise
  with `AuthError` / `RateLimitError` / `APIStatusError` / `APIResponseError` /
  `APIConnectionError` / `ConfigError`.

### As a CLI
Defined in [`cli.py`](src/near_iron_claw/cli.py):
```bash
near-iron-claw config     # resolved settings (key redacted)
near-iron-claw verify     # gateway up? key valid? (exit != 0 on failure)
near-iron-claw models     # list model ids
near-iron-claw chat "hi"  # one-shot; add --stream to stream, --json for machine output
```

## 5. The deployed stack — Supabase + Vercel

Full details and live URLs are in [`DEPLOY.md`](DEPLOY.md). In short:

- **Frontend** — [`web/index.html`](web/index.html): a dependency-free chat UI with a **Logs**
  panel. It only ever calls `/api/chat` and `/api/logs`; it holds no secrets.
- **Vercel middleware** — [`api/chat.js`](api/chat.js), [`api/logs.js`](api/logs.js),
  [`api/health.js`](api/health.js): validate input and forward to Supabase using the *public* anon
  key. Routing is defined in [`vercel.json`](vercel.json).
- **Supabase backend** — [`chat`](supabase/functions/chat/index.ts) and
  [`logs`](supabase/functions/logs/index.ts) edge functions ([Deno](https://deno.com/)). `chat`
  reads provider credentials from the RLS-locked `app_config` row (service role), tries the
  **fallback chain**, logs every attempt to `request_logs`, and **degrades gracefully** when no
  provider answers.

External docs: [Supabase Edge Functions](https://supabase.com/docs/guides/functions) ·
[Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security) ·
[Vercel Functions](https://vercel.com/docs/functions) ·
[`vercel.json` reference](https://vercel.com/docs/projects/project-configuration).

## 6. Data model

Four tables, all with **RLS enabled and no policies** (locked to everyone except the edge
functions' service role). Created by the migrations applied to Supabase project
`duesorupitzmjubbylxg` (mirrored by the DDL described in [`DEPLOY.md`](DEPLOY.md)).

| Table | Purpose | Sensitive? |
|-------|---------|-----------|
| `app_config` | Singleton row: `llm_base_url`, `llm_api_key`, `llm_model`, `fallback_providers` (jsonb). | **Yes** — holds keys; never exposed to anon. |
| `sessions` | One row per conversation. | No |
| `messages` | User/assistant turns, linked to a session. | No |
| `request_logs` | Every upstream attempt: provider, http_status, ok, latency_ms, degraded, error. | No (no key columns). |

## 7. Local development

```bash
# 1. Python core
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # editable install + pytest/ruff  (see pyproject.toml)
cp .env.example .env               # then set LLM_API_KEY to a real key from https://cloud.near.ai

near-iron-claw verify              # sanity-check the connection
pytest                             # fast, fully offline (mocked HTTP)
ruff check .                       # lint

# 2. Deployed stack (optional, needs the CLIs)
npx vercel@latest deploy --prod --yes --scope <team>   # frontend + api/
#   Supabase functions are deployed via the Supabase MCP tools or the Supabase CLI.
bash scripts/smoke.sh              # verify the live chain (8 assertions)
```

Config resolution and the full env-var list are in [Reference](#env-vars).

## 8. Start a new feature

The recommended loop for designing and shipping a change.

### Step 1 — Write the design into the spec
Add the requirement to [`SPEC.md`](SPEC.md) first: a functional requirement (`FR#`), any
non-functional constraint (`NFR#`), and an acceptance criterion. This is the "feature design"
artifact — decide *what done looks like* before writing code.

### Step 2 — Decide which layer it belongs in
Use this table to place the work:

| If the feature is… | Put it in… | Example |
|--------------------|-----------|---------|
| New client capability / API call | [`src/near_iron_claw/client.py`](src/near_iron_claw/client.py) (+ exports in [`__init__.py`](src/near_iron_claw/__init__.py)) | embeddings, tool-calls |
| New config / env var | [`src/near_iron_claw/config.py`](src/near_iron_claw/config.py) | a new provider setting |
| New CLI command / flag | [`src/near_iron_claw/cli.py`](src/near_iron_claw/cli.py) | `near-iron-claw embed` |
| New backend behavior (routing, logging, auth) | [`supabase/functions/chat/index.ts`](supabase/functions/chat/index.ts) | rate limiting, caching |
| New backend endpoint | new folder under [`supabase/functions/`](supabase/functions) + a matching [`api/*.js`](api) proxy + a route in [`vercel.json`](vercel.json) | `/api/usage` |
| Schema change | a Supabase migration (see [`DEPLOY.md`](DEPLOY.md)) | new table/column |
| UI change | [`web/index.html`](web/index.html) | message editing |

### Step 3 — Branch, implement, test
```bash
git checkout -b feat/<name>
# ...implement, following the style of the surrounding code...
pytest && ruff check .             # for Python changes
node --check api/*.js              # for Vercel function changes
```
Add tests next to the layer you touched (see [section 9](#9-testing--ci)). For a new backend
endpoint, extend [`scripts/smoke.sh`](scripts/smoke.sh) with an assertion.

### Step 4 — Review
Run the built-in Claude Code skills before opening a PR:
- `/code-review high` — correctness + quality (multi-agent).
- `/security-review` — secret handling, injection, RLS.
- For DB/schema changes, run the Supabase **security advisors** (see [`DEPLOY.md`](DEPLOY.md)).

The curated agents for this repo are listed in [`.claude/README.md`](.claude/README.md).

### Step 5 — Deploy & verify
Deploy the affected layer ([section 10](#10-deployment--redeploy)), then run
`bash scripts/smoke.sh` and confirm the acceptance criterion from Step 1.

### Step 6 — Open the PR
Push the branch and open a PR that references the `SPEC.md` requirement and the verification
results.

## 9. Testing & CI

- **Python** — [`pytest`](https://docs.pytest.org/) with [`httpx.MockTransport`], so the whole
  suite runs offline with no key. Structure mirrors the source: one `test_*.py` per module.
  Fixtures live in [`tests/conftest.py`](tests/conftest.py). Live tests
  ([`test_live_smoke.py`](tests/test_live_smoke.py)) are deselected unless `--run-live` (or
  `RUN_LIVE=1`) and a valid key are present.
- **End-to-end** — [`scripts/smoke.sh`](scripts/smoke.sh) curls the live URLs and asserts status
  codes across all layers.
- **CI** — [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs ruff + pytest on Python
  3.9 / 3.11 / 3.12 for every push and PR.

Run everything locally:
```bash
pytest --cov=near_iron_claw --cov-report=term-missing
ruff check .
bash scripts/smoke.sh
```

## 10. Deployment & redeploy

See [`DEPLOY.md`](DEPLOY.md) for the authoritative steps and URLs. Summary:

| Layer | How to deploy |
|-------|---------------|
| Frontend + Vercel middleware | `npx vercel@latest deploy --prod --yes --scope <team>` |
| Supabase edge functions | Supabase MCP `deploy_edge_function`, or `supabase functions deploy <name> --project-ref duesorupitzmjubbylxg` |
| Schema change | Supabase MCP `apply_migration`, or `supabase db push` |
| Python package | `python -m build` → publish the wheel |

**No redeploy needed** to add a working LLM provider — insert into `app_config.fallback_providers`
(SQL in [`DEPLOY.md`](DEPLOY.md)); the [`chat`](supabase/functions/chat/index.ts) function picks it
up on the next request.

## 11. Reference

### Live endpoints
| Endpoint | What it returns |
|----------|-----------------|
| `https://near-iron-claw.vercel.app/` | The chat UI |
| `…/api/health` | Readiness + backend reachability |
| `…/api/chat` (POST) | Chat completion, or a graceful `degraded` reply |
| `…/api/logs` (GET) | Recent upstream attempts |
| `https://duesorupitzmjubbylxg.supabase.co/functions/v1/chat` | Supabase backend (requires JWT) |

### Env vars {#env-vars}
Resolved by [`Settings.load()`](src/near_iron_claw/config.py); the first non-empty of each row wins.

| Variable(s) | Meaning | Default |
|-------------|---------|---------|
| `LLM_BASE_URL` / `OPENAI_BASE_URL` | Gateway base URL | `https://cloud-api.near.ai/v1` |
| `LLM_API_KEY` / `OPENAI_API_KEY` / `NEAR_AI_API_KEY` | Bearer key (`sk-agent-…`) | — |
| `LLM_MODEL` / `OPENAI_MODEL` | Default model slug | `anthropic/claude-sonnet-4-6` |
| `LLM_TIMEOUT` | Per-request timeout (s) | `60` |
| `LLM_MAX_RETRIES` | Retries on transient errors | `2` |

Vercel functions also read (with public-safe fallbacks embedded): `SUPABASE_FUNCTION_URL`,
`SUPABASE_LOGS_URL`, `SUPABASE_ANON_KEY`.

### External resources
- [NEAR AI Cloud dashboard](https://cloud.near.ai) — get/rotate keys
- [NEAR AI / IronClaw](https://github.com/nearai)
- [httpx](https://www.python-httpx.org/) · [pytest](https://docs.pytest.org/) · [ruff](https://docs.astral.sh/ruff/)
- [Supabase docs](https://supabase.com/docs) · [Vercel docs](https://vercel.com/docs) · [Deno](https://deno.com/)

### Related docs in this repo
[`README.md`](README.md) · [`SPEC.md`](SPEC.md) · [`CONNECTING.md`](CONNECTING.md) ·
[`DEPLOY.md`](DEPLOY.md) · [`.claude/README.md`](.claude/README.md)
