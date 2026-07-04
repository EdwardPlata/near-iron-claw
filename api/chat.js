// near-iron-claw — Vercel Function `/api/chat` (frontend middleware layer).
//
// Middleware chain:  browser → THIS function → Supabase edge fn → NEAR AI Cloud.
//
// This layer validates the request and forwards it to the Supabase `chat` edge
// function using the (public-safe) Supabase anon key. The NEAR AI credential is
// never present here — it lives only in Supabase. Zero runtime dependencies.
//
// SUPABASE_FUNCTION_URL / SUPABASE_ANON_KEY may be overridden via Vercel env
// vars; the embedded fallbacks are publishable values and safe to ship.

const SUPABASE_FUNCTION_URL =
  process.env.SUPABASE_FUNCTION_URL ||
  "https://duesorupitzmjubbylxg.supabase.co/functions/v1/chat";

const SUPABASE_ANON_KEY =
  process.env.SUPABASE_ANON_KEY ||
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR1ZXNvcnVwaXR6bWp1YmJ5bHhnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODMxMTcwMDIsImV4cCI6MjA5ODY5MzAwMn0.tZCep8kG-Ftjb2_uVubvUOFV3NxmNfMl4YEcsMWFwz4";

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => {
      data += chunk;
      if (data.length > 1_000_000) reject(new Error("payload too large")); // 1MB guard
    });
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

module.exports = async (req, res) => {
  res.setHeader("Content-Type", "application/json");

  if (req.method !== "POST") {
    res.status(405).send(JSON.stringify({ error: "method not allowed" }));
    return;
  }

  let payload;
  try {
    const raw = await readBody(req);
    payload = JSON.parse(raw || "{}");
  } catch (e) {
    res.status(400).send(JSON.stringify({ error: `invalid request body: ${e.message}` }));
    return;
  }

  const hasPrompt = typeof payload.prompt === "string" && payload.prompt.trim().length > 0;
  const hasMessages = Array.isArray(payload.messages) && payload.messages.length > 0;
  if (!hasPrompt && !hasMessages) {
    res.status(400).send(JSON.stringify({ error: "provide `prompt` or `messages`" }));
    return;
  }

  try {
    const upstream = await fetch(SUPABASE_FUNCTION_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const text = await upstream.text();
    res.status(upstream.status).send(text); // transparently relay backend status + body
  } catch (e) {
    res.status(502).send(JSON.stringify({ error: `backend unreachable: ${e.message}` }));
  }
};
