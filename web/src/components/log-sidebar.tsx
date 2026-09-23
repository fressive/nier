import { useMemo } from "react";
import { ArrowDown, Clock3, Eye, Radio, XCircle } from "lucide-react";
import { Badge } from "./ui/badge";
import { Card, CardHeader, CardTitle } from "./ui/card";
import { ScrollArea } from "./ui/scroll-area";
import { DebugControls } from "./debug-controls";
import { DetailEvent } from "./detail-event";
import { RunStatusBadge } from "./status-indicator";
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
  const activeStep = [...events].reverse().find((event) => isPathEvent(event) && event.category === "STEP");
  const selectedStepId = selectedEvent?.category === "STEP"
    ? selectedEvent.event_id
    : selectedEvent?.step_id ?? activeStep?.event_id;
  const previewTarget = selectedEvent ?? activeStep;
  const responsePreviewEvent = useMemo(() => {
    if (!previewTarget) return undefined;
    if (isResponseOrResultEvent(previewTarget)) return previewTarget;
    const relatedResponses = events.filter((event) =>
      isResponseOrResultEvent(event) && event.step_id === previewTarget.event_id,
    );
    return relatedResponses.filter((event) => event.category === "READ RESULT").at(-1)
      ?? relatedResponses.filter((event) => event.category?.endsWith("RESULT")).at(-1)
      ?? relatedResponses.at(-1);
  }, [events, previewTarget?.event_id, previewTarget?.category]);
  const detailEvents = useMemo(() => events.filter((event) =>
    event.type === "log" && (event.category?.endsWith("REQUEST") || isResponseOrResultEvent(event)) &&
    event.event_id !== responsePreviewEvent?.event_id &&
    (selectedStepId === undefined || selectedStepId === null || event.step_id === selectedStepId),
  ), [events, responsePreviewEvent?.event_id, selectedStepId]);
  const footerEvents = events.filter((event) => event.type === "console" || event.type === "run.finished").slice(-8);

  return (
    <Card className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden border-border/80 bg-[#10151c]/85">
      <CardHeader className="shrink-0 space-y-0 border-b border-border/70 px-3 py-2.5 sm:px-4 sm:py-3">
        <div className="flex items-center justify-between">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-sky-400/10 text-sky-300"><Radio className="h-3.5 w-3.5" /></div>
            <div className="min-w-0"><CardTitle className="text-sm">执行日志</CardTitle><p className="mt-0.5 truncate text-[10px] text-slate-500">STEP · Request / Response</p></div>
          </div>
          <RunStatusBadge status={run.status} />
        </div>
        {selectedEvent && (
          <div className="mt-2 flex items-start gap-2 rounded-md border border-border/70 bg-[#0e131a] px-2.5 py-2 sm:mt-3">
            <span className="mt-0.5 font-mono text-[10px] text-emerald-300">#{String(selectedEvent.event_id).padStart(3, "0")}</span>
            <div className="min-w-0"><p className="truncate text-xs font-medium text-slate-200">{eventTitle(selectedEvent)}</p><p className="mt-1 text-[10px] text-slate-500">{localTime(selectedEvent.timestamp)} · {eventSubtitle(selectedEvent)}</p></div>
          </div>
        )}
      </CardHeader>

      <DebugControls
        enabled={run.debug}
        state={run.debug_state}
        location={run.debug_location}
        onCommand={onDebugCommand}
      />

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/60 px-3 py-2 sm:px-4">
          <div className="flex items-center gap-2 text-[10px] text-slate-500"><Clock3 className="h-3.5 w-3.5" /><span>{detailEvents.length + Number(Boolean(responsePreviewEvent))} 条请求 / 响应 / 结果</span></div>
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
            <section className="space-y-2">
              <div className="flex items-center gap-1.5 px-1 text-[11px] font-semibold text-slate-300">
                <Eye className="h-3.5 w-3.5 text-emerald-300" />响应预览
              </div>
              {responsePreviewEvent ? (
                <DetailEvent event={responsePreviewEvent} />
              ) : (
                <div className="rounded-lg border border-dashed border-border/80 bg-[#0e131a]/70 px-4 py-5 text-center">
                  <p className="text-[11px] text-slate-500">当前节点暂无响应内容</p>
                  <p className="mt-1 text-[10px] text-slate-600">选择包含结果的节点后，响应会显示在此面板。</p>
                </div>
              )}
            </section>
            {detailEvents.map((event) => <DetailEvent key={event.event_id} event={event} />)}
            {detailEvents.length === 0 && !responsePreviewEvent && (
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

      <div className="flex shrink-0 items-center justify-between border-t border-border/70 px-3 py-2 text-[9px] text-slate-600 sm:px-4">
        <span className="flex items-center gap-1.5"><Radio className={cn("h-3 w-3", connected && "text-emerald-400")} />实时事件流</span>
        <span className="font-mono">{events.length} events</span>
      </div>
      {run.error && <div className="flex max-h-14 shrink-0 items-start gap-2 overflow-hidden border-t border-rose-400/20 px-3 py-2 text-[10px] text-rose-200 sm:px-4"><XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="break-words">{run.error}</span></div>}
    </Card>
  );
}
