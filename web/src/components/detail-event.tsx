import { Radio } from "lucide-react";
import { Badge } from "./ui/badge";
import { cn } from "../lib/utils";
import { detailTitle, localTime, stringify } from "../lib/dashboard";
import { UiDumpTree } from "./ui-dump-tree";
import { isUiDumpPayload } from "../lib/ui-dump";
import type { WebEvent } from "../types";

export function DetailEvent({ event }: { event: WebEvent }) {
  const category = event.category ?? "";
  const isRequest = category.endsWith("REQUEST");
  const isResponse = category.endsWith("RESPONSE");
  const details = event.details ?? {};
  const method = details.method ? String(details.method) : "";
  const target = details.target ? String(details.target) : "";
  const status = details.status;
  const raw = event.type === "console"
    ? event.text
    : event.type === "log"
      ? details
      : event;
  const uiDump = event.type === "log"
    && details.operation === "dump_ui"
    && isUiDumpPayload(details.result)
    ? details.result
    : undefined;

  return (
    <div className="rounded-lg border border-border/80 bg-[#10151c] p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            isRequest ? "bg-sky-400" : isResponse ? "bg-emerald-400" : "bg-slate-500",
          )} />
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-300">{detailTitle(event)}</span>
          {method && <Badge variant="outline" className="px-1.5 py-0 font-mono text-[9px]">{method}</Badge>}
          {status !== undefined && <Badge variant={Number(status) >= 400 ? "danger" : "success"} className="px-1.5 py-0 font-mono text-[9px]">{String(status)}</Badge>}
        </div>
        <span className="shrink-0 font-mono text-[10px] text-slate-500">{localTime(event.timestamp)}</span>
      </div>
      {target && <p className="mt-2 break-all font-mono text-[10px] text-slate-500">{target}</p>}
      {uiDump
        ? <UiDumpTree dump={uiDump} />
        : <pre className="code-scroll mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[#0b0f14] p-3 font-mono text-[10px] leading-relaxed text-slate-300">{stringify(raw)}</pre>}
      {(isRequest || isResponse) && (
        <div className="mt-2 flex items-center gap-1.5 text-[9px] text-slate-600">
          <Radio className="h-3 w-3" />
          <span>已应用日志脱敏与 4 KB 截断</span>
        </div>
      )}
    </div>
  );
}
