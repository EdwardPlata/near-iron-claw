// near-iron-claw — Supabase Edge Function `chat` (backend middleware layer).
//
// Middleware chain:  browser → Vercel /api/chat → THIS function → NEAR AI Cloud.
//
// Responsibilities:
//   * hold the NEAR AI key server-side (read from the RLS-locked `app_config`
//     row via the auto-injected service role — never exposed to the browser),
//   * proxy chat completions to the NEAR AI Cloud OpenAI-compatible gateway,
//   * persist each turn to `sessions` / `messages` (best-effort),
//   * return typed, JSON errors (mirrors the near_iron_claw Python client).
//
// verify_jwt is enabled: callers must present a valid Supabase JWT (the Vercel
// middleware forwards the anon key).
import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

// PostgREST call with the service role (bypasses RLS on app_config/messages).
function db(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: SERVICE_ROLE,
      Authorization: `Bearer ${SERVICE_ROLE}`,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
}

interface ChatMessage {
  role: string;
  content: string;
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

  if (!provided && !prompt) {
    return json({ error: "provide `prompt` or `messages`" }, 400);
  }

  // 1) Load server-side config (service role bypasses RLS).
  const cfgRes = await db("app_config?id=eq.1&select=llm_base_url,llm_api_key,llm_model");
  if (!cfgRes.ok) return json({ error: "failed to read app_config" }, 500);
  const cfg = (await cfgRes.json())[0];
  if (!cfg?.llm_api_key) {
    return json({ error: "LLM_API_KEY not configured in app_config" }, 503);
  }

  const model = payload.model ? String(payload.model) : cfg.llm_model;
  const messages: ChatMessage[] = provided ?? [
    ...(system ? [{ role: "system", content: system }] : []),
    { role: "user", content: prompt },
  ];

  // 2) Proxy to NEAR AI Cloud.
  let upstream: Response;
  try {
    upstream = await fetch(`${cfg.llm_base_url}/chat/completions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${cfg.llm_api_key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        messages,
        max_tokens: typeof payload.max_tokens === "number" ? payload.max_tokens : 512,
        ...(typeof payload.temperature === "number" ? { temperature: payload.temperature } : {}),
      }),
    });
  } catch (e) {
    return json({ error: `gateway unreachable: ${e}` }, 502);
  }

  const upstreamText = await upstream.text();
  if (!upstream.ok) {
    const authFail = upstream.status === 401 || upstream.status === 403;
    return json(
      {
        error: authFail
          ? "NEAR AI key invalid or expired — update app_config.llm_api_key"
          : `gateway error ${upstream.status}`,
        upstream_status: upstream.status,
        detail: upstreamText.slice(0, 300),
      },
      502,
    );
  }

  let data: { choices?: { message?: { content?: string } }[] };
  try {
    data = JSON.parse(upstreamText);
  } catch {
    return json({ error: "gateway returned a non-JSON body" }, 502);
  }
  const reply = data.choices?.[0]?.message?.content;
  if (reply == null) {
    return json({ error: "unexpected completion shape from gateway" }, 502);
  }

  // 3) Persist the turn (best-effort — never fail the request on a logging error).
  try {
    if (!sessionId) {
      const s = await db("sessions", {
        method: "POST",
        headers: { Prefer: "return=representation" },
        body: JSON.stringify({ title: (prompt || "chat").slice(0, 60) }),
      });
      if (s.ok) sessionId = (await s.json())[0]?.id ?? null;
    }
    if (sessionId) {
      const last = provided ? provided[provided.length - 1] : { role: "user", content: prompt };
      await db("messages", {
        method: "POST",
        body: JSON.stringify([
          { session_id: sessionId, role: last.role || "user", content: String(last.content), model },
          { session_id: sessionId, role: "assistant", content: reply, model },
        ]),
      });
    }
  } catch (_) {
    // logging is best-effort
  }

  return json({ reply, model, session_id: sessionId });
});
