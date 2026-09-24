export type PreviewPointInput = {
  clientX: number;
  clientY: number;
  bounds: { left: number; top: number; width: number; height: number };
  frameWidth: number;
  frameHeight: number;
  screenWidth: number;
  screenHeight: number;
};

export function mapPreviewPoint(input: PreviewPointInput): { x: number; y: number } | null;
