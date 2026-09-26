import type { UiTreeNode } from "./ui-dump";

export type NierCodeOptions = {
  source: string;
  screenWidth: number;
  screenHeight: number;
};

export type NierCodeResult = {
  code: string;
  canClick: boolean;
  warning: string;
};

export function generateNierCode(
  node: UiTreeNode,
  options: NierCodeOptions,
): NierCodeResult;
