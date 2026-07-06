// Shared runtime helpers for the near-iron-claw Supabase edge functions.
// Imported by both `chat` and `logs` via `../_shared/runtime.ts`.

export const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
export const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const CORS_BASE = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

/** CORS headers for a function, merging the shared base with its allowed methods. */
export function makeCors(methods: string): Record<string, string> {
  return { ...CORS_BASE, "Access-Control-Allow-Methods": methods };
}

/** JSON response with the given CORS headers. */
export function json(cors: Record<string, string>, body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

/** Standard CORS preflight response. */
export function handleOptions(cors: Record<string, string>): Response {
  return new Response("ok", { headers: cors });
}

/** PostgREST call with the service role (bypasses RLS). */
export function db(path: string, init: RequestInit = {}): Promise<Response> {
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
