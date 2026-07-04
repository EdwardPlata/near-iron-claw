# Deployment — the middleware chain

`near-iron-claw` ships as a three-layer middleware chain in front of NEAR AI Cloud.
Each layer is a middleware: it validates, adds a concern, and forwards.

```
Browser (web/index.html)
   │  POST /api/chat { prompt, session_id }
   ▼
Vercel Function  api/chat.js            ← middleware 1: input validation, edge proxy
   │  POST …/functions/v1/chat  (Bearer anon key)
   ▼
Supabase Edge Function  chat            ← middleware 2: holds the NEAR key, logs turns
   │  POST /v1/chat/completions (Bearer NEAR key, read from app_config)
   ▼
NEAR AI Cloud (OpenAI-compatible gateway)
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
| `web/index.html` | Chat UI (vanilla JS, no build) |
| `api/chat.js` | Vercel middleware → Supabase edge function |
| `api/health.js` | Readiness probe (checks backend reachability) |
| `supabase/functions/chat/index.ts` | Edge function → NEAR AI Cloud + persistence |
| `vercel.json` | `builds` (static `web/` + Node `api/`) + routes |
| DB: `app_config`, `sessions`, `messages` | Config + conversation persistence (all RLS-locked) |

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
| `POST /api/chat` (valid prompt) | 502 typed key-invalid error through full chain (expired key) |
| `POST /api/chat` (empty body) | 400 validation |
| `GET /api/chat` | 405 method guard |
| unauthenticated edge call | 401 (Supabase `verify_jwt`) |
| anon read of `app_config` / `messages` | `[]` (RLS locked) |
| Supabase security advisors | only INFO (intentional RLS-no-policy lock) |
