import { useState } from "react";
import { ChevronDown, ChevronRight, Circle, Dot, Maximize2 } from "lucide-react";
import { Badge } from "./ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "./ui/dialog";
import { cn } from "../lib/utils";
import { parseUiDumpXml, type UiDumpPayload, type UiTreeNode } from "../lib/ui-dump";

function UiTreeNodeView({ node, depth, large = false }: { node: UiTreeNode; depth: number; large?: boolean }) {
  const [open, setOpen] = useState(depth === 0);
  const attributes = Object.entries(node.attributes);
  const expandable = attributes.length > 0 || node.children.length > 0;
  const label = node.attributes.class || node.tag;
  const text = node.attributes.text || node.attributes["content-desc"] || node.text;
  const resourceId = node.attributes["resource-id"] || node.attributes.id;
  const bounds = node.attributes.bounds;
  const flags = ["clickable", "scrollable", "selected", "focused"]
    .filter((name) => node.attributes[name] === "true");
  if (node.attributes.enabled === "false") flags.push("disabled");

  return (
    <div className="min-w-0">
      <div className={cn("flex min-w-0 items-start gap-1.5", large ? "py-2" : "py-1")}>
        <button
          type="button"
          className={cn(
            "mt-0.5 flex shrink-0 items-center justify-center rounded text-slate-500",
            large ? "h-5 w-5" : "h-4 w-4",
            expandable ? "hover:bg-slate-700/70 hover:text-slate-200" : "cursor-default",
          )}
          aria-label={`${open ? "收起" : "展开"} ${label}`}
          aria-expanded={expandable ? open : undefined}
          disabled={!expandable}
          onClick={() => setOpen((value) => !value)}
        >
          {expandable
            ? open
              ? <ChevronDown className={cn(large ? "h-4 w-4" : "h-3.5 w-3.5")} />
              : <ChevronRight className={cn(large ? "h-4 w-4" : "h-3.5 w-3.5")} />
            : <Dot className={cn(large ? "h-5 w-5" : "h-4 w-4")} />}
        </button>
        <div className="min-w-0 flex-1">
          <div className={cn("flex min-w-0 flex-wrap items-center", large ? "gap-x-3 gap-y-2" : "gap-x-2 gap-y-1")}>
            <span className={cn("font-mono text-sky-300", large ? "text-xs" : "text-[10px]")}>{node.tag}</span>
            {label !== node.tag && <span className={cn("break-all font-mono text-violet-200", large ? "text-xs" : "text-[10px]")}>{label}</span>}
            {text && <span className={cn("max-w-full truncate text-slate-200", large ? "text-sm" : "text-[10px]")} title={text}>{text}</span>}
            {flags.map((flag) => <Badge key={flag} variant="outline" className={cn("px-1 py-0 text-emerald-300", large ? "text-[10px]" : "text-[8px]")}>{flag}</Badge>)}
          </div>
          {(resourceId || bounds) && (
            <div className={cn("mt-0.5 flex min-w-0 flex-wrap gap-x-2 font-mono text-slate-500", large ? "text-[11px]" : "text-[9px]")}>
              {resourceId && <span className="max-w-full truncate" title={resourceId}>id: {resourceId}</span>}
              {bounds && <span>bounds: {bounds}</span>}
            </div>
          )}
        </div>
      </div>
      {open && expandable && (
        <div className="ml-[7px] border-l border-slate-700/70 pl-3">
          {attributes.length > 0 && (
            <details className="mb-1.5 rounded border border-border/50 bg-[#0b0f14]/70 px-2 py-1">
              <summary className={cn("cursor-pointer select-none text-slate-500", large ? "text-[11px]" : "text-[9px]")}>属性 · {attributes.length}</summary>
              <dl className={cn("mt-2 grid grid-cols-[minmax(72px,auto)_minmax(0,1fr)] gap-x-2 gap-y-1 pb-1", large ? "text-[11px]" : "text-[9px]")}>
                {attributes.map(([name, value]) => (
                  <div key={name} className="contents">
                    <dt className={cn("break-all font-mono text-slate-500", large ? "text-[11px]" : "text-[9px]")}>{name}</dt>
                    <dd className={cn("break-all font-mono text-slate-300", large ? "text-[11px]" : "text-[9px]")}>{value || "(empty)"}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
          {node.children.map((child, index) => (
            <UiTreeNodeView key={`${child.tag}-${index}`} node={child} depth={depth + 1} large={large} />
          ))}
        </div>
      )}
    </div>
  );
}

export function UiDumpTree({ dump }: { dump: UiDumpPayload }) {
  const parsed = parseUiDumpXml(dump.xml, dump.source);
  const source = dump.source === "WEBVIEW_DEVTOOLS"
    ? "WebView DOM"
    : dump.source === "UIAUTOMATOR_FALLBACK"
      ? "UIAutomator fallback"
      : "UIAutomator";

  return (
    <Dialog>
      <div className="mt-2 overflow-hidden rounded-md border border-border/60 bg-[#0b0f14]">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
          <UiDumpMetadata dump={dump} parsed={parsed} source={source} />
          <DialogTrigger asChild>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-border/70 px-2 py-1 text-[10px] font-medium text-slate-300 transition-colors hover:border-slate-500 hover:bg-slate-800/70 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/70"
            >
              <Maximize2 className="h-3 w-3" />
              全屏预览
            </button>
          </DialogTrigger>
        </div>
        <UiDumpBody dump={dump} parsed={parsed} />
      </div>
      <DialogContent className="!fixed !inset-0 !left-0 !top-0 !h-[100dvh] !w-screen !max-w-none !translate-x-0 !translate-y-0 flex flex-col overflow-hidden rounded-none border-0 bg-[#090d12] p-0">
        <DialogHeader className="shrink-0 border-b border-border/70 px-5 py-4 pr-14 sm:px-8 sm:py-5">
          <DialogTitle className="text-base text-slate-100">UI 层级树 · {source}</DialogTitle>
          <DialogDescription className="text-xs text-slate-500">
            {parsed.root ? `${parsed.nodeCount} 个节点 · 展开节点可查看属性` : "当前结果无法解析为层级树"}
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col">
          <UiDumpMetadata dump={dump} parsed={parsed} source={source} className="shrink-0 border-b border-border/50 px-5 py-3 sm:px-8" />
          <UiDumpBody dump={dump} parsed={parsed} fullscreen />
        </div>
      </DialogContent>
    </Dialog>
  );
}

function UiDumpMetadata({
  dump,
  parsed,
  source,
  className,
}: {
  dump: UiDumpPayload;
  parsed: ReturnType<typeof parseUiDumpXml>;
  source: string;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <Badge variant="outline" className="px-1.5 py-0 text-[9px]">{source}</Badge>
      {parsed.root && <span className="font-mono text-[9px] text-slate-500">{parsed.nodeCount} 个节点</span>}
      {dump.complete === false && <Badge variant="warning" className="px-1.5 py-0 text-[9px]">结果不完整</Badge>}
      {parsed.truncated && <Badge variant="warning" className="px-1.5 py-0 text-[9px]">日志截断</Badge>}
      {parsed.recovered && <span className="text-[9px] text-amber-300/80">显示可解析部分</span>}
    </div>
  );
}

function UiDumpBody({
  dump,
  parsed,
  fullscreen = false,
}: {
  dump: UiDumpPayload;
  parsed: ReturnType<typeof parseUiDumpXml>;
  fullscreen?: boolean;
}) {
  return (
    <>
      {dump.warning && <p className="shrink-0 border-b border-border/50 px-3 py-2 text-[10px] text-amber-200/80">{dump.warning}</p>}
      {parsed.root ? (
        <div className={cn("code-scroll overflow-auto p-2", fullscreen ? "min-h-0 flex-1 sm:px-6" : "max-h-[420px]")}>
          <UiTreeNodeView node={parsed.root} depth={0} large={fullscreen} />
          {parsed.truncated && <p className="mt-2 border-t border-border/50 pt-2 text-[9px] text-amber-300/70">只显示日志保留的 UI 层级片段。</p>}
        </div>
      ) : (
        <div className={cn("p-3", fullscreen && "min-h-0 flex-1")}>
          <p className="mb-2 flex items-center gap-1.5 text-[10px] text-amber-200/80"><Circle className="h-3 w-3" />{parsed.error}</p>
          <pre className="code-scroll max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-slate-400">{dump.xml || "(空 UI dump)"}</pre>
        </div>
      )}
    </>
  );
}
