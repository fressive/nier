import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Code2, LoaderCircle } from "lucide-react";
import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import { Card, CardHeader, CardTitle } from "./ui/card";
import { fetchJson } from "../lib/api";
import { cn } from "../lib/utils";

hljs.registerLanguage("python", python);

type SourceFile = { path: string; source: string };

type Props = {
  path: string;
  line: number | null;
  functionName: string | null;
  panelActive: boolean;
};

function splitHighlightedLines(markup: string): string[] {
  // Keep each row valid HTML while preserving scopes such as multiline strings.
  const lines: string[] = [];
  const openSpans: string[] = [];
  let current = "";

  for (const part of markup.split(/(<span class="[^"]*">|<\/span>|\n)/g)) {
    if (!part) continue;
    if (part === "\n") {
      lines.push(current + "</span>".repeat(openSpans.length));
      current = openSpans.join("");
    } else if (part.startsWith('<span class="')) {
      openSpans.push(part);
      current += part;
    } else if (part === "</span>") {
      openSpans.pop();
      current += part;
    } else {
      current += part;
    }
  }

  lines.push(current + "</span>".repeat(openSpans.length));
  return lines;
}

export function SourceViewer({ path, line, functionName, panelActive }: Props) {
  const [sourceFile, setSourceFile] = useState<SourceFile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const activeLineRef = useRef<HTMLLIElement>(null);
  const activeLineNumberRef = useRef<number | null>(line);
  const sourceViewportRef = useRef<HTMLDivElement>(null);
  activeLineNumberRef.current = line;

  useEffect(() => {
    if (!path) {
      setSourceFile(null);
      setLoading(false);
      setError("");
      return;
    }

    const controller = new AbortController();
    const encodedPath = path.split("/").map(encodeURIComponent).join("/");
    setSourceFile(null);
    setLoading(true);
    setError("");
    void fetchJson<SourceFile>(`/api/source/${encodedPath}`, { cache: "no-store", signal: controller.signal })
      .then((result) => setSourceFile(result))
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path]);

  const source = sourceFile?.path === path ? sourceFile.source : null;
  const normalizedSource = source?.replace(/\r\n?/g, "\n") ?? null;
  const lines = normalizedSource?.split("\n") ?? [];
  const highlightedLines = useMemo(() => {
    if (normalizedSource === null) return [];
    const highlighted = hljs.highlight(normalizedSource, { language: "python", ignoreIllegals: true });
    return splitHighlightedLines(highlighted.value);
  }, [normalizedSource]);

  useEffect(() => {
    if (!line || line < 1 || source === null || !activeLineRef.current) return;
    activeLineRef.current.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "auto" });
  }, [line, path, source]);

  useEffect(() => {
    const viewport = sourceViewportRef.current;
    if (!viewport) return;
    // A hidden mobile tab has no layout box; follow it when the source tab becomes visible.
    const observer = new ResizeObserver((entries) => {
      if (
        entries.some(({ contentRect }) => contentRect.width > 0 && contentRect.height > 0)
        && activeLineNumberRef.current && activeLineNumberRef.current > 0 && source !== null
      ) {
        activeLineRef.current?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "auto" });
      }
    });
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [path, source, panelActive]);

  return (
    <Card className="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden border-border/80 bg-[#10151c]/85">
      <CardHeader className="shrink-0 space-y-0 border-b border-border/70 px-3 py-2.5 sm:px-4 sm:py-3">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-400/10 text-emerald-300">
              <Code2 className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0">
              <CardTitle className="text-sm">运行源码</CardTitle>
              <p className="mt-0.5 truncate font-mono text-[10px] text-slate-500" title={path || undefined}>
                {path || "选择一个 Python 脚本"}
              </p>
            </div>
          </div>
          {line && line > 0 ? (
            <span className="shrink-0 rounded-md border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 font-mono text-[10px] text-emerald-200">
              L{line}
            </span>
          ) : (
            <span className="shrink-0 text-[10px] text-slate-600">等待运行位置</span>
          )}
        </div>
        {functionName && <p className="truncate pl-9 text-[10px] text-slate-500">{functionName}()</p>}
      </CardHeader>

      {loading ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 text-[11px] text-slate-500">
          <LoaderCircle className="h-4 w-4 animate-spin text-emerald-300/80" />正在读取源码…
        </div>
      ) : error ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4">
          <div className="flex max-w-full items-start gap-2 rounded-lg border border-rose-400/20 bg-rose-400/5 p-3 text-[11px] leading-relaxed text-rose-200">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="break-words">无法读取源码：{error}</span>
          </div>
        </div>
      ) : source === null ? (
        <div className="flex min-h-0 flex-1 items-center justify-center px-5 text-center text-[11px] leading-relaxed text-slate-600">
          {path ? "等待源码加载…" : "选择脚本后，这里会显示源码和当前运行行。"}
        </div>
      ) : (
        <div ref={sourceViewportRef} className="code-scroll min-h-0 flex-1 overflow-auto" role="region" aria-label="Python 源码" tabIndex={0}>
          <ol className="min-w-max py-2 font-mono text-[11px] leading-5" aria-label={`${path} 源码`}>
            {lines.map((text, index) => {
              const lineNumber = index + 1;
              const active = lineNumber === line;
              return (
                <li
                  key={lineNumber}
                  ref={active ? activeLineRef : undefined}
                  aria-current={active ? "location" : undefined}
                  className={cn(
                    "flex min-w-full w-max border-l-2 pr-4",
                    active
                      ? "border-emerald-300 bg-emerald-400/15 text-emerald-50"
                      : "border-transparent text-slate-300",
                  )}
                >
                  <span
                    className={cn(
                      "sticky left-0 z-10 w-12 shrink-0 select-none border-r border-border/50 px-2 text-right",
                      active ? "bg-[#16372f] text-emerald-200" : "bg-[#10151c] text-slate-600",
                    )}
                  >
                    {lineNumber}
                  </span>
                  <code
                    className="source-code whitespace-pre px-3"
                    dangerouslySetInnerHTML={{ __html: highlightedLines[index] || (text ? "" : " ") }}
                  />
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </Card>
  );
}
