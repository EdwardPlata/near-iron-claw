// near-iron-claw — Vercel Function `/api/logs` (frontend middleware layer).
//
// Middleware chain:  browser → THIS function → Supabase `logs` edge fn → request_logs.
//
// Read-only proxy that surfaces recent upstream attempt logs (including provider
// failures like the NEAR AI 401). No secrets pass through — the anon key it uses
// is public-safe and the backend never returns api_key columns.

const SUPABASE_LOGS_URL =
  process.env.SUPABASE_LOGS_URL ||
  "https://duesorupitzmjubbylxg.supabase.co/functions/v1/logs";

const SUPABASE_ANON_KEY =
  process.env.SUPABASE_ANON_KEY ||
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR1ZXNvcnVwaXR6bWp1YmJ5bHhnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODMxMTcwMDIsImV4cCI6MjA5ODY5MzAwMn0.tZCep8kG-Ftjb2_uVubvUOFV3NxmNfMl4YEcsMWFwz4";

module.exports = async (req, res) => {
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "GET") {
    res.status(405).send(JSON.stringify({ error: "method not allowed" }));
    return;
  }
  // Pass through a bounded ?limit= (default 25).
  const raw = parseInt((req.query && req.query.limit) || "25", 10);
  const limit = Number.isFinite(raw) ? Math.min(Math.max(raw, 1), 200) : 25;
  try {
    const upstream = await fetch(`${SUPABASE_LOGS_URL}?limit=${limit}`, {
      headers: { Authorization: `Bearer ${SUPABASE_ANON_KEY}` },
    });
    const text = await upstream.text();
    res.status(upstream.status).send(text);
  } catch (e) {
    res.status(502).send(JSON.stringify({ error: `backend unreachable: ${e.message}` }));
  }
};
