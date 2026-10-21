# Trendora shared content planner

Status: design for owner review. No application implementation is authorized by this file alone.

## Purpose

Lex and one marketing colleague need to turn research into posts, share work, optionally review it, and record publication. Lex administers access. The colleague can approve content. Administration and editorial approval are separate permissions.

This document replaces the earlier single-user planner proposal for this feature. It does not replace the existing research contracts or authorize the broader internet-trends product expansion.

## Agreed scope

- Capture external links, hooks, rough notes, and research inspiration.
- Create a post manually without research or AI.
- Save generated ideas and briefs to editable posts while retaining their origin.
- Edit title, platform, caption, hook, creative brief, asset links, and notes.
- Set a planned publishing date. This never schedules an automatic publication.
- View the same records in an inbox, status board, and calendar.
- Assign a post to either member, or leave it unassigned.
- Add comments without replacing post content.
- Record key activity, including actor and timestamp.
- Optionally request approval from the colleague.
- Manually record a published URL and actual publication date.
- Archive and restore posts rather than permanently deleting them in V1.
- Keep all planner operations independent of AI availability.

Defer automatic publishing, platform analytics, uploads, notifications, live co-editing, recurring posts, a full revision editor, company hierarchy, public registration, billing, and multiple organizations.

## Defaults proposed for review

1. One private shared planner; all planner items are visible to its active members from creation. Private-to-shared drafts are not included.
2. Date-only planning and publication dates. Store activity timestamps in UTC; display them in Asia/Jakarta initially. Do not reinterpret a calendar date through UTC midnight.
3. One platform per post. A cross-platform adaptation is another post, not a new publication subsystem.
4. Approval is off by default on each new post.
5. Explicit saving with visible dirty/saving/saved/failed states. No background autosave for V1.

The owner can change these defaults during review. Builders must not invent a hosting or authentication setup to resolve an unanswered deployment question.

## Access model

| Capability | Lex | Colleague |
| --- | --- | --- |
| Read and edit shared posts | Yes | Yes |
| Comment, assign, plan dates, record publication | Yes | Yes |
| Archive and restore | Yes | Yes |
| Manage membership and planner settings | Admin | No |
| Approve, return for changes, waive submitted review | No by default | Approver |

Each person has an individual login. The backend derives identity from verified authentication, never from an actor ID supplied by the browser. An authenticated person without active membership has no planner access.

The first admin is provisioned explicitly by verified identity. Never make the first public signup an administrator. A member cannot grant their own permissions. Ordinary post updates cannot modify membership or approval authority. Preserve at least one active administrator.

Admin authority is an application access-management role, not proof of editorial sign-off. An administrator who can change membership permissions remains a trusted administrator; this is not a tamper-proof separation-of-duties system. Log permission changes and never let an admin-only account approve through the post API.

Revocation must take effect on subsequent protected requests, even if an identity-provider token is still valid. Retain historical actors after deactivation. Do not hard-delete member identities referenced by comments or activity. Reject new assignments to inactive members.

Remote use requires authentication, TLS, protection of both Next.js and FastAPI paths, and no direct backend bypass. Database grants and any database HTTP API are a separate access boundary. Do not expose provider secrets to either browser account. Keep provider setup in server configuration for V1.

The authentication provider and deployment topology require a separate decision before the access milestone starts. Prefer an existing maintained identity service or gateway over a custom password system. No vendor installation or live account provisioning is approved by this document.

## Post and review rules

Post statuses are Idea, Working on it, Ready for review, Approved, and Published. Archive is separate from status.

Store review information separately from status: whether approval is required, the content revision submitted, the revision approved, the approver, and the approval timestamp. This allows a Published post to truthfully retain a missing-approval warning.

- Either editor can create, edit, assign, comment, or move ordinary drafting statuses.
- Either editor can enable approval and submit the current saved content for review.
- Only an active approver can approve or return a submitted post with a note.
- Only an active approver can waive approval after the first submission. Moving back to Working on it does not unlock the approval switch for other editors.
- Before the first submission, either editor can change the optional approval setting.
- Approval applies to an exact content revision. Reject approval if the submitted revision changed before the approval request commits.
- Changes to title, platform, caption, hook, creative brief, or asset links invalidate approval and the submitted revision. Before publication, return the post to Working on it for resubmission.
- Changes to planned date, assignment, internal notes, or comments do not invalidate approval.
- An approver may approve a post they authored in V1; a mandatory two-person sign-off rule is outside scope.
- Record publication only through an explicit operation with a valid HTTP(S) URL and an actual date no later than today in the planner timezone.
- Publication recording must remain possible when approval is missing, because the app records an external fact. Record whether the current content revision had approval at that moment and show Published without approval when required. Later approval cannot retroactively change that historical outcome.
- Editing an already-published record must not erase publication history. Keep its Published status, distinguish changes after publication, and invalidate current approval when content changes.
- A date passing never changes status or sends a post to a platform.

Status changes, approval/waiver, publication, and content updates must use the same backend policy rules regardless of whether initiated from the workspace, board, calendar, or a direct API call.

## Storage and transaction boundaries

Reuse SQLAlchemy, Alembic, PostgreSQL, FastAPI, Next.js, and the existing server proxy pattern. Do not build a workflow engine or a generic permissions framework.

Expected records:

- Planner member: stable verified identity, display name, admin/editor role, independent can-approve flag, active state.
- Planner post: editable fields, status, assignment, planned/publication dates, publication URL, immutable origin, review metadata, created/updated actors and timestamps, archive timestamp, update version and content revision.
- Post comment: post, actor, plain-text body, timestamp. Append-only initially.
- Post activity: post, actor, event type, timestamp, and a small structured description of changed fields or decisions. This is not a full caption-version store.

One deployment holds one shared planner. Do not add organizations, departments, or workspace switching. Final schema and API signatures belong in the implementation plan after design approval.

Each write validates access and input, checks the expected version, writes the post and associated activity in one transaction, and reports success only after commit. A failed transaction must not produce a success message or a partial approval/activity record.

Use an atomic version comparison for post mutations; do not read a version and then update unconditionally. A stale request returns a conflict and leaves the submitted text available for recovery. Concurrent approval and editing cannot leave stale approval on new content.

Creation and other retry-prone append operations need stable request IDs. Repeating the same request returns the same result; reusing the ID with a different payload returns a conflict. This covers uncertain network outcomes as well as double-clicks.

Keep limits on field lengths, list sizes, pagination, and request bodies. Accept only HTTP(S) asset/source/publication links; store and display them without fetching remote previews. Render user text safely. Reject unknown writable fields so clients cannot inject role, creator, approver, origin, or version metadata.

The planner requires a working database, but no AI or research-provider credentials. Preserve unsaved input after an error; do not claim offline persistence.

## Research handoff

Research reports remain snapshots. Planner edits never modify them. Generated fields become ordinary editable draft text, not newly grounded research claims.

An origin identifies the report and selected idea/brief, preserving original generated content, citations, reference identities and source URLs. Indexes alone are insufficient because they have meaning only within a report. A brief import includes its parent idea context. Reuse the existing citation chain rather than reducing it to a citation count.

For a persisted report, resolve the selected item server-side and verify the requesting member may access it. Do not accept browser-provided report IDs or citation claims as proof of provenance.

Fresh generation currently has best-effort persistence. The handoff milestone must fix normalized metadata, return an explicit persistence result and saved ID, and handle failed snapshot saves visibly. Do not rerun AI just to retry a database save. If an unsaved browser-held result is accepted through a retry/import endpoint, label it client-supplied and perform structural validation; do not falsely certify server origin. Never overwrite an existing report snapshot with that payload.

Report access policy must be explicit: planner origin should expose the sources needed by both members without silently publishing unrelated report history. Default proposal: both active members may use research and history in this single shared deployment, subject to owner review before connecting existing stored reports.

Do not use report immutability as justification to retain source API data indefinitely. Check existing source retention requirements before copying raw metadata into planner origins. Prefer stable source identities/links and retain only the evidence needed under the applicable policy. Preserve the user's authored draft independently from expiring source metadata.

## Repository seams and known prerequisites

Baseline reviewed: commit `6b4accc` plus existing user changes. Recheck before implementation.

| Existing file | Relevant behavior |
| --- | --- |
| `src/trendora/research/ideation.py` | Frozen ContentIdea/ContentBrief and citation/index validation. |
| `src/trendora/models/research.py` | Research snapshot ORM model; no mutable post model. |
| `src/trendora/api/app.py` | Report save swallows failures and takes nullable dates from the original request. Routes have no authentication. |
| `src/trendora/api/research_report_models.py` | Generation response has no saved report ID or persistence outcome. |
| `src/trendora/db/session.py` | Existing transaction/session patterns. |
| `web/components/ReportView.tsx` | Shared display for new and historical reports; existing copy actions. |
| `web/components/TurnView.tsx` and `web/app/report/[id]/page.tsx` | Callers of ReportView. |
| `web/lib/report-provenance.ts` | Citation helpers; missing facts become null but are checked against undefined. Fix before reuse. |
| `tests/unit/test_research_report_api.py` | Service overrides do not isolate best-effort persistence. |
| `tests/integration/conftest.py` and integration session fixtures | Test URL selection is not consistently used to construct the engine. |

Keep user changes to `web/components/ResearchForm.tsx`, web package files, AGENTS files, and OpenCode configuration intact. Do not commit or discard them as part of planner work.

## Delivery sequence and acceptance gates

These are milestone boundaries, not a code-ready task plan. Keep their labels separate from the historical M-numbered roadmap until the owner approves numbering.

### P0: Safe test foundation

Repair test isolation before any planner persistence work. Unit tests must mock persistence and reject real database/network access. Integration fixtures must construct their engine from an explicit dedicated test URL, without falling back to application credentials.

Acceptance: existing relevant tests pass with zero attempted real connections; selecting a fake test URL and a different application URL proves engine selection without connecting; no migration runs against the application database.

### P1: Individual login and shared access

After deployment/authentication decisions, implement explicit admin provisioning, active membership, editor access, and separate approval authority. Protect backend and proxy routes. Provide the smallest admin access-management surface; do not build an organization dashboard.

Acceptance: unauthenticated and nonmember requests fail; an editor cannot manage access or grant approval authority; an admin without can-approve cannot approve; deactivation blocks a still-valid login token; no secret appears in browser responses; the last active admin cannot be removed.

### P2: Durable manual planner

Implement post storage/API and a basic inbox/workspace, assignment and archive/restore. Include explicit saving, version conflict handling and idempotent creation.

Acceptance: both accounts can create/edit/read the same post with AI unset; data survives reload; a failed commit retains entered text and returns an error; duplicate requests create one post; concurrent saves do not overwrite silently; unsafe links and server-owned fields are rejected.

### P3: Save research to planner

Fix report persistence metadata/outcome and add Save to Planner for ideas and briefs in fresh and historical report views. Preserve origin and correct the provenance resolver defect.

Acceptance: imported content and citations resolve to the selected report; edits leave the snapshot unchanged; unsaved reports produce an explicit recovery path; forged/unknown report references fail; persistence retry does not invoke AI; old report snapshots still load.

### P4: Review, comments and activity

Implement optional review with the exact rules above, comments and small activity entries. Use atomic version checks for review actions, not just ordinary edits.

Acceptance: Lex cannot approve; the colleague can; an editor cannot disable review after submission by changing status first; content edits invalidate approval; date changes do not; stale approvals fail; concurrent comments remain distinct; failed transactions leave neither partial activity nor approvals.

### P5: Board, calendar and publication

Add views backed by the same post API and explicit publication recording. Start with ordinary controls, not drag-and-drop.

Acceptance: all views agree after refresh; undated ideas remain accessible; dates do not shift across browser timezones; dates passing cause no publication; publication without required approval is flagged; correcting a published post preserves historical approval/publication events; keyboard, narrow-screen, loading, empty, error and conflict states work.

### P6: Two-account release check

Exercise both accounts against a dedicated test environment, review security boundaries and verify backup/restore before real drafts. Update deployment instructions and actual feature status only after verification.

Acceptance: complete manual and research-import workflows pass; revoked accounts cannot access drafts through either API surface; AI/router outage does not affect planner operations; no application database is used by automated tests; no live deployment occurs without owner approval.

## Separate provider workstream

The builder model is not the application's AI provider. Selecting Muse or MiMo to write code must not modify `TRENDORA_AI_*` or install/configure 9router.

Keep 9router work in a separate specification and change set. Preserve the earlier requirements: full Chat Completions endpoint, qualified free-only model allowlist, exact schema tests, mandatory grounding checks, requested alias separated from unverified reported upstream identity, bounded gateway and application attempts, no paid fallback, protected credentials, and mocked tests before approved live calls. Primary-with-fallback remains the provisional recommendation.

## Decisions before execution

- Where Next.js, FastAPI, and 9router will run, and how both people will reach the app.
- The maintained authentication mechanism appropriate to that deployment.
- Confirmation of shared-from-creation posts, date-only planning, and access to existing research history.
- Antislop timing and visual direction before UI design/implementation. No visual design is delivered by this document.
- Redacted 9router version/combo settings before the separate provider workstream.

## Review checklist

- [x] Separate administration from editorial approval.
- [x] Describe missing-approval publication truthfully.
- [x] Specify version conflicts, retry-safe creation and transaction failures.
- [x] Keep editable posts separate from research snapshots.
- [x] Separate approved scope from proposed defaults and deployment decisions.
- [x] Keep AI/provider work independent from planner saves.
- [ ] Owner reviews this written design.
- [ ] Prepare and review the executable task plan after design approval.

