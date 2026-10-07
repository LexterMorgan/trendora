import test from "node:test";
import assert from "node:assert/strict";

import { newRequestId } from "../lib/report-planner-actions.ts";

function withCrypto(value: unknown, run: () => void) {
  const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  Object.defineProperty(globalThis, "crypto", { configurable: true, value });
  try {
    run();
  } finally {
    if (original) Object.defineProperty(globalThis, "crypto", original);
    else Reflect.deleteProperty(globalThis, "crypto");
  }
}

test("request IDs use randomUUID with its crypto receiver when available", () => {
  const secure = {
    randomUUID() {
      assert.equal(this, secure);
      return "a26e12ac-4c03-49ac-86b9-a4c5c25d39a4";
    },
    getRandomValues() {
      assert.fail("randomUUID already supplies secure randomness");
    },
  };
  withCrypto(secure, () => {
    assert.equal(newRequestId(), "a26e12ac-4c03-49ac-86b9-a4c5c25d39a4");
  });
});

test("getRandomValues supplies valid distinct v4 IDs for independent operations", () => {
  let calls = 0;
  const secure = {
    getRandomValues(bytes: Uint8Array) {
      assert.equal(this, secure);
      assert.equal(bytes.length, 16);
      bytes.fill(++calls);
      return bytes;
    },
  };
  withCrypto(secure, () => {
    const first = newRequestId();
    const second = newRequestId();
    const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
    assert.match(first, uuidV4);
    assert.match(second, uuidV4);
    assert.notEqual(first, second);
    assert.equal(calls, 2);
  });
});

test("a non-callable randomUUID still uses the secure byte fallback", () => {
  withCrypto({ randomUUID: undefined, getRandomValues: (bytes: Uint8Array) => bytes.fill(255) }, () => {
    assert.equal(newRequestId(), "ffffffff-ffff-4fff-bfff-ffffffffffff");
  });
});

test("missing or failing secure randomness gives a clear refusal", () => {
  const unavailable = [
    undefined,
    {},
    { getRandomValues: undefined },
    { getRandomValues() { throw new Error("randomness unavailable"); } },
    { randomUUID() { throw new Error("randomness unavailable"); } },
  ];
  for (const source of unavailable) {
    withCrypto(source, () => {
      assert.throws(newRequestId, {
        message: "Secure randomness is unavailable. This action was not sent. Use a browser with Web Crypto enabled.",
      });
    });
  }
});
