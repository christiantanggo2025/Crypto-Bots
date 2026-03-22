# Deploy Crypto Strategy Lab (Railway + Vercel)

Run the **FastAPI backend** on **Railway** (24/7 worker + API) and the **Vite/React frontend** on **Vercel**.

---

## 1. Railway — backend

1. Push this repo to GitHub (or connect Railway to your repo).
2. In [Railway](https://railway.app/) → **New Project** → **Deploy from GitHub** → select the repo.
3. **Important:** set **Root Directory** to `backend`  
   (Settings → Service → Root Directory → `backend`).
4. Railway will detect Python from `requirements.txt` and use the **Procfile** / `railway.toml` start command:
   - `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. After deploy, open **Settings → Networking → Generate Domain** (or add a custom domain).  
   Copy the public URL, e.g. `https://your-app-production-xxxx.up.railway.app`.

### Environment variables (Railway)

| Variable | Required | Description |
|----------|----------|-------------|
| *(none required for basic run)* | | CoinGecko works without key; optional keys in app Settings UI after deploy. |
| `CORS_ORIGINS` | Optional | Default `*` (all origins). For stricter CORS, set e.g. `https://your-app.vercel.app` |

### Persist paper state & settings (recommended for 24h runs)

Railway’s filesystem is **ephemeral** by default — restarts wipe `backend/data/`.

1. In the Railway service → **Volumes** → **Add volume**.
2. Mount path: **`/app/data`** (Nixpacks often uses `/app` as the app root; if paths differ, check deploy logs and align with `backend/data` on disk).
3. If the working directory is `backend`, the app writes to `./data` under that root — set the volume mount to the same absolute path where `data/` is created (see first deploy logs).

If you skip a volume, the lab still runs but state resets when the service restarts.

### Health check

- `GET /health` → `{"status":"ok"}` (configured in `railway.toml`).

---

## 2. Vercel — frontend

1. In [Vercel](https://vercel.com/) → **Add New** → **Project** → import the same Git repo.
2. **Root Directory:** `frontend`
3. **Framework preset:** Vite (or “Other” with build `npm run build`, output `dist`).
4. **Environment variables** (Production — required for the UI to talk to Railway):

| Name | Value |
|------|--------|
| **`RAILWAY_API_BASE_URL`** | **Required for same-origin `/api`.** Railway origin only: `https://your-app-production-xxxx.up.railway.app` (no trailing slash, no `/api`). Vercel **Edge Middleware** (`frontend/middleware.ts`) proxies `/api/*` to Railway. In Vercel → Env Vars, enable this variable for **Edge** if the UI shows that option. |
| `VITE_API_BASE_URL` | **Optional alternative.** Same URL as above — bakes the Railway origin into the JS bundle and calls Railway **directly** from the browser (needs CORS `*`, which we allow). Redeploy after every change. |

5. **Redeploy** after adding env vars. Open your **Vercel** URL on your phone; Overview should show **CLOUD WORKER LIVE** when Railway is cycling.

### Local production build test

```bash
cd frontend
echo VITE_API_BASE_URL=https://your-railway-url.up.railway.app > .env.production
npm run build
npm run preview
```

---

## 3. How it fits together

- **Vercel** serves static files from `frontend/dist`.
- The browser loads JS with `VITE_API_BASE_URL` baked in at build time → all API calls go to **Railway**.
- **Railway** runs Uvicorn + APScheduler; lab cycles keep running 24/7 as long as the service stays up.
- CORS is open (`*` by default) with `allow_credentials=False` so browsers accept cross-origin `fetch` from your Vercel domain.

---

## 4. Troubleshooting

| Issue | What to check |
|--------|----------------|
| UI shows “Cannot reach API” | Vercel → set **`RAILWAY_API_BASE_URL`** (recommended) or **`VITE_API_BASE_URL`** to your Railway `https://…` origin; **Redeploy**. |
| CORS errors | Set `CORS_ORIGINS` on Railway to your Vercel origin(s), comma-separated, or leave default `*`. |
| 502 / app won’t start | Railway logs; confirm Root Directory is `backend` and start command uses `$PORT`. |
| State resets | Add a volume for `data/` as above. |

---

## 5. Optional: single Railway service (API + static UI)

You can build the frontend into `frontend/dist` in a Docker/Railway build and let FastAPI serve it (see `main.py` static mount). That’s a different layout than Vercel; this guide uses the split **Railway API + Vercel UI** pattern for clarity and CDN hosting.
