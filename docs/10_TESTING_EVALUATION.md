# 10 - Testing and evaluation

How the repository is tested, what the tests establish, and where the evidence
stops. For scope see [14_PRODUCT_ARCHITECTURE_REBASELINE.md](14_PRODUCT_ARCHITECTURE_REBASELINE.md);
for running the app see [DEPLOYMENT.md](DEPLOYMENT.md).

## Commands

Backend (from the repository root, using the project virtualenv):

```sh
.venv/bin/python -m pytest tests/unit -q          # offline unit suite
.venv/bin/python -m pytest tests/integration -q   # requires a database, see below
.venv/bin/python -m trendora.research.evaluation report.json
```

The last command is the offline research-quality evaluator. It reads an
exported report, writes structural diagnostics and a human-review worksheet,
and never calls a model or the network. See
[RESEARCH_QUALITY.md](RESEARCH_QUALITY.md).

Frontend (from `web/`):

```sh
npm test                       # node --test over tests/*.test.ts
npm run lint                   # eslint
npx tsc --noEmit               # typecheck
npx next build --webpack       # production build (Turbopack is unsupported here)
npm run test:browser           # isolated mocked browser scenarios
```

`npm run test:browser` copies the frontend to a temporary directory, builds it
with Webpack, starts it on a random port, and drives it with a
Playwright-compatible driver. It needs a driver module and a browser binary:

```sh
TRENDORA_BROWSER_DRIVER=<path-to-playwright-core> \
TRENDORA_BROWSER_EXECUTABLE=<path-to-chromium-binary> \
npm run test:browser
```

Without a driver it exits with a prerequisite failure instead of pretending the
scenarios ran.

## Isolation

Offline tests are guarded. `tests/conftest.py` installs `tests/io_guards.py`,
which blocks database connections, sockets, and DNS resolution before
collection, and fails with the offending target when a test tries to reach
something it did not declare. A test that genuinely needs loopback network must
permit it explicitly for that block.

This means the unit suite cannot silently fall back to a real provider, and
`tests/unit` is safe to run with no services and no credentials.

## Database-backed tests

Integration tests are marked `integration` and need a PostgreSQL target in
`TRENDORA_TEST_DATABASE_URL`. Only that explicit variable is read; the harness
never falls back to the application `DATABASE_URL` or `.env`. Without it, the
database tests skip.

Two levels of access exist, and they are not the same:

| Level | Opt-in needed | What it does |
| --- | --- | --- |
| Ordinary database tests | None beyond `TRENDORA_TEST_DATABASE_URL` | Connect read-mostly through `test_engine` to a **pre-migrated** test database. The harness does not create or migrate anything for them. |
| Destructive and migration tests | `TRENDORA_TEST_DISPOSABLE_PG_URL`, certified disposable by the operator | Create and drop databases and cluster-wide roles inside that approved cluster, truncate shared fixture data, and run `alembic upgrade head` once per session through `scratch_schema`. |

Details that matter:

- `scratch_schema` runs `alembic upgrade head` in a subprocess only when the
  disposable opt-in is present. Without it, the fixture returns `None`, performs
  zero subprocess work, and the test database must already be migrated.
- Migration tests own what they create. Each run creates one uniquely named
  database and only the roles it created itself; a pre-existing object stops the
  run instead of being dropped, and teardown removes only this run's objects.
- `PG*` handling is deliberately uneven. Subprocess environments (Alembic,
  `psql`) are rebuilt with libpq routing variables stripped. The
  `approved_engine` used by destructive tests rejects inherited `PG*` overrides
  before connecting and rebuilds its URL from the validated target. The ordinary
  `test_engine` does neither, so an inherited `PG*` variable in your shell can
  affect it.
- Both URLs are validated in-process (scheme, loopback, same endpoint) before
  any subprocess starts, and failure output is credential-redacted.

Never point either level at an application database, and treat an approved
disposable target as destroyed by the run.

## What each kind of evidence establishes

| Evidence | Establishes | Does not establish |
| --- | --- | --- |
| Offline unit tests | Contract behaviour with mocked transports and synthetic data | Provider behaviour, live latency, real prose quality |
| Integration tests on a disposable database | Real SQL, migrations, and concurrency against PostgreSQL | Production configuration, retention scheduling, deployment |
| Mocked browser scenarios | Rendered output, keyboard behaviour, account isolation, and responsive layout in a real browser | Live providers, real research content |
| Live provider tests | Whether real endpoints respond as expected at that moment | General reliability, cost, or policy compliance |

Mocked AI responses prove the schema, grounding, citation integrity, and failure
behaviour. They cannot show that a live model writes better or more accurate
prose; that requires human review of a live run.

## Frontend checks

`web/tests/*.test.ts` cover pure logic and client modules. `web/tests/*.browser.mjs`
scenarios run against the isolated build described above and assert rendered
text, control behaviour, focus handling, and layout metrics. Scenario names and
their assertions are the specification for reader behaviour, including that
saved reports never mutate when rendered.

## Evaluation of research quality

The repository has no automated measure of whether a finding is factually
supported. Citation validation proves the cited evidence was supplied; it does
not prove entailment or significance. Research quality is reviewed by a human on
a live report, checking each finding against its cited text and flagging
unsupported specifics, missing qualifications, duplicates, and unsupported
recency claims.

## Not chosen

Load testing, coverage targets, annotation workflows for model quality, and
automated trend or growth evaluation. Trend claims require time-series evidence
the product does not collect.
