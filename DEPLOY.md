# Deployment — the middleware chain

`near-iron-claw` ships as a three-layer middleware chain in front of NEAR AI Cloud.
Each layer is a middleware: it validates, adds a concern, and forwards.

```
Browser (web/index.html)
   │  POST /api/chat { prompt, session_id }        GET /api/logs
   ▼                                                 ▼
Vercel Function  api/chat.js  /  api/logs.js      ← middleware 1: validation, edge proxy
   │  POST …/functions/v1/chat  (Bearer anon key)   GET …/functions/v1/logs
   ▼                                                 ▼
Supabase Edge Function  chat  /  logs             ← middleware 2: holds keys, logs + reads
   │  POST /v1/chat/completions (Bearer key from app_config, provider fallback chain)
   ▼
LLM providers — NEAR AI Cloud primary + optional fallbacks (all OpenAI-compatible)
```

### Resilience: fallback chain, logging, graceful degradation

- **Provider fallback** — `app_config.fallback_providers` is an ordered JSONB list of
  `{ name, base_url, api_key, model }`. The `chat` function tries the primary NEAR AI key
  first, then each fallback, until one answers. Add any OpenAI-compatible endpoint/key here
  and it "just works" — no redeploy needed.
- **Request logging** — every attempt (success or failure, incl. the NEAR AI 401) is written
  to `request_logs` and exposed read-only via `GET /api/logs` → Supabase `logs` function.
- **Graceful degradation** — if no provider answers, `chat` returns HTTP **200** with
  `degraded: true` and an echo of the message (plus the `attempts` detail) instead of a hard
  error, so the pipeline stays demonstrable with no valid key. The UI renders it as a warning.

### Add a working provider (no redeploy)

```sql
update public.app_config
set fallback_providers = '[
  {"name":"openai","base_url":"https://api.openai.com/v1","api_key":"sk-...","model":"gpt-4o-mini"}
]'::jsonb
where id = 1;
```

The **Python `near_iron_claw` client** (this repo's core) is the same middleware pattern as a
library/CLI; the edge function mirrors its error contract (`verify` / typed errors).

## Live URLs

| | |
|---|---|
| Frontend + Vercel middleware | https://near-iron-claw.vercel.app |
| Health probe | https://near-iron-claw.vercel.app/api/health |
| Supabase project | `duesorupitzmjubbylxg` (region `us-east-1`) |
| Supabase edge function | `https://duesorupitzmjubbylxg.supabase.co/functions/v1/chat` |

## Where the secret lives

The NEAR AI key is stored **only** in the Supabase `app_config` row, which has RLS enabled and
**no policies** — so only the edge function's auto-injected `service_role` can read it. It is
never in the browser, in Vercel, or in git. Verified:

- anon `GET /rest/v1/app_config` → `[]` (locked)
- `web/index.html` contains no key / service-role / anon JWT

The Supabase **anon key** and project URL embedded in `api/chat.js` are *publishable* values
(safe to ship) and can be overridden with Vercel env vars `SUPABASE_ANON_KEY` /
`SUPABASE_FUNCTION_URL`.

## Components

| Path | Role |
|------|------|
| `web/index.html` | Chat UI + logs panel (vanilla JS, no build) |
| `api/chat.js` | Vercel middleware → Supabase `chat` edge function |
| `api/logs.js` | Vercel middleware → Supabase `logs` edge function |
| `api/health.js` | Readiness probe (checks backend reachability) |
| `supabase/functions/chat/index.ts` | Edge fn → provider fallback chain + persistence + logging |
| `supabase/functions/logs/index.ts` | Edge fn → recent `request_logs` (no secrets) |
| `vercel.json` | `builds` (static `web/` + Node `api/`) + routes |
| DB: `app_config`, `sessions`, `messages`, `request_logs` | Config + conversation + attempt logs (all RLS-locked) |

## Run the frontend locally

`web/index.html` calls `/api/chat`, `/api/logs`, `/api/health`, which are **Vercel
functions** — so a plain static server (or `open index.html`) 404s on those. Two options:

```bash
# Option A — zero-dependency dev server (serves web/ + runs api/*.js locally):
node scripts/dev-frontend.mjs          # → http://localhost:3000   (PORT=4000 to change)

# Option B — the Vercel CLI emulator:
vercel dev --scope edwardplatas-projects
```

Both run the middleware functions locally and forward to the **deployed** Supabase backend
(no local Supabase needed). Chat shows the degraded reply until a valid NEAR AI key is set in
`app_config` (see below).

## Redeploy

```bash
# Frontend + Vercel middleware
vercel deploy --prod --yes --scope edwardplatas-projects

# Supabase edge function (or via the Supabase MCP deploy_edge_function tool)
supabase functions deploy chat --project-ref duesorupitzmjubbylxg
```

## Set / rotate the NEAR AI key

The committed key returns 401 on `/chat/completions` (chat surfaces a clean
`NEAR AI key invalid or expired` 502 through every layer). Drop a valid key from
<https://cloud.near.ai> into the config row:

```sql
update public.app_config set llm_api_key = 'sk-agent-…', updated_at = now() where id = 1;
```

## Verified end-to-end

| Check | Result |
|-------|--------|
| `GET /` | 200 (HTML) |
| `GET /api/health` | 200 `{ backend: "reachable" }` |
| `POST /api/chat` (valid prompt) | 200 graceful `degraded` echo (expired key) + attempt logged |
| `GET /api/logs` | 200 — shows the NEAR AI 401 + degraded-echo rows |
| `POST /api/chat` (empty body) | 400 validation |
| `GET /api/chat` / `POST /api/logs` | 405 method guard |
| unauthenticated edge call | 401 (Supabase `verify_jwt`) |
| anon read of `app_config` / `messages` | `[]` (RLS locked) |
| Supabase security advisors | only INFO (intentional RLS-no-policy lock) |
| `scripts/smoke.sh` | 8/8 passing |
