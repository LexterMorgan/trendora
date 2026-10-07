import test from "node:test";
import assert from "node:assert/strict";
import { ResearchApiError, type ApiRuntime } from "../lib/api.ts";
import {
  archivePlannerPost, blankPlannerDraft, createPlannerPost, draftFromPost, formatPlannerTimestamp,
  getPlannerMembers, getPlannerPost, listPlannerPosts, plannerFields, restorePlannerPost,
  updatePlannerPost, validatePlannerDraft, type PlannerPost,
} from "../lib/planner-api.ts";

const runtime: ApiRuntime = { getAccessToken: async () => "fictional-token", getSessionBinding: () => ({ userId: "fictional-member", epoch: 0 }), onUnauthenticated() {}, onAccessDenied() {} };
const post: PlannerPost = { ...blankPlannerDraft(), id: "fictional-post", title: "Draft", caption: "Line one\nLine two", planned_date: "2026-10-01", version: 1, content_revision: 1, created_by: "fictional-member", updated_by: "fictional-member", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", archived_at: null };

async function mocked(status: number, body: unknown, run: (calls: Array<{ path: string; init?: RequestInit }>) => Promise<void>) {
  const original = globalThis.fetch;
  const calls: Array<{ path: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (input, init) => {
    calls.push({ path: String(input), init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  try { await run(calls); } finally { globalThis.fetch = original; }
}

test("planner writes send exact snapshots and no server-owned metadata", async () => {
  for (const status of [201, 200]) {
    await mocked(status, { id: post.id }, async (calls) => {
      assert.deepEqual(await createPlannerPost(post, "request-one", { runtime }), { id: post.id });
      assert.equal(calls[0].path, "/api/planner/posts");
      assert.equal(calls[0].init?.method, "POST");
      assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { ...plannerFields(post), request_id: "request-one" });
    });
  }
  await mocked(200, post, async (calls) => {
    await updatePlannerPost(post.id, post, 4, { runtime });
    assert.equal(calls[0].init?.method, "PUT");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { ...plannerFields(post), status: "idea", expected_version: 4 });
    assert.equal((calls[0].init?.headers as Headers).get("authorization"), "Bearer fictional-token");
    assert.equal(calls[0].init?.cache, "no-store");
  });
});

test("archive and restore send only expected_version", async () => {
  await mocked(200, post, async (calls) => {
    await archivePlannerPost(post.id, 2, { runtime });
    await restorePlannerPost(post.id, 3, { runtime });
    assert.deepEqual(calls.map((call) => call.path), [`/api/planner/posts/${post.id}/archive`, `/api/planner/posts/${post.id}/restore`]);
    assert.deepEqual(calls.map((call) => JSON.parse(String(call.init?.body))), [{ expected_version: 2 }, { expected_version: 3 }]);
  });
});

test("planner client preserves rejection codes and status", async () => {
  for (const [status, code] of [[409, "planner_version_conflict"], [409, "planner_create_conflict"], [409, "planner_post_archived"], [413, "planner_request_too_large"], [422, "planner_assignee_invalid"], [503, "data_unavailable"]] as const) {
    await mocked(status, { error: { code, message: "fictional rejection" } }, async () => {
      await assert.rejects(updatePlannerPost(post.id, post, 1, { runtime }), (error: unknown) => error instanceof ResearchApiError && error.code === code && error.status === status);
    });
  }
});

test("planner reads use fixed same-origin paths with bounded pagination", async () => {
  await mocked(200, [post], async (calls) => {
    await listPlannerPosts({ archived: true, limit: 25, offset: 50, runtime });
    assert.equal(calls[0].path, "/api/planner/posts?archived=true&limit=25&offset=50");
    await assert.rejects(listPlannerPosts({ limit: 101, runtime }), /valid planner page/);
    await assert.rejects(listPlannerPosts({ offset: -1, runtime }), /valid planner page/);
    assert.equal(calls.length, 1);
  });
  await mocked(200, post, async (calls) => {
    await getPlannerPost("a/b", { runtime });
    assert.equal(calls[0].path, "/api/planner/posts/a%2Fb");
  });
  await mocked(200, [{ user_id: "fictional-member", email: "fictional@example.test" }], async (calls) => {
    await getPlannerMembers({ runtime });
    assert.equal(calls[0].path, "/api/planner/members");
  });
});

test("unreadable acknowledgements never become usable snapshots", async () => {
  await mocked(200, { id: post.id }, async () => {
    await assert.rejects(getPlannerPost(post.id, { runtime }), (error: unknown) => error instanceof ResearchApiError && error.code === "invalid_response");
  });
  await mocked(201, {}, async () => {
    await assert.rejects(createPlannerPost(post, "request", { runtime }), /unreadable planner response/);
  });
  await mocked(200, { ...post, updated_at: "not a timestamp" }, async () => {
    await assert.rejects(getPlannerPost(post.id, { runtime }), /unreadable planner response/);
  });
});

test("validation preserves multiline text, blank optional fields, and historical UUID assignment", () => {
  const draft = draftFromPost(post);
  draft.assignee_id = "00000000-0000-4000-8000-000000000099";
  assert.deepEqual(validatePlannerDraft(draft), {});
  assert.equal(plannerFields(draft).caption, "Line one\nLine two");
  assert.equal(plannerFields(draft).platform, "");
  assert.equal(validatePlannerDraft({ ...draft, title: " " }).title, "Enter a title.");
  assert.ok(validatePlannerDraft({ ...draft, hook: "x".repeat(1001) }).hook);
  assert.deepEqual(validatePlannerDraft({ ...draft, title: "🎯".repeat(200) }), {});
  for (const link of ["ftp://example.test/a", "https://user:pass@example.test/a", "https://@example.test/a", "javascript:alert(1)", "https://example.test/a b"]) {
    assert.ok(validatePlannerDraft({ ...draft, asset_links: [link] }).asset_links, link);
  }
  assert.deepEqual(validatePlannerDraft({ ...draft, asset_links: ["https://example.test/asset"] }), {});
});

test("calendar dates stay unchanged across timezones and activity uses Jakarta", () => {
  const previous = process.env.TZ;
  try {
    for (const timezone of ["Pacific/Honolulu", "Asia/Jakarta", "Pacific/Auckland"]) {
      process.env.TZ = timezone;
      assert.equal(plannerFields(post).planned_date, "2026-10-01");
      assert.deepEqual(validatePlannerDraft({ ...post, planned_date: "2028-02-29" }), {});
      for (const invalid of ["2026-02-29", "2026-13-01", "2026-01-00", "0000-01-01", "2026-10-01T00:00:00Z"]) assert.ok(validatePlannerDraft({ ...post, planned_date: invalid }).planned_date);
      assert.equal(formatPlannerTimestamp("2026-10-01T23:00:00Z"), "2 Oct 2026, 06:00");
    }
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});
