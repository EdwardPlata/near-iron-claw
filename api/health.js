// near-iron-claw — Vercel Function `/api/health`.
// Lightweight readiness probe: confirms this function is live and reports whether
// the Supabase backend is reachable. Shared config lives in ./_supabase.js.

const { functionUrl } = require("./_supabase");

module.exports = async (req, res) => {
  res.setHeader("Content-Type", "application/json");
  let backend = "unknown";
  try {
    // OPTIONS is unauthenticated (CORS preflight) — proves the backend is up
    // without needing a token.
    const r = await fetch(functionUrl("chat"), { method: "OPTIONS" });
    backend = r.ok ? "reachable" : `http_${r.status}`;
  } catch (e) {
    backend = `unreachable: ${e.message}`;
  }
  res.status(200).send(JSON.stringify({ status: "ok", service: "near-iron-claw-web", backend }));
};
