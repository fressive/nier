import assert from "node:assert/strict";
import test from "node:test";
import { mapPreviewPoint } from "../src/lib/screen-coordinates.mjs";

test("maps a downscaled scrcpy frame to device screen pixels", () => {
  const point = mapPreviewPoint({
    clientX: 50,
    clientY: 100,
    bounds: { left: 0, top: 0, width: 100, height: 200 },
    frameWidth: 572,
    frameHeight: 1280,
    screenWidth: 1240,
    screenHeight: 2772,
  });

  assert.deepEqual(point, { x: 620, y: 1386 });
});

test("maps a landscape frame to rotated screen axes", () => {
  const point = mapPreviewPoint({
    clientX: 250,
    clientY: 250,
    bounds: { left: 0, top: 0, width: 500, height: 500 },
    frameWidth: 1280,
    frameHeight: 573,
    screenWidth: 1240,
    screenHeight: 2772,
  });

  assert.deepEqual(point, { x: 1386, y: 620 });
});

test("ignores clicks in the letterbox outside the video frame", () => {
  const point = mapPreviewPoint({
    clientX: 10,
    clientY: 200,
    bounds: { left: 0, top: 0, width: 500, height: 500 },
    frameWidth: 572,
    frameHeight: 1280,
    screenWidth: 1240,
    screenHeight: 2772,
  });

  assert.equal(point, null);
});
