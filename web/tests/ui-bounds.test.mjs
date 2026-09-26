import assert from "node:assert/strict";
import test from "node:test";
import { parseUiBounds, parseUiNodeBounds, uiNodeClickable, uiNodeVisible } from "../src/lib/ui-bounds.mjs";

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

test("parses mapped WebView screen bounds and normalized interaction metadata", () => {
  const attributes = {
    "data-nier-screen-bounds": "[12, 24][212, 124]",
    "data-nier-clickable": "true",
    "data-nier-visible": "true",
  };

  assert.deepEqual(parseUiNodeBounds(attributes, 300, 200), {
    left: 12,
    top: 24,
    right: 212,
    bottom: 124,
    width: 200,
    height: 100,
  });
  assert.equal(uiNodeClickable(attributes), "true");
  assert.equal(uiNodeVisible(attributes), "true");
});

test("prefers mapped screen metadata and falls back to UIAutomator attributes", () => {
  assert.deepEqual(
    parseUiNodeBounds({ bounds: "[1,2][11,12]" }, 100, 100),
    parseUiBounds("[1,2][11,12]", 100, 100),
  );
  assert.deepEqual(
    parseUiNodeBounds({ bounds: "[1,2][11,12]", "data-nier-screen-bounds": "[5,6][25,36]" }, 100, 100),
    parseUiBounds("[5,6][25,36]", 100, 100),
  );
  assert.equal(uiNodeClickable({ clickable: "false" }), "false");
  assert.equal(uiNodeVisible({ visible: "false" }), "false");
});
