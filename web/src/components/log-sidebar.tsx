import { useMemo, useState } from "react";
import { ArrowDown, Clock3, MonitorPlay, Radio, XCircle } from "lucide-react";
import { Badge } from "./ui/badge";
import { Card, CardHeader, CardTitle } from "./ui/card";
import { ScrollArea } from "./ui/scroll-area";
import { DebugControls } from "./debug-controls";
import { DetailEvent } from "./detail-event";
import { RunStatusBadge } from "./status-indicator";
import { ScreenPreview } from "./screen-preview";
import { eventSubtitle, eventTitle, isPathEvent, isResponseOrResultEvent, localTime, stringify } from "../lib/dashboard";
import { cn } from "../lib/utils";
import type { DebugCommand, RunState, WebEvent } from "../types";

type Props = {
  run: RunState;
  connected: boolean;
  events: WebEvent[];
  selectedEvent?: WebEvent;
  selectedScript: string;
  onDebugCommand: (command: DebugCommand) => void;
};

export function LogSidebar({ run, connected, events, selectedEvent, selectedScript, onDebugCommand }: Props) {
  const [activePanel, setActivePanel] = useState<"logs" | "preview">("logs");
  const activeStep = [...events].reverse().find((event) => isPathEvent(event) && event.category === "STEP");
  const selectedStepId = selectedEvent?.category === "STEP"
    ? selectedEvent.event_id
    : selectedEvent?.step_id ?? activeStep?.event_id;
  const detailEvents = useMemo(() => events.filter((event) =>
    event.type === "log" && (event.category?.endsWith("REQUEST") || isResponseOrResultEvent(event)) &&
    (selectedStepId === undefined || selectedStepId === null || event.step_id === selectedStepId),
  ), [events, selectedStepId]);
  const footerEvents = events.filter((event) => event.type === "console" || event.type === "run.finished").slice(-8);

  return (
    <Card className="flex min-h-[580px] flex-col overflow-hidden border-border/80 bg-[#10151c]/85 xl:sticky xl:top-[88px] xl:h-[calc(100vh-108px)] xl:min-h-[610px]">
      <CardHeader className="border-b border-border/70 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-400/10 text-sky-300"><Radio className="h-4 w-4" /></div>
            <div><CardTitle className="text-sm">执行日志</CardTitle><p className="mt-1 text-[11px] text-slate-500">STEP · Request / Response</p></div>
          </div>
          <RunStatusBadge status={run.status} />
        </div>
        {selectedEvent && activePanel === "logs" && (
          <div className="mt-4 flex items-start gap-2 rounded-md border border-border/70 bg-[#0e131a] px-3 py-2.5">
            <span className="mt-0.5 font-mono text-[10px] text-emerald-300">#{String(selectedEvent.event_id).padStart(3, "0")}</span>
            <div className="min-w-0"><p className="truncate text-xs font-medium text-slate-200">{eventTitle(selectedEvent)}</p><p className="mt-1 text-[10px] text-slate-500">{localTime(selectedEvent.timestamp)} · {eventSubtitle(selectedEvent)}</p></div>
          </div>
        )}
      </CardHeader>

      {activePanel === "logs" && (
        <DebugControls
          enabled={run.debug}
          state={run.debug_state}
          location={run.debug_location}
          onCommand={onDebugCommand}
        />
      )}

      <div className="flex gap-1 border-b border-border/60 px-4 py-2">
        <button
          type="button"
          aria-pressed={activePanel === "logs"}
          onClick={() => setActivePanel("logs")}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[11px] font-medium transition-colors",
            activePanel === "logs" ? "bg-slate-800 text-slate-100" : "text-slate-500 hover:bg-slate-800/50 hover:text-slate-300",
          )}
        >
          <Radio className="h-3.5 w-3.5" />日志
        </button>
        <button
          type="button"
          aria-pressed={activePanel === "preview"}
          onClick={() => setActivePanel("preview")}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[11px] font-medium transition-colors",
            activePanel === "preview" ? "bg-slate-800 text-slate-100" : "text-slate-500 hover:bg-slate-800/50 hover:text-slate-300",
          )}
        >
          <MonitorPlay className="h-3.5 w-3.5" />屏幕预览
        </button>
      </div>

      <div className={cn("min-h-0 flex-1", activePanel === "logs" ? "flex flex-col" : "hidden")}>
        <div className="flex items-center justify-between border-b border-border/60 px-5 py-3">
          <div className="flex items-center gap-2 text-[10px] text-slate-500"><Clock3 className="h-3.5 w-3.5" /><span>{detailEvents.length} 条请求 / 响应 / 结果</span></div>
          <span className="max-w-[180px] truncate text-[10px] text-slate-500">{selectedScript || run.script || "未选择脚本"}</span>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-3 p-4">
            {selectedEvent?.category === "STEP" && (
              <div className="rounded-lg border border-border/80 bg-[#10151c] p-3">
                <div className="mb-2 flex items-center justify-between"><span className="text-[11px] font-semibold text-slate-300">STEP 详情</span><Badge variant="outline">{selectedEvent.level || "v"}</Badge></div>
                <pre className="code-scroll max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[#0b0f14] p-3 font-mono text-[10px] leading-relaxed text-slate-300">{stringify(selectedEvent.details ?? {})}</pre>
              </div>
            )}
            {detailEvents.map((event) => <DetailEvent key={event.event_id} event={event} />)}
            {detailEvents.length === 0 && (
              <div className="rounded-lg border border-dashed border-border/80 bg-[#0e131a]/70 px-4 py-7 text-center">
                <ArrowDown className="mx-auto h-4 w-4 text-slate-600" />
                <p className="mt-3 text-xs font-medium text-slate-400">当前步骤没有请求 / 响应</p>
                <p className="mt-1.5 text-[10px] leading-relaxed text-slate-600">当步骤调用模型或外部接口时，通信明细会关联到对应的 STEP。</p>
              </div>
            )}
            {footerEvents.map((event) => <DetailEvent key={event.event_id} event={event} />)}
          </div>
        </ScrollArea>
      </div>

      <div className={cn("min-h-0 flex-1", activePanel === "preview" ? "flex" : "hidden")}>
        <ScreenPreview active={activePanel === "preview"} />
      </div>

      <div className="flex items-center justify-between border-t border-border/70 px-4 py-3 text-[10px] text-slate-600">
        <span className="flex items-center gap-1.5"><Radio className={cn("h-3 w-3", connected && "text-emerald-400")} />实时事件流</span>
        <span className="font-mono">{events.length} events</span>
      </div>
      {run.error && <div className="flex items-start gap-2 border-t border-rose-400/20 px-4 py-3 text-[10px] text-rose-200"><XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{run.error}</div>}
    </Card>
  );
}
