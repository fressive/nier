import assert from "node:assert/strict";
import test from "node:test";
import { generateNierCode } from "../src/lib/nier-codegen.mjs";

const options = { source: "UIAUTOMATOR", screenWidth: 1080, screenHeight: 2400 };

test("generates a checked Nier widget click for a uniquely described clickable node", () => {
  const result = generateNierCode({
    tag: "node",
    attributes: {
      text: "进入设置",
      "resource-id": "app:id/settings",
      class: "android.widget.Button",
      clickable: "true",
      "visible-to-user": "true",
      bounds: "[10,20][110,80]",
    },
    text: "",
    children: [],
  }, options);

  assert.equal(result.canClick, true);
  assert.equal(result.warning, "");
  assert.match(result.code, /phone\.parse_uidump\(prefer_webview=False\)/);
  assert.match(result.code, /text="进入设置"/);
  assert.match(result.code, /resource_id="app:id\/settings"/);
  assert.match(result.code, /if not ui\.match\(\*\*query\):/);
  assert.match(result.code, /node = ui\.find\(\*\*query\)/);
  assert.match(result.code, /node\.bounds != \(10, 20, 110, 80\)/);
  assert.match(result.code, /phone\.widget\(node\)/);
  assert.doesNotMatch(result.code, /find_all/);
  assert.match(result.code, /component\.click\(\)/);
});

test("does not generate an action for WebView nodes without click metadata", () => {
  const result = generateNierCode({
    tag: "div",
    attributes: { id: "settings", "aria-label": "Settings" },
    text: "Settings",
    children: [],
  }, { ...options, source: "WEBVIEW_DEVTOOLS" });

  assert.equal(result.canClick, false);
  assert.match(result.code, /prefer_webview=True/);
  assert.match(result.code, /content_desc="Settings"/);
  assert.match(result.code, /print\(component\.to_dict\(\)\)/);
  assert.doesNotMatch(result.code, /component\.click\(\)/);
  assert.match(result.warning, /clickable/);
});

test("generates a guarded click for a mapped clickable WebView node", () => {
  const result = generateNierCode({
    tag: "button",
    attributes: {
      "aria-label": "进入设置",
      "data-nier-screen-bounds": "[10,20][110,80]",
      "data-nier-clickable": "true",
      "data-nier-visible": "true",
    },
    text: "进入设置",
    children: [],
  }, { ...options, source: "WEBVIEW_DEVTOOLS" });

  assert.equal(result.canClick, true);
  assert.equal(result.warning, "");
  assert.match(result.code, /prefer_webview=True/);
  assert.match(result.code, /node\.bounds != \(10, 20, 110, 80\)/);
  assert.match(result.code, /component\.click\(\)/);
});

test("does not generate a WebView click for mapped invisible nodes", () => {
  const result = generateNierCode({
    tag: "button",
    attributes: {
      "data-nier-screen-bounds": "[10,20][110,80]",
      "data-nier-clickable": "true",
      "data-nier-visible": "false",
    },
    text: "Continue",
    children: [],
  }, { ...options, source: "WEBVIEW_DEVTOOLS" });

  assert.equal(result.canClick, false);
  assert.match(result.warning, /不可见/);
  assert.doesNotMatch(result.code, /component\.click\(\)/);
});

test("does not generate an action when a clickable node has no screen bounds", () => {
  const result = generateNierCode({
    tag: "node",
    attributes: { text: "Continue", clickable: "true" },
    text: "",
    children: [],
  }, options);

  assert.equal(result.canClick, false);
  assert.match(result.warning, /bounds/);
  assert.doesNotMatch(result.code, /component\.click\(\)/);
});

test("does not generate a click for bounds extending beyond the screen", () => {
  const result = generateNierCode({
    tag: "node",
    attributes: { text: "Continue", clickable: "true", bounds: "[1000,20][1200,80]" },
    text: "",
    children: [],
  }, options);

  assert.equal(result.canClick, false);
  assert.match(result.warning, /bounds/);
  assert.doesNotMatch(result.code, /component\.click\(\)/);
});

test("escapes selected text as a Python string literal", () => {
  const result = generateNierCode({
    tag: "node",
    attributes: { text: 'Say "hello"\nnow' },
    text: "",
    children: [],
  }, options);

  assert.match(result.code, /text="Say \\\"hello\\\"\\nnow"/);
});
