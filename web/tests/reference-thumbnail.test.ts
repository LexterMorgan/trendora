import test from "node:test";
import assert from "node:assert/strict";

import {
  YOUTUBE_THUMBNAIL_HEIGHT,
  YOUTUBE_THUMBNAIL_MIN_WIDTH,
  YOUTUBE_THUMBNAIL_WIDTH,
  youtubeThumbnailCandidates,
} from "../lib/report-reference.ts";

test("lists first-party candidates highest resolution first for a valid id", () => {
  assert.deepEqual(youtubeThumbnailCandidates({ source_code: "youtube", content_external_id: "dQw4w9WgXcQ" }), [
    "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
  ]);
  assert.equal(YOUTUBE_THUMBNAIL_WIDTH, 320);
  assert.equal(YOUTUBE_THUMBNAIL_HEIGHT, 180);
  assert.equal(YOUTUBE_THUMBNAIL_MIN_WIDTH, 200);
});

test("returns no candidates for non-YouTube sources", () => {
  assert.deepEqual(youtubeThumbnailCandidates({ source_code: "public_web", content_external_id: "dQw4w9WgXcQ" }), []);
  assert.deepEqual(youtubeThumbnailCandidates({ source_code: "facebook", content_external_id: "123" }), []);
});

test("rejects ids that are not the exact YouTube video id shape", () => {
  const rejected = ["", "short", "dQw4w9WgXcQextra", "../evil", "dQw4w9WgX Q", "dQw4w9WgXcQ/../../x"];
  for (const id of rejected) {
    assert.deepEqual(youtubeThumbnailCandidates({ source_code: "youtube", content_external_id: id }), [], id);
  }
});

test("only the fixed i.ytimg.com host is ever produced", () => {
  for (const url of youtubeThumbnailCandidates({ source_code: "youtube", content_external_id: "dQw4w9WgXcQ" })) {
    assert.equal(new URL(url).host, "i.ytimg.com");
    assert.equal(new URL(url).protocol, "https:");
  }
});
