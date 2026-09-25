import { parseUiBounds } from "./ui-bounds.mjs";

function pythonString(value) {
  return JSON.stringify(value)
    .replaceAll("\u2028", "\\u2028")
    .replaceAll("\u2029", "\\u2029");
}

function nodeTextContent(node, source) {
  const attributeText = node.attributes.text?.trim() ?? "";
  const ownText = source === "WEBVIEW_DEVTOOLS"
    ? node.text.trim()
    : attributeText || node.text.trim();
  return [ownText, ...node.children.map((child) => nodeTextContent(child, source))]
    .filter(Boolean)
    .join(" ");
}

function isTrue(value) {
  return typeof value === "string" && ["1", "true", "yes", "y", "on"].includes(value.trim().toLowerCase());
}

function isFalse(value) {
  return typeof value === "string" && ["0", "false", "no", "n", "off"].includes(value.trim().toLowerCase());
}

function readBounds(value) {
  if (typeof value !== "string") return null;
  const match = value.trim().match(/^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$/);
  return match ? match.slice(1).map(Number) : null;
}

export function generateNierCode(node, { source, screenWidth, screenHeight }) {
  const attributes = node.attributes;
  const text = nodeTextContent(node, source);
  const resourceId = attributes["resource-id"] || attributes.id || "";
  const className = attributes.class || "";
  const contentDesc = attributes["content-desc"] || attributes["aria-label"] || attributes.title || "";
  const selectors = [
    ["text", text],
    ["resource_id", resourceId],
    ["class_name", className],
    ["content_desc", contentDesc],
    ["tag", node.tag],
  ].filter(([, value]) => value);

  const visible = attributes["visible-to-user"] ?? attributes.visible;
  const rawBounds = readBounds(attributes.bounds);
  const clippedBounds = parseUiBounds(attributes.bounds, screenWidth, screenHeight);
  const usableBounds = Boolean(
    rawBounds
      && clippedBounds
      && clippedBounds.width >= 12
      && clippedBounds.height >= 12
      && rawBounds[0] >= 0
      && rawBounds[1] >= 0
      && rawBounds[2] <= screenWidth
      && rawBounds[3] <= screenHeight
      && rawBounds[2] - rawBounds[0] >= 12
      && rawBounds[3] - rawBounds[1] >= 12,
  );
  const canClick = isTrue(attributes.clickable) && !isFalse(visible) && usableBounds;
  const preferWebView = source === "WEBVIEW_DEVTOOLS" ? "True" : "False";
  const lines = [
    "from nier import connect",
    "",
    'with connect("config/nier.yaml") as phone:',
    `    ui = phone.parse_uidump(prefer_webview=${preferWebView})`,
    "    matches = ui.find_all(",
    ...selectors.map(([key, value]) => `        ${key}=${pythonString(value)},`),
    "    )",
    ...(rawBounds
      ? [
        `    matches = [node for node in matches if node.bounds == (${rawBounds.join(", ")})]`,
      ]
      : []),
    "    if len(matches) != 1:",
    '        raise LookupError(f"Expected one matching UI node, found {len(matches)}")',
    "    component = phone.widget(matches[0])",
  ];

  if (canClick) {
    lines.push("    component.click()");
  } else {
    lines.push("    print(component.to_dict())");
  }

  let warning = "";
  if (!isTrue(attributes.clickable)) {
    warning = "节点没有 clickable=true 标记；生成代码只定位并打印节点，不会点击。";
  } else if (isFalse(visible)) {
    warning = "节点被标记为不可见；生成代码只定位并打印节点，不会点击。";
  } else if (!usableBounds) {
    warning = "节点没有有效的屏幕 bounds；生成代码只定位并打印节点，不会点击。";
  }

  return { code: lines.join("\n"), canClick, warning };
}
