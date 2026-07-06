// near-iron-claw — Vercel Function `/api/chat` (frontend middleware layer).
//
// Middleware chain:  browser → THIS function → Supabase edge fn → NEAR AI Cloud.
//
// Validates the request and forwards it to the Supabase `chat` edge function. The
// NEAR AI credential is never here — it lives only in Supabase. Shared config +
// forwarding live in ./_supabase.js.

const { functionUrl, readJsonBody, relayToSupabase, methodNotAllowed } = require("./_supabase");

module.exports = async (req, res) => {
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "POST") return methodNotAllowed(res);

  let payload;
  try {
    payload = await readJsonBody(req);
  } catch (e) {
    res.status(400).send(JSON.stringify({ error: e.message }));
    return;
  }

  const hasPrompt = typeof payload.prompt === "string" && payload.prompt.trim().length > 0;
  const hasMessages = Array.isArray(payload.messages) && payload.messages.length > 0;
  if (!hasPrompt && !hasMessages) {
    res.status(400).send(JSON.stringify({ error: "provide `prompt` or `messages`" }));
    return;
  }

  await relayToSupabase(res, functionUrl("chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
};
