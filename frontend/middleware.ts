/**
 * Vercel Edge Middleware: proxy /api/* → Railway (fixes 404 when Node api/[...slug] is not invoked on Vite deploys).
 * Requires RAILWAY_API_BASE_URL in Vercel env. In dashboard, enable this var for Edge if your UI offers it.
 */
export const config = {
  matcher: "/api/:path*",
};

export default async function middleware(request: Request): Promise<Response> {
  const base = process.env.RAILWAY_API_BASE_URL?.replace(/\/$/, "");
  if (!base) {
    return new Response(
      JSON.stringify({
        error: "RAILWAY_API_BASE_URL is not set",
        hint: "Vercel → Project → Settings → Environment Variables → Production → add RAILWAY_API_BASE_URL. Enable for Edge if available. Redeploy.",
      }),
      { status: 503, headers: { "content-type": "application/json; charset=utf-8" } }
    );
  }

  const incoming = new URL(request.url);
  const targetUrl = `${base}${incoming.pathname}${incoming.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    const lk = key.toLowerCase();
    if (lk === "host" || lk === "connection") return;
    headers.set(key, value);
  });

  const method = request.method;
  const init: RequestInit = {
    method,
    headers,
    redirect: "manual",
  };

  if (method !== "GET" && method !== "HEAD") {
    init.body = request.body;
  }

  return fetch(targetUrl, init);
}
