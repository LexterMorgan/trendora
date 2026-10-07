import test from "node:test";
import assert from "node:assert/strict";
import { ResearchApiError } from "../lib/api.ts";
import { blankPlannerDraft, draftFromPost, type PlannerPost } from "../lib/planner-api.ts";
import { createPlannerDraft, type PlannerDraftApi } from "../lib/planner-draft.ts";

const post: PlannerPost = { ...blankPlannerDraft(), id: "fictional-post", title: "Original", version: 1, content_revision: 1, created_by: "fictional-member", updated_by: "fictional-member", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", archived_at: null };
const network = () => new ResearchApiError("backend_unreachable", "fictional lost acknowledgement", "network");
const conflict = (code = "planner_version_conflict") => new ResearchApiError(code, "fictional conflict", "unknown", 409);
function fake(overrides: Partial<PlannerDraftApi> = {}): PlannerDraftApi {
  return {
    get: async () => ({ ...post, asset_links: [] }), create: async () => ({ id: post.id }),
    update: async (id, draft, version) => ({ ...post, ...draft, id, version: version + 1 }),
    archive: async (id, version) => ({ ...post, id, version: version + 1, archived_at: "2026-10-01T01:00:00Z" }),
    restore: async (id, version) => ({ ...post, id, version: version + 1, archived_at: null }),
    ...overrides,
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

test("uncertain creation retries the frozen original snapshot and key despite newer edits", async () => {
  const calls: unknown[] = [];
  let count = 0;
  const store = createPlannerDraft({ requestId: () => "stable-key", api: fake({
    create: async (fields, key) => {
      assert.ok(Object.isFrozen(fields));
      assert.ok(Object.isFrozen(fields.asset_links));
      calls.push({ ...fields, request_id: key });
      if (++count === 1) throw network();
      return { id: post.id };
    },
    get: async () => ({ ...post, title: "Submitted" }),
  }) });
  store.edit({ ...blankPlannerDraft(), title: "Submitted", caption: "one\ntwo" });
  await store.create();
  assert.equal(store.getSnapshot().phase, "uncertain");
  assert.equal(store.getSnapshot().acknowledged, null);
  store.edit({ ...store.getSnapshot().draft, title: "New local edit" });
  await store.create();
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(store.getSnapshot().acknowledged?.title, "Submitted");
  assert.equal(store.getSnapshot().draft.title, "New local edit");
  assert.equal(store.getSnapshot().dirty, true);
});

test("acknowledged creation with failed GET keeps ID and retries only GET without losing later edits", async () => {
  let creates = 0, reads = 0;
  const store = createPlannerDraft({ api: fake({ create: async () => { creates++; return { id: post.id }; }, get: async () => { if (++reads === 1) throw network(); return post; } }) });
  store.edit({ ...blankPlannerDraft(), title: "Original" });
  await store.create();
  assert.equal(store.getSnapshot().knownId, post.id);
  assert.equal(store.getSnapshot().pendingCreate, null);
  assert.equal(store.getSnapshot().acknowledged, null);
  store.edit({ ...store.getSnapshot().draft, notes: "Retain this after retry" });
  await store.save();
  assert.equal(creates, 1);
  assert.equal(reads, 2);
  assert.equal(store.getSnapshot().draft.notes, "Retain this after retry");
  assert.equal(store.getSnapshot().dirty, true);
});

test("definite creation validation failure retains text and allows a new corrected attempt", async () => {
  const keys: string[] = [];
  let sequence = 0;
  const store = createPlannerDraft({ requestId: () => `key-${++sequence}`, api: fake({ create: async (_fields, key) => { keys.push(key); if (keys.length === 1) throw new ResearchApiError("planner_assignee_invalid", "inactive", "invalid_request", 422); return { id: post.id }; } }) });
  store.edit({ ...blankPlannerDraft(), title: "Original" });
  await store.create();
  assert.equal(store.getSnapshot().draft.title, "Original");
  assert.equal(store.getSnapshot().pendingCreate, null);
  await store.create();
  assert.deepEqual(keys, ["key-1", "key-2"]);
});

test("creation key conflict and invalid acknowledgements retain the unresolved attempt", async () => {
  for (const error of [conflict("planner_create_conflict"), new ResearchApiError("invalid_response", "unreadable", "unknown", 201), new ResearchApiError("data_unavailable", "unavailable", "unavailable", 503)]) {
    const store = createPlannerDraft({ api: fake({ create: async () => { throw error; } }) });
    store.edit({ ...blankPlannerDraft(), title: "Original" });
    await store.create();
    assert.equal(store.getSnapshot().phase, "uncertain");
    assert.ok(store.getSnapshot().pendingCreate);
    assert.equal(store.getSnapshot().error?.code, error.code);
  }
});

test("overlapping creation and update submissions are blocked synchronously", async () => {
  const waiting = deferred<{ id: string }>();
  let calls = 0;
  const store = createPlannerDraft({ api: fake({ create: async () => { calls++; return waiting.promise; } }) });
  store.edit({ ...blankPlannerDraft(), title: "Original" });
  const first = store.create();
  await store.create();
  await store.save();
  assert.equal(calls, 1);
  assert.equal(store.getSnapshot().busy, true);
  waiting.resolve({ id: post.id });
  await first;
  assert.equal(store.getSnapshot().busy, false);
});

test("failed validation saves retain local fields and confirmed baseline", async () => {
  const store = createPlannerDraft({ post, api: fake({ update: async () => { throw new ResearchApiError("invalid_request", "fictional rejection", "invalid_request", 422); } }) });
  store.edit({ ...draftFromPost(post), caption: "Changed\ncaption" });
  await store.save();
  assert.equal(store.getSnapshot().draft.caption, "Changed\ncaption");
  assert.equal(store.getSnapshot().acknowledged?.caption, "");
  assert.equal(store.getSnapshot().phase, "failed");
  assert.equal(store.getSnapshot().dirty, true);
  assert.equal(store.getSnapshot().requiresReconcile, false);
});

test("version conflicts require explicit recovery and never automatically resubmit", async () => {
  let writes = 0;
  const latest = { ...post, title: "Other editor", version: 2 };
  const store = createPlannerDraft({ post, api: fake({ update: async () => { writes++; throw conflict(); }, get: async () => latest }) });
  store.edit({ ...draftFromPost(post), title: "Local editor" });
  await store.save();
  await store.save();
  assert.equal(writes, 1);
  await store.reconcile();
  assert.equal(store.getSnapshot().acknowledged?.version, 1);
  assert.equal(store.getSnapshot().recovery?.version, 2);
  assert.equal(store.getSnapshot().draft.title, "Local editor");
  store.recover("local");
  assert.equal(store.getSnapshot().acknowledged?.version, 2);
  assert.equal(store.getSnapshot().draft.title, "Local editor");
  assert.equal(store.getSnapshot().dirty, true);
  assert.equal(writes, 1);
});

test("explicit server recovery discards local changes only after a latest snapshot is available", async () => {
  const latest = { ...post, title: "Other editor", version: 2 };
  const store = createPlannerDraft({ post, api: fake({ update: async () => { throw conflict(); }, get: async () => latest }) });
  store.edit({ ...draftFromPost(post), title: "Local editor" });
  await store.save();
  store.recover("server");
  assert.equal(store.getSnapshot().draft.title, "Local editor");
  await store.reconcile();
  store.recover("server");
  assert.equal(store.getSnapshot().draft.title, "Other editor");
  assert.equal(store.getSnapshot().dirty, false);
});

test("lost update/archive/restore acknowledgements block writes until server reconciliation", async () => {
  for (const action of ["update", "archive", "restore"] as const) {
    let writes = 0, reads = 0;
    const initial = action === "restore" ? { ...post, archived_at: "2026-10-01T00:00:00Z" } : post;
    const store = createPlannerDraft({ post: initial, api: fake({ [action]: async () => { writes++; throw network(); }, get: async () => { if (++reads === 1) throw network(); return { ...post, version: 2 }; } }) });
    store.edit({ ...draftFromPost(initial), title: "Keep local text" });
    await (action === "update" ? store.save() : store[action]());
    assert.equal(store.getSnapshot().phase, "uncertain");
    await store.save();
    await store.archive();
    assert.equal(writes, 1);
    await store.reconcile();
    assert.equal(store.getSnapshot().requiresReconcile, true);
    assert.equal(store.getSnapshot().draft.title, "Keep local text");
    await store.reconcile();
    assert.equal(store.getSnapshot().requiresReconcile, true);
    store.recover("local");
    assert.equal(store.getSnapshot().requiresReconcile, false);
    assert.equal(store.getSnapshot().acknowledged?.version, 2);
    assert.equal(store.getSnapshot().draft.title, "Keep local text");
  }
});

test("late saves acknowledge their snapshot without overwriting newer local edits", async () => {
  const waiting = deferred<PlannerPost>();
  const store = createPlannerDraft({ post, api: fake({ update: async () => waiting.promise }) });
  store.edit({ ...draftFromPost(post), title: "Submitted" });
  const saving = store.save();
  store.edit({ ...store.getSnapshot().draft, title: "Newer edit" });
  waiting.resolve({ ...post, title: "Submitted", version: 2 });
  await saving;
  assert.equal(store.getSnapshot().acknowledged?.title, "Submitted");
  assert.equal(store.getSnapshot().draft.title, "Newer edit");
  assert.equal(store.getSnapshot().dirty, true);
});

test("late reads cannot overwrite newer local fields", async () => {
  const waiting = deferred<PlannerPost>();
  const store = createPlannerDraft({ api: fake({ get: async () => waiting.promise }) });
  const loading = store.load(post.id);
  store.edit({ ...blankPlannerDraft(), title: "Entered before read finished" });
  waiting.resolve(post);
  await loading;
  assert.equal(store.getSnapshot().draft.title, "Entered before read finished");
  assert.equal(store.getSnapshot().acknowledged?.id, post.id);
});

test("logout/account switches ignore pending results and disposal purges all draft state", async () => {
  for (const request of ["read", "write"] as const) {
    const waiting = deferred<PlannerPost>();
    let current = true;
    const store = createPlannerDraft({ post, isCurrentSession: () => current, api: fake({ get: async () => waiting.promise, update: async () => waiting.promise }) });
    store.edit({ ...draftFromPost(post), notes: "Private fictional draft" });
    const pending = request === "read" ? store.load(post.id) : store.save();
    current = false;
    store.dispose();
    waiting.resolve({ ...post, notes: "Old session response", version: 2 });
    await pending;
    assert.deepEqual(store.getSnapshot().draft, blankPlannerDraft());
    assert.equal(store.getSnapshot().knownId, null);
    assert.equal(store.getSnapshot().acknowledged, null);
  }
});

test("dispose and resubscribe support StrictMode without accepting the first mount response", async () => {
  const first = deferred<PlannerPost>();
  let reads = 0;
  const store = createPlannerDraft({ api: fake({ get: async () => ++reads === 1 ? first.promise : { ...post, version: 2 } }) });
  const unsubscribe = store.subscribe(() => {});
  const oldRead = store.load(post.id);
  unsubscribe();
  store.dispose();
  store.subscribe(() => {});
  await store.load(post.id);
  first.resolve(post);
  await oldRead;
  assert.equal(store.getSnapshot().acknowledged?.version, 2);
  assert.equal(store.getSnapshot().busy, false);
});

test("archive/restore acknowledgements and archived rejection stay distinct", async () => {
  const store = createPlannerDraft({ post, api: fake() });
  await store.archive();
  assert.ok(store.getSnapshot().acknowledged?.archived_at);
  await store.restore();
  assert.equal(store.getSnapshot().acknowledged?.archived_at, null);
  assert.equal(store.getSnapshot().acknowledged?.version, 3);
  const rejected = createPlannerDraft({ post, api: fake({ update: async () => { throw conflict("planner_post_archived"); } }) });
  rejected.edit({ ...draftFromPost(post), notes: "Keep this" });
  await rejected.save();
  assert.equal(rejected.getSnapshot().error?.code, "planner_post_archived");
  assert.equal(rejected.getSnapshot().draft.notes, "Keep this");
  assert.equal(rejected.getSnapshot().requiresReconcile, true);
});

test("restore preserves edits made during an archive acknowledgement", async () => {
  const waiting = deferred<PlannerPost>();
  const store = createPlannerDraft({ post, api: fake({ archive: async () => waiting.promise }) });
  const archiving = store.archive();
  store.edit({ ...draftFromPost(post), caption: "New text while archive is pending" });
  waiting.resolve({ ...post, archived_at: "2026-10-01T01:00:00Z", version: 2 });
  await archiving;
  assert.equal(store.getSnapshot().dirty, true);
  await store.restore();
  assert.equal(store.getSnapshot().draft.caption, "New text while archive is pending");
  assert.equal(store.getSnapshot().acknowledged?.caption, "");
  assert.equal(store.getSnapshot().dirty, true);
});

test("restore preserves edits explicitly recovered after an archived conflict", async () => {
  const archived = { ...post, archived_at: "2026-10-01T01:00:00Z", version: 2 };
  const store = createPlannerDraft({ post, api: fake({ update: async () => { throw conflict("planner_post_archived"); }, get: async () => archived }) });
  store.edit({ ...draftFromPost(post), notes: "Recovered local text" });
  await store.save();
  await store.reconcile();
  store.recover("local");
  await store.restore();
  assert.equal(store.getSnapshot().draft.notes, "Recovered local text");
  assert.equal(store.getSnapshot().acknowledged?.archived_at, null);
  assert.equal(store.getSnapshot().dirty, true);
});
