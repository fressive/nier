import { useState } from "react";
import { ChevronDown, ChevronRight, Circle, Dot } from "lucide-react";
import { Badge } from "./ui/badge";
import { cn } from "../lib/utils";
import { parseUiDumpXml, type UiDumpPayload, type UiTreeNode } from "../lib/ui-dump";

function UiTreeNodeView({ node, depth }: { node: UiTreeNode; depth: number }) {
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
      <div className="flex min-w-0 items-start gap-1.5 py-1">
        <button
          type="button"
          className={cn(
            "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded text-slate-500",
            expandable ? "hover:bg-slate-700/70 hover:text-slate-200" : "cursor-default",
          )}
          aria-label={`${open ? "收起" : "展开"} ${label}`}
          aria-expanded={expandable ? open : undefined}
          disabled={!expandable}
          onClick={() => setOpen((value) => !value)}
        >
          {expandable ? open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" /> : <Dot className="h-4 w-4" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-mono text-[10px] text-sky-300">{node.tag}</span>
            {label !== node.tag && <span className="break-all font-mono text-[10px] text-violet-200">{label}</span>}
            {text && <span className="max-w-full truncate text-[10px] text-slate-200" title={text}>{text}</span>}
            {flags.map((flag) => <Badge key={flag} variant="outline" className="px-1 py-0 text-[8px] text-emerald-300">{flag}</Badge>)}
          </div>
          {(resourceId || bounds) && (
            <div className="mt-0.5 flex min-w-0 flex-wrap gap-x-2 font-mono text-[9px] text-slate-500">
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
              <summary className="cursor-pointer select-none text-[9px] text-slate-500">属性 · {attributes.length}</summary>
              <dl className="mt-2 grid grid-cols-[minmax(72px,auto)_minmax(0,1fr)] gap-x-2 gap-y-1 pb-1">
                {attributes.map(([name, value]) => (
                  <div key={name} className="contents">
                    <dt className="break-all font-mono text-[9px] text-slate-500">{name}</dt>
                    <dd className="break-all font-mono text-[9px] text-slate-300">{value || "(empty)"}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
          {node.children.map((child, index) => (
            <UiTreeNodeView key={`${child.tag}-${index}`} node={child} depth={depth + 1} />
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
    <div className="mt-2 overflow-hidden rounded-md border border-border/60 bg-[#0b0f14]">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2">
        <Badge variant="outline" className="px-1.5 py-0 text-[9px]">{source}</Badge>
        {parsed.root && <span className="font-mono text-[9px] text-slate-500">{parsed.nodeCount} 个节点</span>}
        {dump.complete === false && <Badge variant="warning" className="px-1.5 py-0 text-[9px]">结果不完整</Badge>}
        {parsed.truncated && <Badge variant="warning" className="px-1.5 py-0 text-[9px]">日志截断</Badge>}
        {parsed.recovered && <span className="text-[9px] text-amber-300/80">显示可解析部分</span>}
      </div>
      {dump.warning && <p className="border-b border-border/50 px-3 py-2 text-[10px] text-amber-200/80">{dump.warning}</p>}
      {parsed.root ? (
        <div className="code-scroll max-h-[420px] overflow-auto p-2">
          <UiTreeNodeView node={parsed.root} depth={0} />
          {parsed.truncated && <p className="mt-2 border-t border-border/50 pt-2 text-[9px] text-amber-300/70">只显示日志保留的 UI 层级片段。</p>}
        </div>
      ) : (
        <div className="p-3">
          <p className="mb-2 flex items-center gap-1.5 text-[10px] text-amber-200/80"><Circle className="h-3 w-3" />{parsed.error}</p>
          <pre className="code-scroll max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-slate-400">{dump.xml || "(空 UI dump)"}</pre>
        </div>
      )}
    </div>
  );
}
