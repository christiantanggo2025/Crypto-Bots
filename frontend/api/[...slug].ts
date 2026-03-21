/**
 * Vercel serverless proxy: browser calls same-origin /api/* → Railway FastAPI.
 *
 * Set in Vercel → Environment Variables (Production):
 *   RAILWAY_API_BASE_URL=https://your-service.up.railway.app
 * (no trailing slash; no /api suffix)
 *
 * Leave VITE_API_BASE_URL unset to use this proxy (recommended).
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";

const HOP = new Set(["host", "connection", "transfer-encoding", "keep-alive"]);

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const base = process.env.RAILWAY_API_BASE_URL?.replace(/\/$/, "");
  if (!base) {
    res.status(503).json({
      error: "RAILWAY_API_BASE_URL is not set on Vercel",
      hint: "Vercel → Project → Settings → Environment Variables → add RAILWAY_API_BASE_URL = your Railway HTTPS URL (no trailing slash). Redeploy.",
    });
    return;
  }

  const incoming = new URL(req.url || "/", "https://placeholder.local");
  const targetUrl = `${base}${incoming.pathname}${incoming.search}`;

  const headers = new Headers();
  for (const [key, val] of Object.entries(req.headers)) {
    if (!val || HOP.has(key.toLowerCase())) continue;
    headers.set(key, Array.isArray(val) ? val.join(", ") : val);
  }

  const method = req.method || "GET";
  let body: string | Buffer | undefined;
  if (!["GET", "HEAD"].includes(method)) {
    if (typeof req.body === "string") body = req.body;
    else if (Buffer.isBuffer(req.body)) body = req.body;
    else if (req.body != null) body = JSON.stringify(req.body);
  }

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl, { method, headers, body });
  } catch (e) {
    res.status(502).json({
      error: "Proxy could not reach Railway",
      target: targetUrl,
      message: e instanceof Error ? e.message : String(e),
    });
    return;
  }

  const ct = upstream.headers.get("content-type");
  if (ct) res.setHeader("content-type", ct);
  const cd = upstream.headers.get("content-disposition");
  if (cd) res.setHeader("content-disposition", cd);

  res.status(upstream.status);
  const buf = Buffer.from(await upstream.arrayBuffer());
  res.send(buf);
}
