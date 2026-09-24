export function mapPreviewPoint({
  clientX,
  clientY,
  bounds,
  frameWidth,
  frameHeight,
  screenWidth,
  screenHeight,
}) {
  const dimensions = [frameWidth, frameHeight, bounds.width, bounds.height, screenWidth, screenHeight];
  const positions = [clientX, clientY, bounds.left, bounds.top];
  if (!dimensions.every((value) => Number.isFinite(value) && value > 0)) return null;
  if (!positions.every(Number.isFinite)) return null;

  const frameAspect = frameWidth / frameHeight;
  const normalAspect = screenWidth / screenHeight;
  const rotatedAspect = screenHeight / screenWidth;
  const rotated = Math.abs(frameAspect - rotatedAspect) < Math.abs(frameAspect - normalAspect);
  const targetWidth = rotated ? screenHeight : screenWidth;
  const targetHeight = rotated ? screenWidth : screenHeight;

  const scale = Math.min(bounds.width / frameWidth, bounds.height / frameHeight);
  const renderedWidth = frameWidth * scale;
  const renderedHeight = frameHeight * scale;
  const left = bounds.left + (bounds.width - renderedWidth) / 2;
  const top = bounds.top + (bounds.height - renderedHeight) / 2;
  const localX = clientX - left;
  const localY = clientY - top;
  if (localX < 0 || localY < 0 || localX >= renderedWidth || localY >= renderedHeight) {
    return null;
  }

  return {
    x: Math.min(targetWidth - 1, Math.floor((localX / renderedWidth) * targetWidth)),
    y: Math.min(targetHeight - 1, Math.floor((localY / renderedHeight) * targetHeight)),
  };
}
