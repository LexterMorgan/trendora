# P2A Manual Shared Planner Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans when available to implement this plan task-by-task. Steps use checkbox syntax for tracking. Lex's selected external builder is MiMo 2.6 Flash Free; the main assistant reviews the actual diff. Do not dispatch another builder or change model configuration.

**Goal:** Persist shared manual posts with protected reads, retry-safe creation, conflict-safe edits, assignment, and archive/restore, without research or AI.

**Architecture:** Add planner tables to the existing PostgreSQL database. A small planner module owns input contracts and transactional operations; a thin FastAPI router reuses the existing authentication and session dependencies. Research snapshots and frontend auth remain unchanged.

**Tech Stack:** Existing Python 3.12+, SQLAlchemy 2, PostgreSQL/psycopg, Alembic, Pydantic, FastAPI, and pytest. No added dependencies.

**Spec:** `/Users/lex/Projects/trendora/docs/superpowers/specs/2026-09-25-shared-content-planner-design.md`

Status: ready for Lex's plan review, not implemented. P2A is the backend half of P2. P2B adds the inbox/editor and proves browser input recovery; this plan alone does not complete P2.

## Global Constraints

- One deployment holds one shared planner. All posts are shared with active members from creation, including archived posts. No creator-only visibility or 30-day planner cutoff.
- Identity comes from verified authentication and active database membership. Admin and can-approve remain separate; neither is required for ordinary planner edits.
- Date-only planning. UTC activity timestamps. No automatic publication or status change when a date passes.
- Editable posts are separate from immutable research reports. Manual operations require a database, not AI/research credentials or services.
- Each mutation writes its associated activity in the same transaction and returns success only after commit.
- Atomic expected-version checks prevent silent overwrites. Creation uses a stable request ID; identical retries return the same post ID, changed payloads conflict.
- Archive/restore only, no permanent delete. No review, comments, publication recording, research imports, board/calendar, provider changes, or frontend work in P2A.
- Preserve all existing staged/unstaged work. No staging, unstaging, commits, pushes, installs, live provider calls, application database operations, or live Supabase provisioning.
- Do not read `.env`, credentials, or real private drafts. Use fictional test content. Antislop applies during work; no em dashes in new prose/comments.
- Run unit tests offline. Integration collection is allowed. Real PostgreSQL tests require separate owner approval, both disposable/test URLs, the existing approved harness, and no application credentials. Do not invent approval or start/provision a cluster.

## Review Focus

1. A creation retry arriving after the first post was edited or archived still returns its original ID without overwriting it: Task 2 retry regressions.
2. Two devices save the same version concurrently: exactly one succeeds and the other receives 409, with no extra activity: Task 2 concurrency regression.
3. Membership/assignment changes race a write: actor and newly selected assignee must still be active when the write commits: Task 2 membership locking regression.
4. Request size is understated or omitted, or a date arrives as a timestamp/number: reject oversized streamed bodies and non-date values before any planner mutation: Task 3 boundary regressions.
5. A new FK breaks existing cleanup, or inherited libpq settings redirect migration tests: Task 1 offline harness proof and Task 2 approved integration compatibility checks.

## Verified reuse and limits

- `src/trendora/api/auth.py`: `require_member`, `Member`, and local active-membership checks. Do not use JWT metadata for roles.
- `src/trendora/api/deps.py`: shared request session and sanitized session-setup errors.
- `src/trendora/api/errors.py`: `ApiError` and `DataUnavailableError`, already registered by `create_app`.
- `src/trendora/db/base.py`: `Base`, naming convention, and timestamp conventions.
- `src/trendora/models/membership.py`: retained member UUIDs and email labels. No new membership or display-name schema.
- `tests/integration/conftest.py`: `approved_engine` is the only engine for new shared-data writes. `test_engine` is not its substitute.
- Current local evidence: 1,187 backend unit tests pass. Gate B remains reviewed; live Supabase/deployment remains unverified. The older spec's statements that routes lack auth describe its baseline, not the current code.
- Remaining test hazard: `tests/integration/test_gate_a_migration.py::_alembic` builds from `os.environ` without `libpq_free_env`. Its canonical URL alone does not neutralize `PGHOSTADDR`/`PGSERVICE`. Correct this seam before executing any migration tests.

## File map

Create:

- `src/trendora/models/planner.py`: `PlannerPost` and `PlannerPostActivity` ORM records.
- `src/trendora/planner.py`: typed planner contracts, input validation, reads, and transactional mutations. No generic repository/provider layer.
- `src/trendora/api/planner.py`: `planner_router`, route-local body cap, and thin handlers.
- `alembic/versions/0004_planner_posts.py`: additive schema and new-table access protection.
- `tests/unit/test_planner_models.py`, `tests/unit/test_planner.py`, `tests/unit/test_planner_api.py`: offline model, policy, transaction, and API checks.
- `tests/integration/test_planner.py`: real transaction/race checks through `approved_engine` only.

Modify only:

- `src/trendora/models/__init__.py`: register/export the two models.
- `src/trendora/api/app.py`: import/include `planner_router`; no research/auth refactor.
- `tests/integration/test_gate_a_members_admin.py`: explicit FK-compatible fixture cleanup.
- `tests/integration/test_gate_a_migration.py`: safe Alembic subprocess environment and planner migration assertions using its existing owned-resource harness.
- `tests/integration/test_database.py`: expected head becomes `0004_planner_posts`.
- `tests/unit/test_pg_harness.py`: mocked regression for the migration helper's environment. No harness permission expansion.

## Contracts decided for this slice

### Inputs and output

`PostFields` in `trendora.planner` contains the complete editable snapshot: `title`, `platform`, `caption`, `hook`, `creative_brief`, `asset_links`, `notes`, `planned_date`, and `assignee_id`. All keys are required; blank strings, an empty link list, and null date/assignee are valid except title. P2B supplies these empty values for a new manual post.

- Title: trim outer whitespace, 1..200 characters. Platform: trim outer whitespace, 0..80 characters; blank means not selected yet.
- Hook: 0..1,000 characters. Caption, creative brief, notes: each 0..20,000 characters. Preserve their whitespace/newlines.
- Asset links: at most 20 HTTP(S) URLs, each at most 2,048 characters, a nonempty host, no username/password. Store strings; never fetch previews or validate reachability.
- `planned_date`: null or an exact `YYYY-MM-DD` calendar date. Reject numeric epochs and datetime strings. Past/future planned dates are allowed; publication-date policy belongs to P5.
- `assignee_id`: null or a member UUID. New/changed non-null assignments require an active member. An unchanged inactive historical assignee does not prevent editing other fields; null clears assignment.
- Reject unknown fields and non-string text values. Versions are strict positive integers, not booleans or numeric strings. Avoid global strict mode that rejects valid JSON UUID/date strings unintentionally.
- `PostCreate(PostFields)` adds required UUID `request_id`. Initial status is always `idea`.
- `PostUpdate(PostFields)` adds required `expected_version` and `status`, restricted to `idea | working`. This is a full snapshot, not a merge PATCH. P4 will deliberately expand the status policy.
- `PostVersionRequest` contains only required `expected_version` for archive/restore.
- `PostRead` returns editable fields plus `id`, `status`, `version`, `content_revision`, `created_by`, `updated_by`, UTC `created_at`/`updated_at`, and nullable UTC `archived_at`. Never return the creation payload hash.
- `PostSummary` returns only `id`, `title`, `platform`, `status`, `planned_date`, `assignee_id`, `version`, `updated_at`, and `archived_at`. List responses do not load full draft text.
- `PlannerMemberOption` returns only `user_id` and `email` for active assignment options, sorted by email then UUID. No membership writes or permission flags.

### Database

`planner_posts` stores the PostRead fields. Use UUID primary keys, SQL `DATE` for planned dates, timezone-aware timestamps, JSONB for the bounded asset-link array, and positive integer version/content_revision initially 1. Add a check restricting status to `idea`/`working`. Archive is not a status.

`created_by`, `updated_by`, and nullable `assignee_id` reference `memberships.user_id` with no cascading deletion. Add immutable `create_request_id` UUID and `create_payload_hash` (SHA-256 hex) with unique constraint `(created_by, create_request_id)`. Hash the normalized validated creation fields in canonical JSON; exclude the request ID and server metadata. Never recompute that hash after editing.

`planner_post_activity` has a UUID primary key, non-cascading post/member FKs, `event_type` (`created`, `updated`, `archived`, `restored`), UTC timestamp, and small JSONB details: changed field names, resulting version, and status/archive decision where relevant. Do not duplicate captions, notes, or full payloads in activity. No standalone activity-write API.

Index the post-list ordering `(updated_at, id)` and activity `(post_id, created_at, id)`. Do not add search indexes, a job queue, idempotency service/table, workspace tables, or future review/import columns.

Migration `0004_planner_posts` follows `0003_memberships_history`. Enable RLS without browser policies on both new tables, revoke all new-table grants from `PUBLIC` and from each existing `anon`/`authenticated` role independently. Do not change schema-wide defaults, existing grants, or runtime database roles. This preserves the current trusted-backend access model; it is not user-scoped RLS enforcement for the backend. If the actual backend role cannot access these tables, stop for a deployment decision rather than disabling RLS or granting browser access.

Downgrade removes only these two new tables, activity first. It destroys planner records and must never be run against real drafts without separate approval. Test preservation of memberships, permission history, and research snapshots.

### Service interfaces

All contracts above live in `src/trendora/planner.py`. Routes pass the existing request `Session` and derive actor UUID from `Member`, never request data.

```python
create_post(session: Session, *, actor_id: UUID, data: PostCreate) -> tuple[UUID, bool]
get_post(session: Session, *, post_id: UUID) -> PostRead
list_posts(session: Session, *, archived: bool, limit: int, offset: int) -> list[PostSummary]
update_post(session: Session, *, actor_id: UUID, post_id: UUID, data: PostUpdate) -> PostRead
set_archived(session: Session, *, actor_id: UUID, post_id: UUID, expected_version: int, archived: bool) -> PostRead
list_assignees(session: Session) -> list[PlannerMemberOption]
```

- The creation tuple is `(id, created)`: first success 201, replay 200, both return only `{"id": "<uuid>"}`. A stable acknowledgment avoids returning a stale creation snapshot after later edits. P2B follows with GET detail.
- Each write locks/reloads the actor and any newly selected assignee with PostgreSQL `FOR SHARE`, in UUID order, before touching the post. This cooperates with Gate A's membership lock and avoids stale ORM identity-cache decisions. Check active membership again inside the transaction; do not lock the entire planner.
- Use PostgreSQL targeted `INSERT ... ON CONFLICT DO NOTHING ... RETURNING` for creation. A duplicate key is compared with the stored immutable hash; same payload returns the ID without another activity row, changed payload gives 409. Do not reinterpret arbitrary integrity errors as retries.
- Update/archive/restore use `UPDATE ... WHERE id = :id AND version = :expected_version RETURNING ...`, with archive state in the predicate where required. A preliminary read may compute changes, but cannot replace the atomic predicate. Unknown ID is 404; stale version is 409; editing an archived post is 409.
- Increment version once per real mutation. Increment content_revision only when title/platform/caption/hook/creative_brief/asset_links change. Notes/date/assignment/status/archive changes do not change content_revision.
- After checking the expected version, an unchanged request is a no-op with no version/activity increment. Archive/restore preserve drafting status and content. A stale request is a conflict even if its desired values now match.
- Serialize the response snapshot before commit, but do not return it until commit succeeds. Post change and exactly one activity row commit together. Replay/no-op creates no activity.
- All SQLAlchemy failures, including flush/activity/commit failures, roll back and produce fixed 503 `data_unavailable`, message `planner data is unavailable`. Keep driver detail only in the cause chain. Rollback failures must not hide the original error. Other rejection paths roll back and keep their own errors. No automatic write retries.
- Define planner `ApiError` subclasses in this module, using the already registered base handler: 404 `planner_post_not_found`; 409 `planner_version_conflict`, `planner_create_conflict`, `planner_post_archived`; 422 `planner_assignee_invalid`. Use fixed messages, never driver text or submitted draft content.

### HTTP routes

Every route requires the existing `require_member`. Register static member options before the post-ID route. All UUIDs are validated parameters.

| Method and path | Contract |
| --- | --- |
| GET `/api/v1/planner/members` | Active assignment options for either editor. |
| GET `/api/v1/planner/posts` | Summary list; archived=false by default, limit=50 (1..100), offset=0 (>=0), updated_at descending then id descending. archived=true selects archived records only. |
| POST `/api/v1/planner/posts` | PostCreate; 201 new or 200 replay, stable ID acknowledgment after commit. |
| GET `/api/v1/planner/posts/{post_id}` | Full record, including archived records for restoration. |
| PUT `/api/v1/planner/posts/{post_id}` | PostUpdate; 200 committed PostRead, never blind overwrite. |
| POST `/api/v1/planner/posts/{post_id}/archive` | PostVersionRequest; 200 PostRead. |
| POST `/api/v1/planner/posts/{post_id}/restore` | PostVersionRequest; 200 PostRead. |

Use a route-local `PlannerBodyLimitRoute(APIRoute)` in `api/planner.py`, only for this router. Before FastAPI JSON parsing, consume the incoming body stream with a 131,072-byte cumulative cap; reject excess with fixed 413 `planner_request_too_large`. Replay the bounded bytes to the normal handler through a new Request/receive callable using public APIs. Do not rely on Content-Length, call unbounded `request.body()` first, patch private request state, decompress input, or change global request behavior. Schema validation retains the existing fixed 422 envelope.

## Task 1: Close the remaining migration-harness seam

Files: modify `tests/integration/test_gate_a_migration.py` and `tests/unit/test_pg_harness.py` only.

- [ ] Add `test_role_state_alembic_strips_libpq_overrides`: construct an in-memory Target/OwnedCluster, inject `PGHOSTADDR`, `PGSERVICE`, and `PGPASSWORD`, and mock `run_checked`. Assert captured env has no `PG*`, `DATABASE_URL == target.url_for(owned.database)`, non-PG environment is retained, and timeout/redaction parameters remain intact. No DNS, subprocess, or database calls.
- [ ] Run `.venv/bin/python -B -m pytest -p no:cacheprovider tests/unit/test_pg_harness.py -q`; demonstrate the regression fails for inherited PG keys.
- [ ] Build `_alembic`'s subprocess environment from existing `libpq_free_env(os.environ)` plus the canonical owned database URL. Do not modify approvals, ownership cleanup, URL validation, or runtime engine code.
- [ ] Rerun the focused check and existing approved-engine unit checks. Do not run the migration module against PostgreSQL yet.

## Task 2: Store and mutate manual posts safely

Files: create the ORM/core/migration files and model/service/integration tests; modify model registration and the three existing integration files listed above.

- [ ] Write failing offline checks: `test_planner_metadata_matches_contract` asserts DATE, FKs, unique creator/request constraint and positive counters; `test_post_fields_reject_invalid_boundaries` asserts limits, non-string inputs, unsafe/userinfo links, unknown fields, non-ISO dates, and strict versions.
- [ ] Write mocked transaction regressions: `test_creation_replay_keeps_original_id_after_edit_or_archive`, `test_creation_key_with_changed_payload_conflicts`, `test_update_uses_atomic_expected_version`, `test_stale_noop_is_still_conflict`, `test_commit_failure_has_no_success_and_rolls_back`, `test_activity_failure_rolls_back_post`, and `test_membership_rechecked_before_write`. Assert exactly the activity/commit/rollback calls required by the service rules; mocks alone are not proof of PostgreSQL race behavior.
- [ ] Run `.venv/bin/python -B -m pytest -p no:cacheprovider tests/unit/test_planner_models.py tests/unit/test_planner.py -q` and record expected failures before implementation.
- [ ] Implement the declared contracts, registered ORM records, additive migration, and service signatures, using existing SQLAlchemy/PostgreSQL primitives. No generic workflow or permissions framework.
- [ ] Extend existing owned-resource migration tests to cover both new tables across neither/anon/authenticated/both role states, RLS and absence of effective browser privileges. Add upgrade 0003->0004->downgrade 0003 preservation assertions with seeded membership/history/report rows. Reuse existing role ownership checks; never modify pre-existing cluster roles or broaden cleanup.
- [ ] Fix Gate A's membership fixture with explicit `TRUNCATE planner_post_activity, planner_posts, membership_permission_history, memberships` through its existing approved_engine. Do not use CASCADE or change the engine/opt-in contract. Update the expected migration head.
- [ ] Author `tests/integration/test_planner.py` with bounded two-session/thread tests: simultaneous identical creation yields one post/one created activity/same ID; differing payloads sharing a key conflict; competing version-1 saves produce one winner/one conflict/no loser activity; activity/commit failure leaves no partial post; deactivation and new assignment coordinate safely with the membership transaction; edited/archived creation retries preserve current content; metadata-only changes preserve content_revision. Use approved_engine for all committed writes and explicit planner/member cleanup only on that approved target.
- [ ] Rerun offline tests. Collect integration tests without execution. Real upgrade/downgrade/race checks remain pending explicit disposable-cluster approval and main-reviewer inspection.

## Task 3: Expose the protected API and stop

Files: create `src/trendora/api/planner.py` and `tests/unit/test_planner_api.py`; modify only router wiring in `src/trendora/api/app.py`.

- [ ] Write offline API regressions with mocked sessions/services: every route denies missing/invalid auth and inactive/nonmembers, both editor identities get shared access, actor IDs come from the dependency, and an editor can read assignment options without admin rights. Include a post older than 30 days and one created by the other member.
- [ ] Add boundary/error assertions: unsupported review/published statuses and injected creator/approval/origin fields return 422; stale save 409; failed commit 503 with credential-bearing fake driver detail absent; invalid assignee 422; full-snapshot missing keys rejected; archive/edit/restore rules preserved.
- [ ] Add direct ASGI receive tests for missing/understated Content-Length and multiple chunks. More than 131,072 bytes returns 413 with zero planner mutation calls; within-boundary input reaches normal validation. Assert existing non-planner routes are not capped by this router change.
- [ ] Run `.venv/bin/python -B -m pytest -p no:cacheprovider tests/unit/test_planner_api.py -q` and record failure before wiring.
- [ ] Implement the thin router and body-limit wrapper. Reuse the existing standard error handlers, session dependency, and require_member. Planner requests must never construct/invoke AI or research-source services; test those seams with raising sentinels.
- [ ] Run `.venv/bin/python -B -m pytest -p no:cacheprovider tests/unit -q`, `.venv/bin/python -B -m pytest -p no:cacheprovider tests/integration --collect-only -q`, and `git diff --check`. Inspect the diff and confirm existing staged content is unchanged. Do not run web build/install commands for this backend-only task.
- [ ] Return changed files, commands actually run, regression evidence, remaining risks, and explicit NOT RUN integration checks. Stop for main review. Do not call P2A verified until real approved PostgreSQL checks pass; do not start P2B.

## Sources and plan review

The new tables use RLS plus explicit table revokes because Supabase treats grants and row policies as separate boundaries, and project defaults can differ. See [Supabase API security](https://supabase.com/docs/guides/api/securing-your-api) and [default-grant change](https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically). No live project setting has been checked or changed.

The route-local request wrapper follows FastAPI's supported [custom APIRoute mechanism](https://fastapi.tiangolo.com/how-to/custom-request-and-route/); the exact cap and replay behavior above are Trendora decisions, not a claim that FastAPI supplies a body limit by default.

Self-review: P2 backend requirements map to Tasks 1..3. P2 browser input preservation/reload/two-account UI checks are intentionally P2B. P3 origin/import, P4 editorial workflow/comments/activity display, and P5 calendar/publication remain out of this slice. No UI design or product-security completion claim is made by this document.
