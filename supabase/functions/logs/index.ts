// near-iron-claw — Supabase Edge Function `logs`.
// Returns the most recent upstream attempt logs from `request_logs` (RLS-locked;
// readable only here via the service role). Surfaces failures like the NEAR AI 401
// so the operator can see exactly what each provider returned.
//
// verify_jwt is enabled: callers present a valid Supabase JWT (Vercel forwards the
// anon key). Read-only — no secrets (api_key columns are never selected).
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { db, handleOptions, json as _json, makeCors } from "../_shared/runtime.ts";

const CORS = makeCors("GET, OPTIONS");
const json = (body: unknown, status = 200): Response => _json(CORS, body, status);

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") return handleOptions(CORS);
  if (req.method !== "GET") return json({ error: "method not allowed" }, 405);

  const url = new URL(req.url);
  const rawLimit = parseInt(url.searchParams.get("limit") ?? "50", 10);
  const limit = Number.isFinite(rawLimit) ? Math.min(Math.max(rawLimit, 1), 200) : 50;

  const cols = "id,created_at,session_id,provider,model,http_status,ok,latency_ms,degraded,error";
  const res = await db(`request_logs?select=${cols}&order=created_at.desc&limit=${limit}`);
  if (!res.ok) return json({ error: "failed to read request_logs" }, 500);
  const logs = await res.json();
  return json({ count: logs.length, logs });
});
