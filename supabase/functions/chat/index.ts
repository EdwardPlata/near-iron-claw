// near-iron-claw — Supabase Edge Function `chat` (backend middleware layer).
//
// Middleware chain:  browser → Vercel /api/chat → THIS function → LLM providers.
//
// Responsibilities:
//   * hold provider credentials server-side (read from the RLS-locked `app_config`
//     row via the auto-injected service role — never exposed to the browser),
//   * try an ORDERED provider fallback chain (primary NEAR AI + any configured
//     fallbacks) until one succeeds,
//   * LOG every attempt (success or failure, e.g. the NEAR AI 401) to
//     `request_logs` for observability via the /logs endpoint,
//   * DEGRADE GRACEFULLY: if no provider answers, return a clear 200 echo instead
//     of a hard error so the pipeline stays demonstrable,
//   * persist each turn to `sessions` / `messages` (best-effort).
//
// verify_jwt is enabled: callers present a valid Supabase JWT (Vercel forwards
// the anon key).
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { db, json as _json, makeCors } from "../_shared/runtime.ts";

const CORS = makeCors("POST, OPTIONS");
const json = (body: unknown, status = 200): Response => _json(CORS, body, status);

interface ChatMessage {
  role: string;
  content: string;
}

interface Provider {
  name: string;
  base_url: string;
  api_key: string;
  model?: string;
}

interface Attempt {
  provider: string;
  model: string;
  http_status: number | null;
  ok: boolean;
  latency_ms: number;
  error: string | null;
}

async function logAttempt(a: Attempt, sessionId: string | null, degraded = false): Promise<void> {
  try {
    await db("request_logs", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        provider: a.provider,
        model: a.model,
        http_status: a.http_status,
        ok: a.ok,
        latency_ms: a.latency_ms,
        degraded,
        error: a.error,
      }),
    });
  } catch (_) {
    // logging must never break the request
  }
}

// Call one OpenAI-compatible provider; returns the reply or throws with detail.
async function callProvider(
  p: Provider,
  messages: ChatMessage[],
  model: string,
  maxTokens: number,
  temperature: number | undefined,
): Promise<{ ok: boolean; status: number | null; reply?: string; error?: string }> {
  let res: Response;
  try {
    res = await fetch(`${p.base_url.replace(/\/$/, "")}/chat/completions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${p.api_key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages,
        max_tokens: maxTokens,
        ...(temperature !== undefined ? { temperature } : {}),
      }),
    });
  } catch (e) {
    return { ok: false, status: null, error: `unreachable: ${e}` };
  }
  const text = await res.text();
  if (!res.ok) {
    const authFail = res.status === 401 || res.status === 403;
    return {
      ok: false,
      status: res.status,
      error: (authFail ? "key invalid or expired: " : `http ${res.status}: `) + text.slice(0, 200),
    };
  }
  try {
    const data = JSON.parse(text);
    const reply = data?.choices?.[0]?.message?.content;
    if (reply == null) return { ok: false, status: res.status, error: "unexpected completion shape" };
    return { ok: true, status: res.status, reply };
  } catch {
    return { ok: false, status: res.status, error: "non-JSON body" };
  }
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);

  let payload: Record<string, unknown>;
  try {
    payload = await req.json();
  } catch {
    return json({ error: "invalid JSON body" }, 400);
  }

  const prompt = String(payload.prompt ?? "").trim();
  const system = payload.system ? String(payload.system) : null;
  const provided = Array.isArray(payload.messages) ? (payload.messages as ChatMessage[]) : null;
  let sessionId = (payload.session_id as string | null) ?? null;
  const maxTokens = typeof payload.max_tokens === "number" ? payload.max_tokens : 512;
  const temperature = typeof payload.temperature === "number" ? payload.temperature : undefined;

  if (!provided && !prompt) return json({ error: "provide `prompt` or `messages`" }, 400);

  // Load server-side config (service role bypasses RLS).
  const cfgRes = await db(
    "app_config?id=eq.1&select=llm_base_url,llm_api_key,llm_model,fallback_providers",
  );
  if (!cfgRes.ok) return json({ error: "failed to read app_config" }, 500);
  const cfg = (await cfgRes.json())[0] ?? {};

  const messages: ChatMessage[] = provided ?? [
    ...(system ? [{ role: "system", content: system }] : []),
    { role: "user", content: prompt },
  ];

  // Build the ordered provider chain: primary (NEAR AI) + configured fallbacks.
  const chain: Provider[] = [];
  if (cfg.llm_api_key) {
    chain.push({
      name: "near-ai",
      base_url: cfg.llm_base_url ?? "https://cloud-api.near.ai/v1",
      api_key: cfg.llm_api_key,
      model: cfg.llm_model,
    });
  }
  for (const p of (cfg.fallback_providers ?? []) as Provider[]) {
    if (p?.base_url && p?.api_key) chain.push(p);
  }

  // Ensure we have a session to attach logs/messages to.
  if (!sessionId) {
    try {
      const s = await db("sessions", {
        method: "POST",
        headers: { Prefer: "return=representation" },
        body: JSON.stringify({ title: (prompt || "chat").slice(0, 60) }),
      });
      if (s.ok) sessionId = (await s.json())[0]?.id ?? null;
    } catch (_) { /* best-effort */ }
  }

  const attempts: Attempt[] = [];
  const requestedModel = payload.model ? String(payload.model) : null;

  // Try each provider in order, logging every attempt.
  for (const p of chain) {
    const model = requestedModel || p.model || "anthropic/claude-sonnet-4-6";
    const started = Date.now();
    const r = await callProvider(p, messages, model, maxTokens, temperature);
    const attempt: Attempt = {
      provider: p.name,
      model,
      http_status: r.status,
      ok: r.ok,
      latency_ms: Date.now() - started,
      error: r.error ?? null,
    };
    attempts.push(attempt);
    await logAttempt(attempt, sessionId);

    if (r.ok && r.reply != null) {
      await persist(sessionId, provided, prompt, r.reply, model);
      return json({ reply: r.reply, model, provider: p.name, session_id: sessionId, attempts });
    }
  }

  // No provider succeeded (or none configured with a key) → degrade gracefully.
  const lastError = attempts.length ? attempts[attempts.length - 1].error : "no provider configured with an api_key";
  const degradedModel = "degraded-echo";
  const reply =
    "⚠️ Degraded mode — no live LLM provider answered " +
    `(${attempts.length} attempt${attempts.length === 1 ? "" : "s"}; last error: ${lastError}). ` +
    "Set a valid key in app_config.llm_api_key or add a working provider to " +
    "app_config.fallback_providers. Echoing your message so the full pipeline is verifiable:\n\n" +
    (provided ? String(provided[provided.length - 1]?.content ?? "") : prompt);

  await logAttempt(
    { provider: "degraded-echo", model: degradedModel, http_status: 200, ok: true, latency_ms: 0, error: lastError },
    sessionId,
    true,
  );
  await persist(sessionId, provided, prompt, reply, degradedModel);

  return json({
    reply,
    model: degradedModel,
    provider: "degraded-echo",
    degraded: true,
    session_id: sessionId,
    attempts,
  });
});

// Persist the user + assistant turn (best-effort — never fail the request on logging).
async function persist(
  sessionId: string | null,
  provided: ChatMessage[] | null,
  prompt: string,
  reply: string,
  model: string,
): Promise<void> {
  if (!sessionId) return;
  try {
    const last = provided ? provided[provided.length - 1] : { role: "user", content: prompt };
    await db("messages", {
      method: "POST",
      body: JSON.stringify([
        { session_id: sessionId, role: last.role || "user", content: String(last.content), model },
        { session_id: sessionId, role: "assistant", content: reply, model },
      ]),
    });
  } catch (_) {
    // best-effort
  }
}
