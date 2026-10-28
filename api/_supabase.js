// Shared config + helpers for the Vercel middleware functions (api/*.js).
//
// Single source of truth for the Supabase backend URL and the (public, publishable)
// anon key, plus the "forward to Supabase and relay status+body" logic that chat.js
// and logs.js both need. Overridable via env vars; the embedded fallbacks are
// publishable values and safe to ship.

const BASE_URL =
  process.env.SUPABASE_FUNCTION_BASE_URL ||
  "https://duesorupitzmjubbylxg.supabase.co/functions/v1";

const SUPABASE_ANON_KEY =
  process.env.SUPABASE_ANON_KEY ||
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR1ZXNvcnVwaXR6bWp1YmJ5bHhnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODMxMTcwMDIsImV4cCI6MjA5ODY5MzAwMn0.tZCep8kG-Ftjb2_uVubvUOFV3NxmNfMl4YEcsMWFwz4";

// Per-function full-URL overrides (backward-compatible with the documented env
// vars in DEPLOY.md / DOCS.md). A full override wins over the derived base URL.
const FULL_URL_OVERRIDES = {
  chat: process.env.SUPABASE_FUNCTION_URL,
  logs: process.env.SUPABASE_LOGS_URL,
};

// URL of a named Supabase edge function (e.g. functionUrl("chat")).
function functionUrl(name) {
  return FULL_URL_OVERRIDES[name] || `${BASE_URL}/${name}`;
}

// Read and JSON-parse the request body (bounded to guard against huge payloads).
function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => {
      data += chunk;
      if (data.length > 1_000_000) reject(new Error("invalid request body: payload too large")); // 1MB
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(data || "{}"));
      } catch (e) {
        reject(new Error(`invalid request body: ${e.message}`));
      }
    });
    req.on("error", reject);
  });
}

// Forward a request to a Supabase edge function with the anon key and relay its
// response status + body verbatim. On network failure, emit a 502.
async function relayToSupabase(res, upstreamUrl, init = {}) {
  try {
    const upstream = await fetch(upstreamUrl, {
      ...init,
      headers: { Authorization: `Bearer ${SUPABASE_ANON_KEY}`, ...(init.headers || {}) },
    });
    const text = await upstream.text();
    res.status(upstream.status).send(text);
  } catch (e) {
    res.status(502).send(JSON.stringify({ error: `backend unreachable: ${e.message}` }));
  }
}

function methodNotAllowed(res) {
  res.status(405).send(JSON.stringify({ error: "method not allowed" }));
}

module.exports = {
  SUPABASE_ANON_KEY,
  functionUrl,
  readJsonBody,
  relayToSupabase,
  methodNotAllowed,
};
