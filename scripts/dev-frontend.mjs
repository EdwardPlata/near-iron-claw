// Local dev server for the near-iron-claw frontend (zero dependencies, Node 18+).
//
// Serves the static UI in web/ AND runs the Vercel functions in api/*.js locally,
// so /api/chat, /api/logs, /api/health work exactly as they do on Vercel — they
// forward to the deployed Supabase backend. This is the local equivalent of
// `vercel dev` without needing the Vercel CLI.
//
//   node scripts/dev-frontend.mjs           # http://localhost:3000
//   PORT=4000 node scripts/dev-frontend.mjs
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const WEB = join(ROOT, "web");
const PORT = Number(process.env.PORT) || 3000;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
};

// Give the Node ServerResponse the small helper surface the Vercel functions expect.
function vercelRes(res) {
  res.status = (code) => {
    res.statusCode = code;
    return res;
  };
  res.send = (body) => res.end(body);
  res.json = (obj) => {
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify(obj));
  };
  return res;
}

const require = createRequire(import.meta.url);
const handlers = {
  "/api/chat": require(join(ROOT, "api", "chat.js")),
  "/api/logs": require(join(ROOT, "api", "logs.js")),
  "/api/health": require(join(ROOT, "api", "health.js")),
};

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const handler = handlers[url.pathname];
  if (handler) {
    req.query = Object.fromEntries(url.searchParams); // Vercel populates req.query
    try {
      await handler(req, vercelRes(res));
    } catch (err) {
      res.statusCode = 500;
      res.end(JSON.stringify({ error: String(err && err.message ? err.message : err) }));
    }
    return;
  }
  // Static files from web/
  const rel = url.pathname === "/" ? "/index.html" : url.pathname;
  try {
    const data = await readFile(join(WEB, rel));
    res.setHeader("content-type", MIME[extname(rel)] || "application/octet-stream");
    res.end(data);
  } catch {
    res.statusCode = 404;
    res.end("not found");
  }
});

server.listen(PORT, () => {
  console.log(`near-iron-claw frontend → http://localhost:${PORT}`);
  console.log("  /api/chat, /api/logs, /api/health run locally (forward to Supabase).");
});
