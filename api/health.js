// near-iron-claw — Vercel Function `/api/health`.
// Lightweight readiness probe for the middleware chain: confirms this function is
// live and reports whether the Supabase backend URL is configured/reachable.

const SUPABASE_FUNCTION_URL =
  process.env.SUPABASE_FUNCTION_URL ||
  "https://duesorupitzmjubbylxg.supabase.co/functions/v1/chat";

module.exports = async (req, res) => {
  res.setHeader("Content-Type", "application/json");
  let backend = "unknown";
  try {
    // OPTIONS is unauthenticated (CORS preflight) — proves the backend is up
    // without needing a token.
    const r = await fetch(SUPABASE_FUNCTION_URL, { method: "OPTIONS" });
    backend = r.ok ? "reachable" : `http_${r.status}`;
  } catch (e) {
    backend = `unreachable: ${e.message}`;
  }
  res.status(200).send(
    JSON.stringify({ status: "ok", service: "near-iron-claw-web", backend }),
  );
};
