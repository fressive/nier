import { Activity, Bot, Braces, Eye, Workflow } from "lucide-react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Badge } from "./ui/badge";
import { cn } from "../lib/utils";
import { eventSubtitle, eventTitle, localTime } from "../lib/dashboard";
import type { StepNodeType } from "../types";

function NodeIcon({ category }: { category?: string }) {
  if (category === "TOOL CALL") return <Bot className="h-4 w-4" />;
  if (category === "SYS ONE RESULT" || category === "LLM RESULT") return <Braces className="h-4 w-4" />;
  if (category === "OCR RESULT") return <Activity className="h-4 w-4" />;
  return <Workflow className="h-4 w-4" />;
}

export function StepNode({ data }: NodeProps<StepNodeType>) {
  const { event, response, index, selected, active, onSelect } = data;
  const status = String(event.details?.status ?? "");
  const failed = status === "failed";
  const completed = ["ok", "success", "done"].includes(status)
    || (!failed && Boolean(response?.category?.endsWith("RESULT")));
  const subtitle = completed && status === "start"
    ? eventSubtitle({ ...event, details: { ...event.details, status: "ok" } })
    : eventSubtitle(event);
  return (
    <div
      onClick={() => onSelect(event.event_id)}
      className={cn(
        "step-node w-[320px] cursor-pointer rounded-xl border bg-[#151b23] p-4 shadow-xl transition-all",
        selected ? "border-emerald-400/60 shadow-emerald-950/40" : "border-[#2a3542] hover:border-[#536273]",
        failed && "border-rose-400/50",
        active && !failed && "border-emerald-400/45",
      )}
    >
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-[#64788a]" />
      <div className="flex items-start gap-3">
        <div className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
          failed ? "border-rose-400/20 bg-rose-400/10 text-rose-300" :
          completed ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-300" :
          "border-cyan-400/20 bg-cyan-400/10 text-cyan-300",
        )}>
          <NodeIcon category={event.category} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <p className="truncate text-sm font-semibold text-slate-100">{eventTitle(event)}</p>
            <div className="flex shrink-0 items-center gap-1.5">
              {response && (
                <span className="text-emerald-300" aria-label="侧栏有响应预览" role="img" title="侧栏有响应预览">
                  <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
              )}
              <Badge variant={failed ? "danger" : completed ? "success" : "outline"} className="px-2 py-0">
                {failed ? "失败" : completed ? "完成" : event.category === "STEP" ? "STEP" : "MODEL"}
              </Badge>
            </div>
          </div>
          <p className="mt-1 truncate text-xs text-slate-400">{subtitle}</p>
          <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-[0.12em] text-slate-500">
            <span>节点 {String(index).padStart(2, "0")}</span>
            <span className="font-mono normal-case tracking-normal">{localTime(event.timestamp)}</span>
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-emerald-400" />
    </div>
  );
}

export const nodeTypes = { step: StepNode };
