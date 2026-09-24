import type { RunState, WebEvent } from "../types";

export function localTime(value?: string | null) {
  if (!value) return "--:--:--";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "--:--:--"
    : date.toLocaleTimeString("zh-CN", { hour12: false });
}

function shortName(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function eventTitle(event: WebEvent) {
  const details = event.details ?? {};
  const action = details.action ?? details.operation ?? details.name ?? details.provider;
  const message = event.message || event.category || "Event";
  return action ? `${shortName(String(message))} · ${String(action)}` : shortName(message);
}

export function eventSubtitle(event: WebEvent) {
  const details = event.details ?? {};
  const status = details.status;
  const method = details.method;
  const target = details.target;
  if (status) return `${String(status)}${details.attempt ? ` · attempt ${details.attempt}` : ""}`;
  if (method || target) return [method, target].filter(Boolean).join(" ");
  const action = details.action;
  if (action && event.message !== "goal") return String(action);
  return event.category === "STEP" ? "执行步骤" : event.category || "运行事件";
}

export function isPathEvent(event: WebEvent) {
  if (isReadCompletion(event)) return false;
  return event.type === "log" && [
    "STEP",
    "TOOL CALL",
    "OCR RESULT",
    "SYS ONE RESULT",
    "LLM RESULT",
  ].includes(event.category ?? "");
}

export function isResponseOrResultEvent(event: WebEvent) {
  return event.type === "log" && Boolean(event.category?.endsWith("RESPONSE") || event.category?.endsWith("RESULT"));
}

export function isReadCompletion(event: WebEvent) {
  return event.type === "log" && event.category === "STEP" && event.message === "read" && event.details?.status === "ok";
}

export function isBusy(status: RunState["status"]) {
  return ["starting", "running", "stopping"].includes(status);
}

export function statusLabel(status: RunState["status"]) {
  return {
    idle: "等待运行",
    starting: "正在启动",
    running: "执行中",
    stopping: "正在停止",
    completed: "已完成",
    stopped: "已停止",
    failed: "运行失败",
  }[status];
}

export function statusVariant(status: RunState["status"]) {
  if (status === "completed") return "success" as const;
  if (status === "stopped") return "warning" as const;
  if (status === "failed") return "danger" as const;
  if (isBusy(status)) return "warning" as const;
  return "outline" as const;
}

export function stringify(value: unknown) {
  if (value === undefined) return "暂无详细内容";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function detailTitle(event: WebEvent) {
  if (event.category === "HTTP REQUEST") return "Request";
  if (event.category === "HTTP RESPONSE") return "Response";
  if (event.type === "console") return event.stream === "stderr" ? "stderr" : "stdout";
  if (event.type.startsWith("run.")) return "运行状态";
  return event.category || "STEP";
}
