# Trendora — Research Workspace (web)

Next.js (App Router) + React + TypeScript frontend for the Trendora research
workflow. It is a consumer of the M15 research API; no research logic lives
here.

## Local development

Backend (Terminal 1, repository root):

```bash
source .venv/bin/activate
uvicorn trendora.api.app:create_app --factory --reload --port 8000
```

Frontend (Terminal 2, this directory):

```bash
cp .env.example .env.local   # set TRENDORA_API_BASE_URL if not default
npm install
npm run dev
```

Required environment variable (`web/.env.local`):

| Variable | Purpose | Example |
| --- | --- | --- |
| `TRENDORA_API_BASE_URL` | FastAPI backend base URL the server proxy forwards to | `http://127.0.0.1:8000` |

## Commands

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # eslint
npm run build       # production build
npm run dev         # local dev server
```

## How the frontend reaches the API

Browser → same-origin Next.js route handler (`app/api/research/route.ts`) →
`${TRENDORA_API_BASE_URL}/api/v1/research`. The proxy forwards the structured
request and passes through the backend status/body; it performs no research
logic and never exposes backend credentials.

## Vercel

Deployable as-is with Next.js defaults: root directory `web`, build command
`npm run build`, and the `TRENDORA_API_BASE_URL` environment variable set in
Vercel to the hosted FastAPI backend base URL.
