# Trendora — Research Workspace (web)

Next.js (App Router) + React + TypeScript frontend for the Trendora research
workflow. It consumes the research/report API; collection and analysis remain
in the backend. The authoritative [product PRD](../docs/14_PRODUCT_ARCHITECTURE_REBASELINE.md)
makes research the primary use and the existing shared planner optional.
Reports lead with research findings, supporting sources, dates, and coverage
limits. Research-only requests may run grounded interpretation; strategy and
ideation run only when content tools are requested. If synthesis fails, collected
evidence and labelled source excerpts remain available for saving and recovery.
Content ideas, briefs, and planner actions remain secondary and explicit.

## Local development

Backend (Terminal 1, repository root):

```bash
.venv/bin/python -m uvicorn trendora.api.app:create_app --factory \
  --reload --host 127.0.0.1 --port 8000
```

Frontend (Terminal 2, this directory):

```bash
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Use the already installed dependencies and preserve existing private
environment files. [Local startup and variable requirements](../docs/DEPLOYMENT.md#a-local-startup-with-installed-tools)
cover the backend, source configuration and save-recovery signing key.
Starting either server does not migrate or clean a database. The frontend is
available at `http://127.0.0.1:3000`.

Required environment variable (`web/.env.local`):

| Variable | Purpose | Example |
| --- | --- | --- |
| `TRENDORA_API_BASE_URL` | FastAPI backend base URL the server proxy forwards to | `http://127.0.0.1:8000` |

## Browser authentication

Sign-in, invitations, and password recovery run through Supabase Auth in the
browser (implicit flow). The backend verifies the resulting JWT; the browser
only ever holds the public anon/publishable key. Never put a service-role key
in these variables.

| Variable | Purpose | Example |
| --- | --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (public) | `https://xyzcompany.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/publishable key (public) | `eyJhbGciOi...` |

With either variable missing, protected pages render a sign-in-unavailable
notice instead of any workspace content.

Supabase project setup:

1. **Callback allowlist.** Dashboard → Authentication → URL Configuration →
   Redirect URLs. Add exactly the two URLs this app sends links to, per
   origin:

   | Screen | Local | Deployed |
   | --- | --- | --- |
   | Invitations | `http://127.0.0.1:3000/accept-invite` | `https://<your-domain>/accept-invite` |
   | Password recovery | `http://127.0.0.1:3000/reset-password` | `https://<your-domain>/reset-password` |

   Set the Site URL to `http://127.0.0.1:3000/` locally (your deployed origin
   in production) so links without an explicit redirect still return to the
   app. Supabase rejects a link whose callback URL is not allowlisted before
   any session is established, so the invitee never reaches a password
   screen.
2. Keep the default email templates (`{{ .ConfirmationURL }}`): links carry
   the auth result in the URL hash, which the app reads.
3. **Invitations must target `/accept-invite`.** Send them from trusted
   server or operator code — a Node backend, an admin CLI, a dashboard
   script — that holds the service-role key:

   ```ts
   // Trusted server code only: this runs with the service-role key.
   const { error } = await supabase.auth.admin.inviteUserByEmail(email, {
     redirectTo: `${appOrigin}/accept-invite`,
   });
   ```

   The dashboard invite dialog makes the same admin call, and sets the same
   redirect. Either way, never build this call in the browser: the
   service-role key bypasses every authorization check, so it must not
   appear in `NEXT_PUBLIC_*` variables, in a client bundle, or in anything a
   user can run. The browser only ever holds the anon (publishable) key.

   Recovery links already target `/reset-password` (`sendPasswordResetEmail`
   passes `redirectTo`). Implicit flow lets an invite be accepted in a
   different browser than the one that sent it. Without the invite redirect,
   an invitee lands in the workspace without ever setting a password.
4. **Turn off public sign-up.** Dashboard → Authentication → Providers →
   Email: toggle off **Allow new users to sign up** (older dashboards label
   it *Enable sign ups*), and disable it for every OAuth provider you have
   configured. The app offers no self-service sign-up: all three screens
   (sign-in, accept-invite, reset-password) assume an invited account, and
   the password screen only appears for the session the link itself
   establishes.

Flow summary: `/login` signs in with email + password (or emails a recovery
link); `/accept-invite` and `/reset-password` parse the link hash, wait for
the session it establishes, then set the password. The shared session store
(`lib/auth/session.ts`) drives `Protected` gating, redirects signed-out
visits to `/login`, replaces workspace content with a stable access-denied
card when the backend rejects the account, and remounts content
(`userId:epoch`) on sign-out or account switch. API calls attach
`Authorization: Bearer <access_token>` via `lib/api.ts` and stay bound to the
`userId:epoch` they started under, so a response from a previous session is
discarded instead of acting on it; the Next.js proxies forward the header
upstream and respond with `Cache-Control: private, no-store`.

## Commands

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # eslint
npm run build       # production build
npm run dev         # local dev server
npm test            # node --test (auth, API, proxy unit tests)
npm run test:browser # execute rendered browser regressions (needs a driver)
npm run test:browser:contract # check the browser module contract only
```

The rendered browser regressions live in `tests/planner-workspace.browser.mjs`.
`npm run test:browser` executes them and requires a Playwright-compatible
driver (`TRENDORA_BROWSER_DRIVER`, or an installed `playwright`). The adapter
in `tests/browser-fixture.mjs` uses a private frontend copy, fresh browser
storage, fictional accounts, and owned loopback mock services. No driver is
bundled here; use an already-installed compatible module, including a package
path supplied at runtime. Missing prerequisites and failed acceptance
assertions return nonzero exits. `npm run test:browser:contract` checks only that the
module exports a well-formed, non-empty scenario list; it executes nothing.

## How the frontend reaches the API

Browser → same-origin Next.js route handler (`app/api/research/route.ts`) →
`${TRENDORA_API_BASE_URL}/api/v1/research`. The proxy forwards the structured
request and passes through the backend status/body; it performs no research
logic and never exposes backend credentials.

## Manual shared planner (P2B)

`/planner` lists active or archived posts with bounded pagination.
`/planner/new` creates a manual post; `/planner/[id]` opens its editable
workspace. Every active member shares these records from creation.

Creation starts with **Idea**, as required by the backend. After creation,
the workspace supports **Idea** and **Working on it**. Save sends a complete
snapshot with its expected version. Archive and Restore are explicit
versioned actions; there is no permanent deletion or autosave.

Platform, planned date, and assignment are optional. Assignment choices
include active members. An unchanged historical assignment remains selected
when that member is no longer available. Asset links must be HTTP(S) URLs
without embedded credentials; Trendora does not fetch previews. A planning
date never triggers automatic publication.

Unacknowledged creation keeps one request ID paired with its original
submission. Retry that attempt before making changes. If creation returns
an ID but reading the post fails, retry the read rather than creation.
An unresolved creation blocks same-tab navigation; the inbox can be
inspected in a new tab while retaining the attempt.
Uncertain saves, archives, and restores require checking server state before
another mutation. Version conflicts retain entered text and require an
explicit decision to load the server snapshot or keep local edits using
the latest version; neither choice automatically saves.

Unsaved text stays in memory only. Nothing is saved offline or placed in
browser storage. Controlled navigation and archive warn before discarding
edits. Reload and tab-close warnings depend on the browser; browser
Back/Forward navigation may leave without a prompt. Account changes,
logout, and membership denial clear the protected workspace.

Planner requests use `lib/api.ts` and the same-origin `app/api/planner/`
proxies. Those routes forward bearer authorization to fixed
`TRENDORA_API_BASE_URL` planner endpoints, disable caching, and bound write
bodies to 131072 bytes while streaming.

P2B verification uses fictional mocked auth and backend services. It does
not verify live Supabase authentication/schema, deployment permissions, or
readiness for real private drafts. P3 adds explicit import of saved research
ideas/briefs with immutable origin, frozen retry keys, and visible save recovery.
Reading research does not require creating a planner post. Approval, comments,
activity feeds, board/calendar views, and publishing remain deferred.

## Vercel

The deployment shape uses root directory `web`, build command `npm run build`,
and `TRENDORA_API_BASE_URL` pointing to the hosted FastAPI backend. Actual
hosting limits, database/access verification, retention cleanup, and provider
compatibility remain release checks. This documentation review did not deploy
or verify those checks.
