# Deployment Guide (M34)

Trendora remains local. This guide covers local startup and optional future
deployment. Nothing here is automatically applied; the Docker and Render
templates are references. Hosting setup is a separate future action.

Two pieces:

- **Backend** — FastAPI (`src/trendora/`), talks to PostgreSQL (Supabase) and the
  YouTube/Meta/AI providers.
- **Frontend** — Next.js App Router (`web/`), proxies same-origin `/api/*`
  requests to the backend via `TRENDORA_API_BASE_URL`.

---

## A. Local startup with installed tools

### Prerequisites

- Python 3.12 (the project `.venv` is CPython 3.12.14).
- Node.js 22+ and npm (the Supabase SDK requires Node 22). Frontend tests also
  need an installed Node version with native TypeScript support.
- Existing installed dependencies in `.venv/` and `web/node_modules/`.
- For real protected workflows: an authorized, already migrated PostgreSQL
  database and matching Supabase Auth project with active local memberships.

### Backend

From the repository root in Terminal 1:

```bash
.venv/bin/python -m uvicorn trendora.api.app:create_app --factory \
  --host 127.0.0.1 --port 8000
```

Add `--reload` only when you are actively editing backend code; it is a
development convenience, not the default. In local development, startup does not
migrate the database: run Alembic explicitly against an approved target.

Backend: <http://127.0.0.1:8000>; public liveness probe: `/health`.

### Frontend

From the repository root in Terminal 2:

```bash
cd web
npm run dev -- --webpack --hostname 127.0.0.1 --port 3000
```

Frontend: <http://127.0.0.1:3000>. Keep existing private `.env` and
`web/.env.local` files intact. The example files list names and placeholders;
they are not working credentials. Configure missing values privately rather
than overwriting an existing environment file.
Use the Webpack path. Turbopack needs a native SWC binding that may be absent;
no compiler installation is required to build and run with Webpack.

### Stopping servers

Run each server in a foreground terminal and stop it with Ctrl+C in that
terminal. Do not use pattern-based process kills such as `pkill -f "next dev"`;
the pattern can match unrelated projects on the machine. Do not kill by a PID
recorded in an older note, because the PID may now belong to a different process.

### Separately managed dependencies

The public-web search container (SearXNG) and the optional AI router are
separate services you start and stop yourself. They are not part of this
application's process tree.

- If you use a container runtime such as Colima, stopping that instance stops
  every container in it, not only the search container. Do not stop or restart
  an instance you did not start.
- Restarting the search container or the AI router is outside this guide. If a
  run fails because one of them is down, report it rather than silently
  recreating it.

| Process | Variable names | Requirement |
| --- | --- | --- |
| Backend | `DATABASE_URL` | Required at startup, even for `/health`. A valid URL does not prove connectivity or migration state. |
| Backend authentication | `SUPABASE_URL` | Required for usable protected routes; match the frontend project. Verified JWT signing keys and an active local membership are also required. |
| Backend recovery | `TRENDORA_REPORT_RECOVERY_SIGNING_KEY` | Required for new source-bearing save recovery; dedicated, at least 32 UTF-8 bytes, stable across restarts and backend workers. |
| Frontend server | `TRENDORA_API_BASE_URL` | Set to `http://127.0.0.1:8000`; never expose database or backend signing credentials here. |
| Browser authentication | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public project URL and anon/publishable key. Never use a service-role key. |
| Selected research source | `YOUTUBE_API_KEY`; or `META_ACCESS_TOKEN` and `META_GRAPH_API_VERSION`; or `SEARXNG_URL` / `SERPER_API_KEY` | Configure only the chosen source. `TRENDORA_WEB_SEARCH_BACKEND` selects the public-web backend (`auto`/`serper`/`searxng`/`none`); `TRENDORA_WEB_SEARCH_ENABLED` toggles public web (default true). |
| Optional AI synthesis/content | `TRENDORA_AI_PROVIDER`, `TRENDORA_AI_MODEL`, `TRENDORA_AI_ENDPOINT_URL`, `TRENDORA_AI_API_KEY` | Complete generic provider configuration; endpoint must be the adapter's Chat Completions endpoint. Current UI requests preserve source excerpts when synthesis is unavailable. Legacy requests omitting the content-tools flag still require AI configuration. |

Use the same local origin for Supabase's Site URL and exact redirect allowlist:
`http://127.0.0.1:3000/accept-invite` and
`http://127.0.0.1:3000/reset-password`. Restart Next.js after changing public
environment variables.

The research form offers `public_web`. Two backends are supported; select one
explicitly with `TRENDORA_WEB_SEARCH_BACKEND` (`auto` | `serper` | `searxng` |
`none`, default `auto`). `auto` prefers a self-hosted SearXNG when
`SEARXNG_URL` is set, then Serper. A named backend never silently falls back to
a different (paid) provider. Self-hosted SearXNG is free and local; see
`deploy/searxng/README.md` for the official-image start/stop commands. This
source searches indexed titles/snippets. Its current adapter does not enforce
the selected search timeframe or provide verified publication dates; reports
label undated material as context. Collection dates never establish publication
within the requested window. Reading the full text of discovered pages is
deferred.

### Current Supabase configuration assessment

Read-only checks on 2026-10-07 found project `trendora`
(`ymzloduyggkcmapmiics`) ACTIVE_HEALTHY. Local frontend/backend URLs and the
database pooler project identifier match. The public key is accepted by Auth
settings, email authentication is enabled, and JWKS advertises ES256, which
the backend supports. An advertised key can be standby; the algorithm used
by an actual session remains unverified. Auth redirects are not exposed by
the available read-only tools, so the Site URL and callback allowlist above
still need dashboard confirmation.

Schema state is target-specific and must be checked, not assumed. The
authoritative schema is the set of Alembic revisions in `alembic/versions/`
(`0001` through `0008` at the time of writing). A target database is only ready
when its applied revision matches the intended one and its grants, row-level
security, membership rows, and auth settings match the deployment's needs.

Dated evidence: an earlier read-only inspection of one hosted project found that
project at revision `0002` with membership, planner, and expiry objects absent
and signup open. That observation describes that project at that moment. Do not
treat it as the current state of any database, including your own.

Any operation that changes schema, grants, memberships, or auth settings needs a
separately approved target and a backup strategy. See section F.

Configuration observations do not prove the protected application flow works
live. Verify the intended provider, model, and endpoint against your own private
configuration rather than a note in this file.

### Isolated acceptance versus live integrations

The maintained browser runner starts a real Next.js production server in a
private frontend copy. Fictional Supabase accounts and a shared Node in-memory
backend exercise research, save/recovery, saved-report reads and planner
import. It excludes environment files and generated output, allowlists child
environments, blocks outbound service requests, uses fresh browser storage,
and stops only its owned loopback services. It does not start FastAPI or
contact Supabase, 9router, research providers or a database.

With an already installed Playwright-compatible driver available:

```bash
cd web
TRENDORA_BROWSER_DRIVER=/absolute/path/to/installed/playwright npm run test:browser
```

The driver path is test tooling, not an application dependency or credential.
`TRENDORA_BROWSER_EXECUTABLE` optionally selects an already installed browser.
The runner builds with Webpack and an offline font fixture, and returns nonzero
when prerequisites or acceptance assertions fail. Its contract-only command
does not execute a browser.

Local acceptance also includes an isolated startup check with six passing
assertions and no failures or skips: a real FastAPI process serves `/health`
(200) and refuses protected research without authentication (401) without
database access; a real `next dev --webpack` server renders the workspace with
an isolated fictional login; the browser reaches the real Next proxy and the
real FastAPI backend and receives the useful missing-source error; a stopped
owned backend produces a private 502 with a readable retry failure; and the run
sends no external requests, planner mutations or uncaught browser errors. Dotenv,
database connections and outbound networking stay blocked throughout. Completed
disposable PostgreSQL verification is separate evidence (section F). These
checks exercise local development-server mode but do not prove the application's
Supabase connection, migration state, membership, live research quality or
9router compatibility. No dedicated 9router startup or configuration is
implemented here; it would use the generic AI variables above. Local acceptance
does not reactivate Supabase, migrate an application database or authorize
provider calls.

### Security notes (local)

- `.env` and `.env.local` are gitignored. Never commit real secrets.
- Business API routes require a verified Supabase access token and an active
  local membership. `/health` remains public. Keep development services on
  loopback; production still needs TLS and verified database privileges.

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
(below). A deployed frontend cannot reach a laptop's loopback backend:
`http://127.0.0.1:8000` on the visitor's machine is not your machine. Point the
frontend at a reachable backend URL instead.

### Option 2 — Render (backend, optional)

1. Sign up at <https://render.com> (free tier, no credit card for the basic
   web service).
2. **New → Web Service**, connect the GitHub repo.
3. Environment: Python. Build: `pip install -e .`. Start:
   `alembic upgrade head && uvicorn trendora.api.app:create_app --factory --host 0.0.0.0 --port $PORT`.
4. Set environment variables (`DATABASE_URL`, `YOUTUBE_API_KEY`,
   `TRENDORA_AI_*`) in the Render dashboard.
5. Keep using the existing Supabase database via `DATABASE_URL`.

Every Render boot runs `alembic upgrade head` before Uvicorn. Applying the same
revisions again is idempotent. A failed migration exits non-zero and stops the
boot, so the service never serves a stale schema.

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
docker run --env-file .env -p 127.0.0.1:8000:8000 trendora-api
# or
docker compose up --build
```

Publish to loopback only, as shown. The published Compose template in
`docker-compose.yml` maps `8000:8000`, which binds on every interface and would
expose the backend to your network. That template is unchanged by this guide;
either edit it yourself or run the loopback `docker run` form above. Treat a
container that mounts `.env` as holding your real credentials.

---

## D. Environment variables

| File | Purpose |
| --- | --- |
| `.env.example` | Backend and shared template; configure `DATABASE_URL`, `SUPABASE_URL`, and the selected source/AI credentials separately. |
| `web/.env.example` | Frontend template; configure `TRENDORA_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, and the public `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Never use a service-role key here. |

Never commit the populated `.env` / `.env.local`.

Fresh recovery after a failed save needs `TRENDORA_REPORT_RECOVERY_SIGNING_KEY`
on the backend only: a dedicated high-entropy key, at least 32 UTF-8 bytes,
kept stable across workers and restarts for the lifetime of issued receipts.
Do not reuse a provider credential or expose this key to the frontend. Without
it, generation and existing-key acknowledgment still work, but new
source-bearing recovery cannot establish a trusted deadline. Changing the key
invalidates outstanding receipts. Provisioning this secret and applying 0008
to the deployment database still require separate target approval. Disposable
verification does not complete either deployment action. No legacy expiry is
backfilled.

---

## E. Request limits and pending deployment checks

Inspected 2026-10-07. These are code limits and current public host documentation,
not evidence that an existing deployment has this configuration.

| Path | Application limit |
| --- | --- |
| Frontend report-generation proxy | 65,536 streamed request bytes; 180-second deadline for upstream fetch and full response reading, with client cancellation forwarded. The 180-second proxy deadline does not guarantee backend completion or backend-side cancellation. |
| Research interpretation (backend) | One shared monotonic deadline (`TRENDORA_AI_TIMEOUT_SECONDS`, default 30 s) governs the interpretation call and at most one malformed-output retry. The retry is skipped when remaining time is shorter than the failed attempt. In-flight I/O is cancellable at the deadline; JSON parsing, grounding validation, and cleanup are not strictly interrupted. |
| On-demand content (backend) | A separate request generates strategy and ideation for one saved, non-expired report. Strategy and ideation share their own `TRENDORA_AI_TIMEOUT_SECONDS` budget. Success appends a new completed report snapshot; failure leaves the source report unchanged. |
| Report save/recovery | 8,388,608 request bytes in browser, frontend proxy, and backend route. |
| Planner writes | 131,072 streamed request bytes in frontend proxy and backend route. |

The smallest limit on the deployed path wins. Vercel Functions currently cap
request and response payloads at 4.5 MB, below the application save cap. Fluid
compute on Hobby allows 300 seconds; the selected project/runtime settings must
be inspected before relying on that duration. [Vercel limits](https://vercel.com/docs/functions/limitations).

Do not assume a short fixed timeout bounds a whole report. AI request I/O is
bounded by the operation deadline described above; source requests, database
writes, and cold starts add time beyond it. Proxy cancellation bounds the
frontend wait; it does not prove backend execution or a database write stopped.
On-demand content is a separate request after the report is saved, so it does
not consume the research synthesis budget. Verify actual latency and
lost-response recovery on the intended host before release.

The optional Render Free template does not establish an operational cleanup
schedule. Free services sleep after 15 idle minutes and typically take about a
minute to wake, have an ephemeral filesystem, and cannot run one-off jobs or
attach persistent disks. Their 750 monthly instance hours are shared per
workspace. [Render Free limits](https://render.com/docs/free).

The manual cleanup entry point is
`python -m trendora.retention --database-env TRENDORA_RETENTION_DATABASE_URL`.
It uses only the explicitly named database variable, defaults to dry-run, and
requires `--apply` to commit deletion. Both modes connect to the supplied
database and need separate target/run approval. No scheduler is enabled.
Cleanup preserves authored planner fields/activity and report replay identity;
source-derived report and origin material can expire independently.
Detail and new imports enforce the canonical trusted source deadline even
before cleanup runs. Expired report reads return 410; new imports cannot
resolve expired source material. Generated origin context and source links
are hidden when their trusted bounds expire. Reads never delete stored data.
Identity-only retries still acknowledge an existing report/post without
restoring content or extending its original deadline. Physical deletion
remains the explicit cleanup operation; history visibility is not retention, and
an ageing-out or hidden report is not deleted.

For local use, the smallest procedure is a manual dry-run and approved apply
using a privately supplied `TRENDORA_RETENTION_DATABASE_URL` for the exact
approved target:

```bash
.venv/bin/python -m trendora.retention --database-env TRENDORA_RETENTION_DATABASE_URL
# Only after approval for this target and apply run:
.venv/bin/python -m trendora.retention --database-env TRENDORA_RETENTION_DATABASE_URL --apply
unset TRENDORA_RETENTION_DATABASE_URL
```

Run the approved procedure after waking the laptop and check its result.
Manual operation has no finite maximum deletion delay. An approved hourly OS
cron job would normally add up to 60 minutes plus execution time while awake;
sleep and failed runs remove that bound, and missed cron runs do not catch up
automatically. Access still refuses expired data at the next read. No local
cleanup or scheduler is activated by these instructions.

Disposable PostgreSQL verification through 0008 now passes (section F).
Still pending on the actual deployment: host/plan/runtime limits, TLS and auth,
dedicated recovery-key provisioning, migration history/schema compatibility,
provider quotas/access, and an explicitly approved retention schedule. Never
enable cleanup implicitly; history visibility and hidden source links are not
deletion. Application-database, provider, cleanup, and deployment operations
require approval for the exact target.

---

## F. Ordered release operations

### Migration and backup strategy

Before applying any migration to a target that holds real data:

1. Confirm the target's current revision with the Alembic history for that
   database, and confirm it is the database you intend to change.
2. Take a logical backup (for example `pg_dump`) and verify a restore into a
   disposable database. An unverified backup is not a backup.
3. Apply migrations from a checkout whose revisions you have reviewed.
4. Post-migration checks must be explicitly non-destructive: confirm the applied
   revision, exercise read paths, and re-run only read-only checks against the
   target. The destructive and migration test suites are for a disposable
   cluster only. Never point them at an application database, and never use a
   schema-mutating suite as a verification step against one.

Never run `--apply` retention, migrations, or cleanup against a target you have
not explicitly identified and approved, and never against a shared database
someone else may be using.

As of 2026-10-07, disposable database verification is complete; no deployed
Trendora environment is confirmed. Repository hosting identity files are
absent, the connected Sites inventory returned no sites, and no Render/Vercel
connector or hosting CLI is available in this session. This does not prove
there is no deployment elsewhere. `render.yaml` remains a reference template.
The intended frontend/backend host, environment and service IDs are needed
before host-specific settings or limits can be accepted. None of the operations
below is activated by this guide.

1. Completed evidence (dated): on a disposable local PostgreSQL instance, 45
   database checks and 55 focused offline checks passed, covering a fresh
   migration, the `0007` to `0008` upgrade, legacy NULL expiry, UUID defaults,
   row-level security and grants, membership and history behaviour, concurrent
   writes, signed replay, and a synthetic retention dry-run and apply. Authored
   planner content survived cleanup, and the owned instance was stopped and
   removed afterwards. These results do not establish any application
   database's migration history. Do not repeat completed local checks without a
   relevant change.

   Before migrating a real target, take a backup that you have verified can be
   restored, and confirm the target's current revision. See the backup strategy
   below.

2. Identify and approve the intended backend/frontend service IDs, environment,
   database target and test accounts. Record plan/runtime, TLS URLs, backend
   connectivity, auth issuer/audience and active memberships. Confirm actual
   request AND response limits, including full saved reports and generation
   timeouts. If Vercel is chosen, its 4.5 MB host cap applies before the 8 MiB
   application save cap. `/health` checks the process, not schema or membership.

   Frontend: inject `NEXT_PUBLIC_SUPABASE_URL` and the public
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` before building; Next.js embeds them in the
   browser bundle. Keep `TRENDORA_API_BASE_URL` server-side and point it at the
   selected backend. The backend's `SUPABASE_URL` must identify the same auth
   project; tokens require issuer `<SUPABASE_URL>/auth/v1`, audience/role
   `authenticated`, and RS256 or ES256 JWKS keys. HS256-only signing is
   incompatible. Active local membership remains required. Approve the exact
   frontend callback/reset URLs and test accounts before changing auth settings.
   Verify TLS, forwarded bearer headers and backend/JWKS connectivity on the
   target. No authentication settings were changed here.

   Record both host request and response limits. An 8 MiB save cap does not
   bound generated/saved report responses. Vercel's 4.5 MB cap is an explicit
   compatibility limit; a successful small mock is insufficient to accept
   larger payloads. Render's actual ingress body limits remain unverified here;
   inspect the selected service/proxy configuration or obtain a documented
   host limit, then verify synthetic boundary payloads with target approval.

3. Provision the recovery signing key only for the approved backend environment.
   Generate one dedicated value with a password manager's cryptographically
   secure generator (64 random alphanumeric characters), store it in an
   environment-specific secret entry, and paste it directly into the host's
   secret setting. Do not print it, put it in Git, or generate it at startup.
   All backend workers/services that issue or verify receipts must use the
   same value across restarts. The frontend must never receive it.

   If Render is selected: open the exact backend service's **Environment** page,
   add `TRENDORA_REPORT_RECOVERY_SIGNING_KEY`, and choose **Save only** until the
   migration and rollout are approved. For multiple backend services, use one
   environment-scoped environment group and remove conflicting service-level
   overrides. The template's `sync: false` placeholder contains no value and
   does not provision a secret. Roll out all workers with that stored value,
   then exercise configured-key recovery across a restart. Rotation invalidates
   outstanding receipts. [Render secret settings](https://render.com/docs/configure-environment-variables).

4. Obtain approval for the named deployment database and migration runner.
   Use a checkout containing the corrected 0007, `alembic.ini`, and `alembic/`,
   with dependencies already prepared and `DATABASE_URL` injected by the host's
   secret mechanism. Do not package local environment files or inherit local
   `PG*` overrides. Before mutation, run these read-only queries through the
   approved target's SQL console (an empty database has no version table):

   ```sql
   SELECT version_num FROM public.alembic_version;
   SELECT character_maximum_length
   FROM information_schema.columns
   WHERE table_schema = 'public' AND table_name = 'alembic_version'
     AND column_name = 'version_num';
   SELECT is_nullable
   FROM information_schema.columns
   WHERE table_schema = 'public' AND table_name = 'planner_post_origin_sources'
     AND column_name = 'collected_at';
   ```

   Compatibility caveat: 0007 retains its 33-character revision identity and
   now widens Alembic's version column to 64 before recording it. Fresh and
   pre-0007 upgrades are verified. A target already at 0007/0008 will not rerun
   the edited migration; its prior manual fixes, stamps and schema are unknown.
   At 0007/0008, `collected_at` must be nullable and the version column must
   accommodate 0007 (including on downgrade from 0008). Stop on divergence or
   unknown revision IDs and obtain approval for explicit remediation. Do not
   rename revisions, stamp over a failure, or silently alter an existing target.

   After preflight and migration approval, run one migration process before
   releasing the new backend workers:

   ```bash
   python -m alembic current
   python -m alembic upgrade 0008_report_source_expiry
   python -m alembic current
   ```

   Require the final revision to be `0008_report_source_expiry`; abort rollout
   on any command failure. Backend start command:
   `uvicorn trendora.api.app:create_app --factory --host 0.0.0.0 --port "$PORT"`.
   Frontend commands, from `web/` with installed dependencies and public auth
   configuration, on a Node host:

   ```bash
   npm run build -- --webpack
   npm run start -- --hostname 0.0.0.0 --port "$PORT"
   ```

   Vercel manages frontend startup.

   Render Free has no pre-deploy command/one-off job runner. Use a separately
   authorized checkout with database connectivity; do not put migrations in
   every worker's start command. A paid Render service can use the same explicit
   upgrade command as `preDeployCommand` after target/billing approval.
   [Render deploy steps](https://render.com/docs/deploys).
   The reference Docker image omits migration files; use the checkout runner
   above if Docker is selected. No host settings or paid plan were provisioned.

5. Approve the retention target, first dry-run and first apply run, scheduler
   and allowed cleanup delay. Configure only that job with the explicitly named
   `TRENDORA_RETENTION_DATABASE_URL`. Dry-run command:
   `python -m trendora.retention --database-env TRENDORA_RETENTION_DATABASE_URL`.
   Inspect counts, then run the same command with `--apply` after its approval.
   Source-bearing detail/new imports refuse elapsed trusted deadlines before
   cleanup; the apply run separately removes stored source-derived data.

   A proposed minimum operating setup is one existing platform cron job running
   the apply command hourly (`0 * * * *`, UTC), with run failures checked in the
   platform's existing logs. Successful hourly runs give a maximum delay of
   60 minutes plus scheduler/startup delay and execution time; failed or delayed
   runs have no finite bound. Accept that delay explicitly before activation.
   No actual host or deadline SLA is confirmed, so the cadence is not approved.
   If Render is chosen, use a separately approved Cron Job or an existing trusted
   scheduler; a sleeping Free web service is not a scheduler. Render Cron Jobs
   have a minimum charge of $1/month. No cron service is added to the template.
   [Render Cron Jobs](https://render.com/docs/cronjobs).

6. On the approved deployed test environment, use authorized test accounts and
   synthetic data to verify authentication, research/save or lost-ack recovery,
   stable report identity, planner import/retry and account switching. Use
   mocked source/AI responses; paid provider calls and provider quality are
   outside this verification. Check host-sized payload failures and restart
   recovery before accepting the deployment. Local browser mocks do not satisfy
   this deployed check.

---

## Risks

- **Access configuration.** Verify token validation, active memberships,
  administrative permissions, and database roles on the intended deployment.
- **Provider quotas.** YouTube Data API quota and AI provider credits are
  billed/limited per account; a public endpoint can be abused.
- **Free-tier limits.** Render/Vercel free tiers have compute/hour and cold-start
  constraints; evaluate against real usage.
- **Database exposure.** The Supabase `DATABASE_URL` is a full-access credential;
  treat it as a secret and rotate if leaked.
