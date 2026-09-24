export type UiBounds = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

export function parseUiBounds(
  value: string | undefined,
  screenWidth: number,
  screenHeight: number,
): UiBounds | null;
