import assert from "node:assert/strict";
import test from "node:test";
import { parseUiBounds } from "../src/lib/ui-bounds.mjs";

test("parses UIAutomator bounds and clips them to the screenshot", () => {
  assert.deepEqual(parseUiBounds("[-10, 20][40, 120]", 100, 80), {
    left: 0,
    top: 20,
    right: 40,
    bottom: 80,
    width: 40,
    height: 60,
  });
});

test("rejects malformed and invisible bounds", () => {
  assert.equal(parseUiBounds("[1,2][x,4]", 100, 100), null);
  assert.equal(parseUiBounds("[20,20][10,30]", 100, 100), null);
  assert.equal(parseUiBounds("[-20,-20][-1,-1]", 100, 100), null);
});
