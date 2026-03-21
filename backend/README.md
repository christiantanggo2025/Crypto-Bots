# Crypto Bot – Backend (FastAPI)

This is a **Python** project. There is no `package.json` here.

## Run the API server

With your virtualenv activated (e.g. `venv`):

```bash
uvicorn app.main:app --reload
```

Runs at **http://127.0.0.1:8000** by default.

## Run the frontend

From the project root:

```bash
cd frontend
npm install
npm run dev
```

Frontend (Vite) runs at **http://localhost:5173** and talks to the backend API.

## Deploy (Railway + Vercel)

See **[DEPLOY.md](../DEPLOY.md)** in the repo root for 24/7 hosting: API on Railway, UI on Vercel, with `VITE_API_BASE_URL` and optional data volume.
