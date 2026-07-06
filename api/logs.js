// near-iron-claw — Vercel Function `/api/logs` (frontend middleware layer).
//
// Middleware chain:  browser → THIS function → Supabase `logs` edge fn → request_logs.
//
// Read-only proxy that surfaces recent upstream attempt logs. No secrets pass
// through. Shared config + forwarding live in ./_supabase.js.

const { functionUrl, relayToSupabase, methodNotAllowed } = require("./_supabase");

module.exports = async (req, res) => {
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "GET") return methodNotAllowed(res);

  // Pass through a bounded ?limit= (default 25).
  const raw = parseInt((req.query && req.query.limit) || "25", 10);
  const limit = Number.isFinite(raw) ? Math.min(Math.max(raw, 1), 200) : 25;

  await relayToSupabase(res, `${functionUrl("logs")}?limit=${limit}`);
};
