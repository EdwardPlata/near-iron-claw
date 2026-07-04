# near-iron-claw

A small, well-tested **Python library + CLI** for talking to **NEAR AI Cloud** — the hosted
[IronClaw](https://github.com/nearai) endpoint, an **OpenAI-compatible** LLM gateway at
`https://cloud-api.near.ai/v1`.

It turns the ad-hoc `curl` recipes in [`CONNECTING.md`](CONNECTING.md) into a reusable,
type-hinted client with config loading, model listing, chat (blocking + streaming), and a
health check that faithfully distinguishes "gateway reachable" from "key actually works".

See [`SPEC.md`](SPEC.md) for the full spec kit and acceptance criteria.

## Documentation

- **[`DOCS.md`](DOCS.md) — full developer guide.** Start here: architecture, a hyperlinked
  repository map, the data model, local dev, and **how to design and ship a new feature**.
- [`SPEC.md`](SPEC.md) — requirements & acceptance criteria · [`CONNECTING.md`](CONNECTING.md) —
  raw connection facts · [`DEPLOY.md`](DEPLOY.md) — the deployed Supabase + Vercel stack.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # editable install with dev tools (pytest, ruff)
```

This exposes the `near-iron-claw` console script and the `near_iron_claw` importable package.

## Configure

Copy the example env file and drop in a real key from <https://cloud.near.ai>:

```bash
cp .env.example .env
# edit .env: set LLM_API_KEY=sk-agent-...
```

Config resolves from `.env` then the environment (env wins). Recognized variables:

| Variable | Meaning | Default |
|----------|---------|---------|
| `LLM_BASE_URL` / `OPENAI_BASE_URL` | Gateway base URL | `https://cloud-api.near.ai/v1` |
| `LLM_API_KEY` / `OPENAI_API_KEY` / `NEAR_AI_API_KEY` | Bearer key (`sk-agent-…`) | — |
| `LLM_MODEL` / `OPENAI_MODEL` | Default model slug | `anthropic/claude-sonnet-4-6` |
| `LLM_TIMEOUT` | Per-request timeout (s) | `60` |
| `LLM_MAX_RETRIES` | Retries on transient errors | `2` |

Secrets are **never printed in full** — `config` and logs show a redacted `sk-agent-…88a` form.

## CLI

```bash
near-iron-claw config            # show resolved settings (key redacted)
near-iron-claw verify            # health-check: gateway up? key valid? (exit != 0 on failure)
near-iron-claw models            # list available model ids
near-iron-claw chat "hello"      # one-shot chat completion
echo "hello" | near-iron-claw chat            # prompt from stdin
near-iron-claw chat "write a haiku" --stream  # stream tokens as they arrive
near-iron-claw --json verify     # machine-readable output (works on any command)
```

`verify` reports gateway reachability and key validity **separately**. Per `CONNECTING.md`, a
public `GET /models` 200 does *not* prove your key works, so the key check issues a minimal
`/chat/completions` call — the only endpoint that truly exercises the credential:

```text
✅ gateway reachable: True
❌ key valid: False
   models available: 47
   gateway reachable; key invalid or expired
```

## Library

```python
from near_iron_claw import NearAIClient, Settings

with NearAIClient(Settings.load()) as client:
    print(client.list_models())
    print(client.chat([{"role": "user", "content": "ping"}], max_tokens=16))

    for delta in client.stream_chat([{"role": "user", "content": "count to 3"}]):
        print(delta, end="", flush=True)
```

Typed errors let you handle failures precisely:

```python
from near_iron_claw import AuthError, RateLimitError, APIConnectionError, NearAIError

try:
    client.chat([{"role": "user", "content": "hi"}])
except AuthError:        # 401/403 — bad or expired key
    ...
except RateLimitError:   # 429
    ...
except APIConnectionError:  # network/DNS/TLS/timeout
    ...
except NearAIError:      # catch-all base class
    ...
```

## Develop

```bash
pytest                    # fast, fully offline (mocked HTTP), no API key needed
pytest --cov=near_iron_claw --cov-report=term-missing
pytest --run-live         # optional: hits the real gateway; skipped without a valid key
ruff check .              # lint
```

Tests use `httpx.MockTransport`, so the whole suite runs with **no network and no key**.
The optional live smoke test (`tests/test_live_smoke.py`) is deselected by default and only
runs with `--run-live` (or `RUN_LIVE=1`) when a non-placeholder key is configured.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs ruff + pytest on Python
3.9 / 3.11 / 3.12 for every push and PR.

## Swapping models

```bash
near-iron-claw models        # list slugs
# then set LLM_MODEL in .env, or per call:
near-iron-claw chat "hi" -m openai/gpt-5.5
```

## Project layout

```
src/near_iron_claw/
  config.py    Settings loader (.env + env), secret redaction
  errors.py    typed exception hierarchy
  client.py    NearAIClient — list_models, chat, stream_chat, verify
  cli.py       argparse CLI (config / models / chat / verify, --json)
tests/         offline mocked suite + optional live smoke test
```

## License

MIT — see [`pyproject.toml`](pyproject.toml).
