export function parseUiBounds(value, screenWidth, screenHeight) {
  if (typeof value !== "string") return null;
  if (![screenWidth, screenHeight].every((size) => Number.isInteger(size) && size > 0)) {
    return null;
  }

  const match = value.match(/^\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]\s*$/);
  if (!match) return null;
  const [left, top, right, bottom] = match.slice(1).map(Number);
  const clipped = {
    left: Math.max(0, Math.min(screenWidth, left)),
    top: Math.max(0, Math.min(screenHeight, top)),
    right: Math.max(0, Math.min(screenWidth, right)),
    bottom: Math.max(0, Math.min(screenHeight, bottom)),
  };
  if (clipped.right <= clipped.left || clipped.bottom <= clipped.top) return null;
  return {
    ...clipped,
    width: clipped.right - clipped.left,
    height: clipped.bottom - clipped.top,
  };
}

export function parseUiNodeBounds(attributes, screenWidth, screenHeight) {
  if (!attributes || typeof attributes !== "object") return null;
  const value = attributes["data-nier-screen-bounds"] ?? attributes.bounds;
  return parseUiBounds(value, screenWidth, screenHeight);
}

export function uiNodeClickable(attributes) {
  if (!attributes || typeof attributes !== "object") return undefined;
  return attributes["data-nier-clickable"] ?? attributes.clickable;
}

export function uiNodeVisible(attributes) {
  if (!attributes || typeof attributes !== "object") return undefined;
  return attributes["data-nier-visible"]
    ?? attributes["visible-to-user"]
    ?? attributes.visible;
}
