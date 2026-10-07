import test from "node:test";
import assert from "node:assert/strict";

import { createSubmitGate } from "../lib/submit-gate.ts";

test("gate blocks a second acquire until released", () => {
  const gate = createSubmitGate();
  assert.equal(gate.isActive(), false);
  assert.equal(gate.acquire(), true);
  assert.equal(gate.isActive(), true);
  assert.equal(gate.acquire(), false, "double click must not double-fire");
  gate.release();
  assert.equal(gate.isActive(), false);
  assert.equal(gate.acquire(), true);
});
