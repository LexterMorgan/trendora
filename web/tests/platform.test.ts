import test from "node:test";
import assert from "node:assert/strict";

import { platformForUrl, platformLabel } from "../lib/platform.ts";

test("labels known platforms and explicit aliases", () => {
  assert.equal(platformLabel("https://www.reddit.com/r/x"), "Reddit · via web search");
  assert.equal(platformForUrl("https://twitter.com/u/status/1"), "X");
  assert.equal(platformForUrl("https://x.com/u/1"), "X");
  assert.equal(platformForUrl("https://old.reddit.com/r/x"), "Reddit");
  assert.equal(platformForUrl("https://m.facebook.com/page"), "Facebook");
  assert.equal(platformForUrl("https://www.linkedin.com/posts/x"), "LinkedIn");
});

test("hostname boundaries: a suffix-spoofed host is never a platform", () => {
  assert.equal(platformForUrl("https://reddit.com.evil.example/r/x"), null);
  assert.equal(platformForUrl("https://evilreddit.com/r/x"), null);
  assert.equal(platformForUrl("https://x.com.evil.example/1"), null);
});

test("short links and non-platform hosts are not labelled", () => {
  for (const url of ["https://redd.it/x", "https://t.co/x", "https://lnkd.in/x", "https://example.com/x", null, undefined, "not a url"]) {
    assert.equal(platformLabel(url), null, String(url));
  }
});
