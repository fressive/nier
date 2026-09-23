import type { Node } from "@xyflow/react";

export type RunStatus =
  | "idle"
  | "starting"
  | "running"
  | "stopping"
  | "completed"
  | "stopped"
  | "failed";

export type DebugCommand = "continue" | "step" | "step_into" | "step_out";
export type DebugState = "inactive" | "running" | "paused" | "finished";

export type ScriptInfo = { path: string; name: string; description: string };
export type DebugFrame = { file: string; line: number; function: string };
export type DebugLocation = {
  step_id: number | null;
  category: string;
  message: string;
  details: Record<string, unknown>;
  depth: number;
  file: string;
  line: number;
  function: string;
  stack: DebugFrame[];
};

export type RunState = {
  id: string | null;
  script: string | null;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  error?: string | null;
  debug: boolean;
  debug_state: DebugState;
  debug_location: DebugLocation | null;
};

export type WebEvent = {
  type: string;
  event_id: number;
  timestamp: string;
  run_id?: string;
  script?: string;
  debug?: boolean;
  category?: string;
  level?: string;
  message?: string;
  details?: Record<string, unknown>;
  step_id?: number | null;
  stream?: string;
  text?: string;
  status?: string;
  exit_code?: number | null;
  error?: string | null;
  command?: DebugCommand;
  file?: string;
  line?: number;
  function?: string;
  depth?: number;
  stack?: DebugFrame[];
};

export type ApiState = { run: RunState; events: WebEvent[] };

export type StepNodeData = {
  event: WebEvent;
  index: number;
  selected: boolean;
  active: boolean;
  onSelect: (id: number) => void;
};

export type StepNodeType = Node<StepNodeData, "step">;

export const initialRun: RunState = {
  id: null,
  script: null,
  status: "idle",
  started_at: null,
  finished_at: null,
  exit_code: null,
  debug: false,
  debug_state: "inactive",
  debug_location: null,
};
