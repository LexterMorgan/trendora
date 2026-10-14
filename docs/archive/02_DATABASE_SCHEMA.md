# 02 — Database schema

Status: Milestone 1 schema is implemented. Alembic revision `0001_initial_schema`. Connectors and analytics tables are not in this revision.

## Portability rule

Schema is plain PostgreSQL, compatible with:

- the V1 development database: existing Supabase PostgreSQL 17 (`https://ymzloduyggkcmapmiics.supabase.co`, database `postgres`)
- local PostgreSQL later, using the same SQLAlchemy models and Alembic revisions

Avoid vendor-only types unless they exist in both environments. Current types: `uuid`, `timestamptz`, `text`, `jsonb`, `bigint`, `integer`.

`jsonb` is used for optional source-specific metadata. Both local Postgres and Supabase Postgres support it. Models do not call Supabase APIs.

## How to migrate

From the repository root, with `.venv` active and `DATABASE_URL` set (see `.env.example`):

```bash
alembic current
alembic upgrade head
```

Alembic reads `DATABASE_URL` from application settings. It does not use a hard-coded URL.

Trendora only creates and manages its own application tables plus `alembic_version`. Do not use these migrations to drop unrelated Supabase schemas (`auth`, `storage`, and so on).

If this V1 database already records `0001_initial_schema` in `alembic_version`, `alembic upgrade head` is a no-op. The same SQL was also applied once via the development Supabase MCP (`trendora_0001_initial_schema`). Do not re-apply that SQL by hand.

## Design

Normalized core, source-agnostic:

1. **Source registry** — platforms listed in [03_DATA_SOURCES.md](03_DATA_SOURCES.md). Registry rows are not connectors.
2. **Markets / topics** — SEA markets and the product domain taxonomy.
3. **Publishers** — channels, accounts, owners. Identity is `(source_id, external_id)`.
4. **Content items** — videos, stories, questions, repositories, articles. Identity is `(source_id, external_id)`.
5. **Metric snapshots** — append-only observations. Never overwrite current statistics in place.
6. **Retention policies** — documented hooks (YouTube 30-day non-authorized stats/metadata). No retention job in Milestone 1.

Source-specific fields belong in `source_metadata` (JSONB) until a later milestone has a proven need for dedicated columns.

## Tables

| Table | Role |
| --- | --- |
| `sources` | Platform registry (`code` unique). Seeded: youtube, hacker_news, stack_exchange, github, wikimedia, gdelt. |
| `markets` | SEA markets (`code` unique, ISO 3166-1 alpha-2). Seeded: ID, TH, MY, SG, VN, PH. |
| `topics` | Domain taxonomy (`code` unique). |
| `retention_policies` | Retention hooks (`code` unique). Seeded YouTube 30-day stats and metadata policies from docs/03. |
| `publishers` | Source-local publisher. Unique `(source_id, external_id)`. Optional `market_id`, `retain_until`. |
| `content_items` | Canonical content. Unique `(source_id, external_id)`. Optional publisher/market, `published_at`, `retain_until`. |
| `content_item_topics` | Many-to-many. Composite PK `(content_item_id, topic_id)`. |
| `metric_snapshots` | One row per collected metric observation. |
| `alembic_version` | Alembic revision stamp. Not an application table. |

All application tables use timezone-aware `created_at` / `updated_at` except the association table `content_item_topics`.

### Metric snapshots (YouTube-ready, source-agnostic)

- Subject XOR: exactly one of `content_item_id` or `publisher_id`.
- `metric_name` + `metric_value` (bigint). Historical rows are inserted; existing rows are not updated to “current”.
- `observed_at` — when the source said the value was true.
- `collected_at` — when Trendora stored the observation.
- Optional `retention_policy_id` and `retain_until` for later cleanup jobs.
- Partial unique indexes: `(content_item_id, metric_name, collected_at)` and `(publisher_id, metric_name, collected_at)`.

This supports later YouTube snapshot collection without making YouTube the whole model. No YouTube API connector is included here.

## Constraints worth reviewing

- Unique codes on catalog tables.
- Unique `(source_id, external_id)` on `publishers` and `content_items`.
- `ck_metric_snapshots_subject_xor` on `metric_snapshots`.
- Foreign keys from publishers, content, and snapshots back to catalog tables.
- Indexes on foreign keys, `observed_at`, and `retain_until` where lookups are expected.

## Row Level Security

Milestone 1 enables PostgreSQL RLS on application tables and `alembic_version` with **no policies**. PostgREST anon/authenticated roles therefore see no rows. The table owner (and the SQLAlchemy/Alembic `DATABASE_URL` role) still can.

This is a Postgres privilege boundary, not a modeled Supabase feature. No RLS policies were invented beyond that exposure control.

Supabase’s linter may still report “RLS enabled, no policy” at INFO. That is expected until a later milestone defines real policies.

## Not in this revision

- Connector tables or YouTube-only DDL
- Derived analytics / forecast / anomaly tables
- AI explanation storage
- Retention worker
- Authentication
