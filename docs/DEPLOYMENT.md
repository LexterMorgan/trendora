# Deployment Guide (M34)

Reference guide for running Trendora locally and deploying it on free-tier
hosting when you are ready. Nothing here is automatically applied; the Docker
and Render templates are optional. Actual deployment is a future action.

Two pieces:

- **Backend** — FastAPI (`src/trendora/`), talks to PostgreSQL (Supabase) and the
  YouTube/Meta/AI providers.
- **Frontend** — Next.js App Router (`web/`), proxies same-origin `/api/*`
  requests to the backend via `TRENDORA_API_BASE_URL`.

---

## A. Local development setup

### Prerequisites

- Python 3.12 (the project `.venv` is CPython 3.12.14).
- Node.js 20+ and npm (for `web/`).
- A PostgreSQL connection string (the existing Supabase project is fine).
- Optional: a YouTube Data API key and an OpenAI-compatible AI provider key.

### Backend

```bash
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example.backend .env      # then fill in real values
alembic upgrade head              # apply schema (including research_reports)
uvicorn trendora.api.app:create_app --factory --reload --port 8000
```

Backend: <http://localhost:8000> (OpenAPI docs at `/docs`).

### Frontend

```bash
cd web
npm install
cp ../.env.example.frontend .env.local   # set TRENDORA_API_BASE_URL
npm run dev
```

Frontend: <http://localhost:3000>.

### Security notes (local)

- `.env` and `.env.local` are gitignored. Never commit real secrets.
- The API has **no authentication**; keep it bound to localhost during local
  development and do not expose port 8000 publicly without a proxy and auth.

---

## B. Future deployment options

### Option 1 — Vercel (frontend only)

1. Push the repository to GitHub.
2. In Vercel: **Add New → Project → Import** the repo; Next.js is detected
   automatically (zero config).
3. Set the frontend root directory to `web/`.
4. Environment variable: `TRENDORA_API_BASE_URL` = your backend URL.
5. Deploy. Pushes to the default branch auto-deploy.

Vercel's free tier requires no credit card. The backend still needs a host
(below) or you can point the frontend at a local backend for testing.

### Option 2 — Render (backend, optional)

1. Sign up at <https://render.com> (free tier, no credit card for the basic
   web service).
2. **New → Web Service**, connect the GitHub repo.
3. Environment: Python. Build: `pip install -e .`. Start:
   `uvicorn trendora.api.app:create_app --factory --host 0.0.0.0 --port $PORT`.
4. Set environment variables (`DATABASE_URL`, `YOUTUBE_API_KEY`,
   `TRENDORA_AI_*`) in the Render dashboard.
5. Keep using the existing Supabase database via `DATABASE_URL`.

Free-tier caveats: limited monthly compute hours, services spin down when idle,
and cold starts add latency. Verify current limits before relying on it.

### Option 3 — Self-hosted VPS (DigitalOcean / AWS EC2)

1. Provision an Ubuntu server (paid, ~$5+/month).
2. **Firewall**: allow only 22 (SSH), 80/443 (HTTP/HTTPS). Do **not** expose
   8000/3000 directly to the internet.
3. Install Docker and run the backend container:
   `docker build -t trendora-api . && docker run --env-file .env -p 127.0.0.1:8000:8000 trendora-api`.
4. Run the frontend (`npm run build && npm start`) behind the same host.
5. **Reverse proxy + HTTPS**: put Nginx in front, terminate TLS with Let's
   Encrypt (`certbot`). This is required before any public exposure — plain
   HTTP sends credentials and report payloads in the clear.
6. Set environment variables via an `.env` file mounted into the containers.

---

## C. Container reference

Optional. See `Dockerfile` (backend image) and `docker-compose.yml` (local
orchestration). The compose file uses the external Supabase database; it does
not start a local PostgreSQL.

```bash
docker build -t trendora-api .
docker run --env-file .env -p 8000:8000 trendora-api
# or
docker compose up --build
```

---

## D. Environment variables

| File | Purpose |
| --- | --- |
| `.env.example.backend` | Backend template: `DATABASE_URL`, `YOUTUBE_API_KEY`, `META_*`, `TRENDORA_AI_*` |
| `.env.example.frontend` | Frontend template: `TRENDORA_API_BASE_URL` |

Never commit the populated `.env` / `.env.local`.

---

## Risks

- **No authentication.** Every endpoint is public once deployed. Add an auth
  layer or keep the service private until that exists.
- **Provider quotas.** YouTube Data API quota and AI provider credits are
  billed/limited per account; a public endpoint can be abused.
- **Free-tier limits.** Render/Vercel free tiers have compute/hour and cold-start
  constraints; evaluate against real usage.
- **Database exposure.** The Supabase `DATABASE_URL` is a full-access credential;
  treat it as a secret and rotate if leaked.
