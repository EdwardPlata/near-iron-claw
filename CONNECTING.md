# Connecting near-iron-claw to NEAR AI Cloud (hosted IronClaw)

This project connects to the **hosted** NEAR AI Cloud endpoint — no local IronClaw build.
NEAR AI Cloud is an **OpenAI-compatible** gateway, so any OpenAI-style SDK or IronClaw's
`openai_compatible` backend can talk to it.

## Endpoint

| | |
|---|---|
| Gateway base URL | `https://cloud-api.near.ai/v1` |
| Auth | `Authorization: Bearer <LLM_API_KEY>` |
| Dashboard (get/rotate keys) | https://cloud.near.ai |
| Model list | `GET /v1/models` (public) |

> The old NEAR AI Developer Hub / Completions API at `api.near.ai` was **retired 2025-10-31**
> (returns HTTP 410). Use `cloud-api.near.ai` only.

## Configuration

All config lives in `.env` (git-ignored). Copy `.env.example` → `.env` and set a valid key.

| Var | Meaning |
|-----|---------|
| `LLM_BACKEND=openai_compatible` | IronClaw backend selector |
| `LLM_BASE_URL` | Gateway URL above |
| `LLM_API_KEY` | Your NEAR AI Cloud key (`sk-agent-…`) |
| `LLM_MODEL` | A slug from `GET /v1/models` (default `anthropic/claude-sonnet-4-6`) |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | Same values, so a plain OpenAI SDK works unchanged |
| `NEAR_AI_API_KEY` | Alias for tools expecting a NEAR-named var |

### Swapping models
List available slugs, then set `LLM_MODEL`:
```bash
curl -s https://cloud-api.near.ai/v1/models | jq -r '.data[].id'
```
Examples: `anthropic/claude-opus-4-7`, `openai/gpt-5.5`, `deepseek/deepseek-v3.2`,
`qwen/qwen3.7-max`, `google/gemini-3.5-flash`.

## Verify the connection

`GET /v1/models` is **public** and does NOT prove your key works — you must hit
`/v1/chat/completions`, which requires a valid key:

```bash
set -a; . ./.env; set +a
curl -s https://cloud-api.near.ai/v1/chat/completions \
  -H "Authorization: Bearer $LLM_API_KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"$LLM_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":16}" | jq .
```

- ✅ A JSON `choices[0].message.content` → the connection works.
- ❌ `401 {"error":{"type":"invalid_api_key"}}` → key is invalid/expired; get a new one at
  https://cloud.near.ai and update `.env`.

> ⚠️ **Current status:** the key committed at setup (`sk-agent-5f854c…`) returns **401
> Invalid or expired** on `/chat/completions`. Replace it with a valid dashboard key before
> running via the app.
