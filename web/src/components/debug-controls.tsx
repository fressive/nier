import { ArrowRight, CornerDownRight, LogOut, Play } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { stringify } from "../lib/dashboard";
import type { DebugCommand, DebugLocation, DebugState } from "../types";

type Props = {
  enabled: boolean;
  state: DebugState;
  location: DebugLocation | null;
  onCommand: (command: DebugCommand) => void;
};

export function DebugControls({ enabled, state, location, onCommand }: Props) {
  if (!enabled) return null;
  const paused = state === "paused";
  const label = state === "paused" ? "已暂停" : state === "finished" ? "调试结束" : "运行中";
  const controls: { command: DebugCommand; label: string; title: string; icon: typeof Play }[] = [
    { command: "continue", label: "继续", title: "继续运行，不再停在 STEP 事件", icon: Play },
    { command: "step_into", label: "步入", title: "运行到更深的 STEP 调用层级", icon: CornerDownRight },
    { command: "step", label: "单步", title: "运行到下一个 STEP 事件", icon: ArrowRight },
    { command: "step_out", label: "步出", title: "运行到更浅的 STEP 调用层级", icon: LogOut },
  ];

  return (
    <section className="border-b border-border/60 bg-[#0e131a]/80 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-200">STEP 调试</span>
          <Badge variant={paused ? "success" : "outline"} className="px-1.5 py-0">{label}</Badge>
        </div>
        {location && <span className="max-w-[180px] truncate font-mono text-[10px] text-slate-500">{location.file}:{location.line}</span>}
      </div>
      <div className="mt-2 grid grid-cols-4 gap-1.5">
        {controls.map(({ command, label: buttonLabel, title, icon: Icon }) => (
          <Button
            key={command}
            variant={command === "continue" ? "secondary" : "outline"}
            size="sm"
            disabled={!paused}
            onClick={() => onCommand(command)}
            title={title}
            className="h-8 gap-1 px-1.5 text-[10px]"
          >
            <Icon className="h-3.5 w-3.5" />{buttonLabel}
          </Button>
        ))}
      </div>
      {location && (
        <div className="mt-3 overflow-hidden rounded-md border border-border/70 bg-[#0b0f14]">
          <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2 text-[10px] text-slate-500">
            <span className="truncate font-mono">STEP #{String(location.step_id ?? "?").padStart(3, "0")} · {location.message}</span>
            <span className="shrink-0">{location.function} · {location.file}:{location.line} · 深度 {location.depth}</span>
          </div>
          <pre className="code-scroll max-h-40 overflow-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-[10px] leading-relaxed text-emerald-200">{stringify(location.details)}</pre>
          {location.stack.length > 0 && (
            <details className="border-t border-border/60 px-3 py-2">
              <summary className="cursor-pointer text-[10px] text-slate-500">STEP 调用路径 · {location.stack.length} 层</summary>
              <pre className="code-scroll mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-slate-400">{location.stack.map((frame) => `${frame.file}:${frame.line} · ${frame.function}`).join("\n")}</pre>
            </details>
          )}
        </div>
      )}
      {!location && <p className="mt-2 text-[10px] text-slate-500">等待脚本触发第一个 STEP 事件。</p>}
    </section>
  );
}
