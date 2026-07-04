// near-iron-claw — Supabase Edge Function `logs`.
// Returns the most recent upstream attempt logs from `request_logs` (RLS-locked;
// readable only here via the service role). Surfaces failures like the NEAR AI 401
// so the operator can see exactly what each provider returned.
//
// verify_jwt is enabled: callers present a valid Supabase JWT (Vercel forwards the
// anon key). Read-only — no secrets (api_key columns are never selected).
import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "GET") return json({ error: "method not allowed" }, 405);

  const url = new URL(req.url);
  const rawLimit = parseInt(url.searchParams.get("limit") ?? "50", 10);
  const limit = Number.isFinite(rawLimit) ? Math.min(Math.max(rawLimit, 1), 200) : 50;

  const cols = "id,created_at,session_id,provider,model,http_status,ok,latency_ms,degraded,error";
  const res = await fetch(
    `${SUPABASE_URL}/rest/v1/request_logs?select=${cols}&order=created_at.desc&limit=${limit}`,
    {
      headers: {
        apikey: SERVICE_ROLE,
        Authorization: `Bearer ${SERVICE_ROLE}`,
      },
    },
  );
  if (!res.ok) return json({ error: "failed to read request_logs" }, 500);
  const logs = await res.json();
  return json({ count: logs.length, logs });
});
