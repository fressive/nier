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

export function parseUiNodeBounds(
  attributes: Record<string, string>,
  screenWidth: number,
  screenHeight: number,
): UiBounds | null;

export function uiNodeClickable(attributes: Record<string, string>): string | undefined;

export function uiNodeVisible(attributes: Record<string, string>): string | undefined;
