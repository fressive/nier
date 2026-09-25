import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Braces, Check, ChevronDown, ChevronRight, Code2, Copy, Layers3, LoaderCircle, MonitorPlay, RefreshCw, ScanSearch } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { fetchJson, postJson } from "../lib/api";
import { parseUiDumpXml, type UiTreeNode } from "../lib/ui-dump";
import { parseUiBounds, type UiBounds } from "../lib/ui-bounds.mjs";
import { generateNierCode } from "../lib/nier-codegen.mjs";
import { cn } from "../lib/utils";

type InspectorDevice = {
  serial: string;
  state: string;
  model: string;
  product: string;
};

type DeviceResponse = {
  serial: string | null;
  device_error: string | null;
  devices: InspectorDevice[];
};

type UiDumpPreview = {
  serial: string;
  image_base64: string;
  image_mime: string;
  screen_width: number;
  screen_height: number;
  xml: string;
  source: string;
  complete: boolean;
  warning: string;
  tree_text: string;
};

type TreeEntry = {
  node: UiTreeNode;
  path: string;
  depth: number;
  bounds: UiBounds | null;
};

function flattenTree(
  node: UiTreeNode,
  path: string,
  depth: number,
  width: number,
  height: number,
): TreeEntry[] {
  return [
    {
      node,
      path,
      depth,
      bounds: parseUiBounds(node.attributes.bounds, width, height),
    },
    ...node.children.flatMap((child, index) =>
      flattenTree(child, `${path}/${index}`, depth + 1, width, height),
    ),
  ];
}

function nodeLabel(node: UiTreeNode) {
  return node.attributes.text
    || node.attributes["content-desc"]
    || node.attributes["aria-label"]
    || node.attributes.title
    || node.text
    || node.attributes["resource-id"]
    || node.attributes.class
    || node.tag;
}

function nodeElementId(path: string) {
  return `ui-inspector-node-${path.replaceAll("/", "-")}`;
}

export function UiInspectorTab() {
  const [devices, setDevices] = useState<InspectorDevice[]>([]);
  const [serial, setSerial] = useState("");
  const [deviceError, setDeviceError] = useState("");
  const [preferWebView, setPreferWebView] = useState(true);
  const [includeInvisible, setIncludeInvisible] = useState(false);
  const [capture, setCapture] = useState<UiDumpPreview | null>(null);
  const [loadingDevices, setLoadingDevices] = useState(true);
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState("");
  const [hoveredPath, setHoveredPath] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => new Set(["0"]));
  const [copyStatus, setCopyStatus] = useState("");

  const refreshDevices = useCallback(async () => {
    setLoadingDevices(true);
    try {
      const result = await fetchJson<DeviceResponse>("/api/preview/state");
      setDevices(result.devices);
      setDeviceError(result.device_error ?? "");
      setSerial((current) => {
        if (result.serial && result.devices.some((device) => device.serial === result.serial && device.state === "device")) {
          return result.serial;
        }
        if (current && result.devices.some((device) => device.serial === current && device.state === "device")) {
          return current;
        }
        return result.devices.find((device) => device.state === "device")?.serial ?? "";
      });
      setError("");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLoadingDevices(false);
    }
  }, []);

  useEffect(() => {
    void refreshDevices();
  }, [refreshDevices]);

  const parsed = useMemo(
    () => capture ? parseUiDumpXml(capture.xml, capture.source) : null,
    [capture],
  );
  const entries = useMemo(
    () => parsed?.root && capture
      ? flattenTree(parsed.root, "0", 0, capture.screen_width, capture.screen_height)
      : [],
    [parsed, capture],
  );
  const activePath = hoveredPath ?? selectedPath;
  const activeEntry = entries.find((entry) => entry.path === activePath);
  const selectedEntry = entries.find((entry) => entry.path === selectedPath);
  const generatedCode = useMemo(
    () => selectedEntry && capture
      ? generateNierCode(selectedEntry.node, {
        source: capture.source,
        screenWidth: capture.screen_width,
        screenHeight: capture.screen_height,
      })
      : null,
    [selectedEntry, capture],
  );

  useEffect(() => {
    setCopyStatus("");
  }, [generatedCode?.code]);
  const boxes = useMemo(
    () => entries
      .filter((entry): entry is TreeEntry & { bounds: UiBounds } => entry.bounds !== null)
      .sort((left, right) => {
        const leftArea = left.bounds.width * left.bounds.height;
        const rightArea = right.bounds.width * right.bounds.height;
        return rightArea - leftArea || left.depth - right.depth;
      }),
    [entries],
  );

  useEffect(() => {
    if (!hoveredPath) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(nodeElementId(hoveredPath))?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hoveredPath]);

  const runUidump = async () => {
    if (!serial) return;
    setCapturing(true);
    setError("");
    setCapture(null);
    setHoveredPath(null);
    setSelectedPath(null);
    setExpandedPaths(new Set(["0"]));
    try {
      const result = await postJson<UiDumpPreview>("/api/uidump", {
        serial,
        prefer_webview: preferWebView,
        include_invisible: includeInvisible,
      });
      setCapture(result);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setCapturing(false);
    }
  };

  const toggleExpanded = (path: string) => {
    setExpandedPaths((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const copyGeneratedCode = async () => {
    if (!generatedCode) return;
    try {
      await navigator.clipboard.writeText(generatedCode.code);
      setCopyStatus("代码已复制");
    } catch {
      setCopyStatus("复制失败，请手动选择代码");
    }
  };

  const connectedDevices = devices.filter((device) => device.state === "device");
  const sourceLabel = capture?.source === "WEBVIEW_DEVTOOLS"
    ? "WebView DevTools"
    : capture?.source === "UIAUTOMATOR_FALLBACK"
      ? "UIAutomator fallback"
      : "UIAutomator";
  const selectedDevice = devices.find((device) => device.serial === serial);

  return (
    <div className="mx-auto flex min-h-0 w-full flex-1 flex-col gap-2 overflow-hidden px-3 py-2 sm:px-5 lg:px-6">
      <Card className="flex shrink-0 flex-wrap items-center gap-2 border-border/80 bg-[#10151c]/85 p-3 sm:p-3.5">
        <div className="mr-auto flex min-w-0 items-center gap-2">
          <ScanSearch className="h-4 w-4 shrink-0 text-emerald-300" />
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-slate-100">UI Inspector</h1>
            <p className="truncate text-[10px] text-slate-500">执行只读 uidump，并把节点 bounds 映射到截图</p>
          </div>
        </div>
        <select
          value={serial}
          onChange={(event) => setSerial(event.target.value)}
          disabled={capturing || loadingDevices}
          aria-label="选择 UIDump 设备"
          className="h-9 min-w-0 flex-1 rounded-md border border-border bg-[#0b0f14] px-2 text-[10px] text-slate-200 outline-none focus:border-emerald-400/50 disabled:opacity-60 sm:max-w-[320px] sm:text-[11px]"
        >
          {connectedDevices.length === 0 && <option value="">未发现已授权 ADB 设备</option>}
          {devices.map((device) => (
            <option key={device.serial} value={device.serial} disabled={device.state !== "device"}>
              {device.model || device.product || device.serial} · {device.state} · {device.serial}
            </option>
          ))}
        </select>
        <Button variant="ghost" size="icon" title="刷新设备列表" onClick={() => void refreshDevices()} disabled={loadingDevices || capturing} className="h-9 w-9 text-slate-400">
          <RefreshCw className={cn("h-3.5 w-3.5", loadingDevices && "animate-spin")} />
        </Button>
        <label className="flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border/70 px-2 text-[10px] text-slate-400" title="优先使用 WebView DevTools DOM；不可用时按设备配置回退">
          <input type="checkbox" checked={preferWebView} onChange={(event) => setPreferWebView(event.target.checked)} className="accent-emerald-400" />
          WebView
        </label>
        <label className="flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border/70 px-2 text-[10px] text-slate-400" title="包含不可见节点">
          <input type="checkbox" checked={includeInvisible} onChange={(event) => setIncludeInvisible(event.target.checked)} className="accent-emerald-400" />
          不可见节点
        </label>
        <Button size="sm" onClick={() => void runUidump()} disabled={!serial || capturing} className="h-9 shrink-0 px-3 text-[11px]">
          {capturing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {capturing ? "正在执行 uidump" : "执行 uidump"}
        </Button>
      </Card>

      {(error || deviceError) && (
        <div className="flex max-h-16 shrink-0 items-start gap-2 overflow-auto rounded-lg border border-rose-400/20 bg-rose-400/5 px-3 py-2 text-[10px] text-rose-200">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error || deviceError}</span>
        </div>
      )}

      {capture ? (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.9fr)]">
          <Card className="flex min-h-0 min-w-0 flex-col overflow-hidden border-border/80 bg-[#10151c]/85">
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-2.5">
              <div className="flex min-w-0 items-center gap-2">
                <MonitorPlay className="h-3.5 w-3.5 shrink-0 text-emerald-300" />
                <span className="text-[11px] font-semibold text-slate-200">设备截图</span>
                <Badge variant="outline" className="px-1.5 py-0 text-[9px]">{capture.screen_width} × {capture.screen_height}</Badge>
              </div>
              {activeEntry?.bounds && (
                <span className="truncate font-mono text-[9px] text-emerald-200">
                  [{activeEntry.bounds.left},{activeEntry.bounds.top}][{activeEntry.bounds.right},{activeEntry.bounds.bottom}]
                </span>
              )}
            </div>
            <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black p-2 sm:p-3">
              <div className="relative flex max-h-full max-w-full">
                <img
                  src={`data:${capture.image_mime};base64,${capture.image_base64}`}
                  alt={`${selectedDevice?.model || capture.serial} 截图`}
                  draggable={false}
                  className="block max-h-full max-w-full select-none object-contain"
                />
                <svg
                  aria-label="截图中的 UI 节点边界"
                  className="absolute inset-0 h-full w-full overflow-visible"
                  viewBox={`0 0 ${capture.screen_width} ${capture.screen_height}`}
                  preserveAspectRatio="xMidYMid meet"
                >
                  {boxes.map((entry) => {
                    const bounds = entry.bounds;
                    const active = activePath === entry.path;
                    return (
                      <rect
                        key={entry.path}
                        x={bounds.left}
                        y={bounds.top}
                        width={bounds.width}
                        height={bounds.height}
                        fill={active ? "rgba(52, 211, 153, 0.2)" : "rgba(56, 189, 248, 0.025)"}
                        stroke={active ? "#34d399" : "rgba(56, 189, 248, 0.56)"}
                        strokeWidth={active ? 4 : 1.5}
                        vectorEffect="non-scaling-stroke"
                        className="cursor-crosshair transition-colors"
                        onPointerEnter={() => setHoveredPath(entry.path)}
                        onPointerLeave={() => setHoveredPath(null)}
                        onClick={() => setSelectedPath(entry.path)}
                      >
                        <title>{`${entry.node.attributes.class || entry.node.tag} · ${nodeLabel(entry.node)} · bounds [${bounds.left},${bounds.top}][${bounds.right},${bounds.bottom}]`}</title>
                      </rect>
                    );
                  })}
                </svg>
              </div>
              {boxes.length === 0 && (
                <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-md border border-border/70 bg-[#10151c]/90 px-2.5 py-1.5 text-[10px] text-slate-400">
                  此 dump 没有可映射的 bounds；WebView DOM 节点可能不包含屏幕坐标
                </div>
              )}
            </div>
            {capture.warning && <p className="shrink-0 border-t border-border/60 px-3 py-2 text-[10px] text-amber-200/80">{capture.warning}</p>}
          </Card>

          <Card className="flex min-h-0 min-w-0 flex-col overflow-hidden border-border/80 bg-[#10151c]/85">
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2.5">
              <Layers3 className="h-3.5 w-3.5 text-emerald-300" />
              <span className="text-[11px] font-semibold text-slate-200">节点树</span>
              <Badge variant="outline" className="px-1.5 py-0 text-[9px]">{sourceLabel}</Badge>
              <span className="ml-auto font-mono text-[9px] text-slate-500">{entries.length} nodes · {boxes.length} bounds</span>
            </div>
            {!capture.complete && <p className="shrink-0 border-b border-border/50 px-3 py-2 text-[10px] text-amber-200/80">UIDump 返回不完整</p>}
            <div
              className="code-scroll min-h-0 flex-1 overflow-auto p-2"
              onMouseLeave={() => setHoveredPath(null)}
            >
              {parsed?.root ? (
                <InspectorTreeNode
                  node={parsed.root}
                  path="0"
                  depth={0}
                  activePath={activePath}
                  expandedPaths={expandedPaths}
                  onToggle={toggleExpanded}
                  onHover={setHoveredPath}
                  onSelect={setSelectedPath}
                />
              ) : (
                <p className="p-2 text-[10px] text-amber-200/80">{parsed?.error || "无法解析 UIDump"}</p>
              )}
            </div>
            {activeEntry && (
              <div className="max-h-28 shrink-0 overflow-auto border-t border-border/60 px-3 py-2">
                <p className="mb-1 flex items-center gap-1.5 text-[9px] uppercase tracking-wide text-slate-500"><Braces className="h-3 w-3" />当前节点</p>
                <p className="truncate text-[10px] text-slate-200" title={nodeLabel(activeEntry.node)}>{activeEntry.node.attributes.class || activeEntry.node.tag} · {nodeLabel(activeEntry.node)}</p>
                {activeEntry.node.attributes["resource-id"] && <p className="mt-1 truncate font-mono text-[9px] text-slate-500">{activeEntry.node.attributes["resource-id"]}</p>}
                {activeEntry.bounds && <p className="mt-1 font-mono text-[9px] text-emerald-200">bounds [{activeEntry.bounds.left},{activeEntry.bounds.top}][{activeEntry.bounds.right},{activeEntry.bounds.bottom}]</p>}
              </div>
            )}
            <div className="shrink-0 border-t border-border/60">
              <div className="flex items-center gap-2 px-3 py-2">
                <Code2 className="h-3 w-3 text-emerald-300" />
                <span className="text-[10px] font-medium text-slate-300">生成 Nier 代码</span>
                {selectedEntry && (
                  <span className="min-w-0 flex-1 truncate text-[9px] text-slate-500" title={nodeLabel(selectedEntry.node)}>
                    {nodeLabel(selectedEntry.node)}
                  </span>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  title="复制生成的 Nier 代码"
                  onClick={() => void copyGeneratedCode()}
                  disabled={!generatedCode}
                  className="h-7 shrink-0 gap-1 px-2 text-[9px] text-slate-300"
                >
                  {copyStatus === "代码已复制" ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                  {copyStatus || "复制"}
                </Button>
              </div>
              {generatedCode ? (
                <>
                  <pre className="code-scroll max-h-40 overflow-auto border-t border-border/40 bg-[#0b0f14] p-3 font-mono text-[9px] leading-relaxed text-slate-300">{generatedCode.code}</pre>
                  {generatedCode.warning && <p className="border-t border-border/40 px-3 py-2 text-[9px] text-amber-200/80">{generatedCode.warning}</p>}
                </>
              ) : (
                <p className="border-t border-border/40 px-3 py-2 text-[9px] text-slate-500">点击截图 bounds 或节点树中的组件以生成代码</p>
              )}
            </div>
            <details className="shrink-0 border-t border-border/60">
              <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-2 text-[10px] text-slate-400"><Code2 className="h-3 w-3" />CLI uidump 输出</summary>
              <pre className="code-scroll max-h-40 overflow-auto border-t border-border/40 bg-[#0b0f14] p-3 font-mono text-[9px] leading-relaxed text-slate-400">{capture.tree_text}</pre>
            </details>
            <details className="shrink-0 border-t border-border/60">
              <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-2 text-[10px] text-slate-400"><Code2 className="h-3 w-3" />原始 XML / HTML</summary>
              <pre className="code-scroll max-h-40 overflow-auto border-t border-border/40 bg-[#0b0f14] p-3 font-mono text-[9px] leading-relaxed text-slate-500">{capture.xml}</pre>
            </details>
          </Card>
        </div>
      ) : (
        <Card className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 border-border/80 bg-[#10151c]/70 px-5 text-center">
          {capturing ? <LoaderCircle className="h-7 w-7 animate-spin text-emerald-300" /> : <MonitorPlay className="h-8 w-8 text-slate-600" />}
          <p className="text-xs font-medium text-slate-300">{capturing ? "正在读取截图和 UI 层级…" : "选择设备后运行 uidump"}</p>
          <p className="max-w-lg text-[10px] leading-relaxed text-slate-500">
            在截图上悬浮或点击 bounds 可定位到对应节点；悬浮树节点会反向高亮截图区域。操作只读取设备，不会点击或保存截图。
          </p>
          {deviceError && <p className="text-[10px] text-amber-200/80">{deviceError}</p>}
        </Card>
      )}
    </div>
  );
}

function InspectorTreeNode({
  node,
  path,
  depth,
  activePath,
  expandedPaths,
  onToggle,
  onHover,
  onSelect,
}: {
  node: UiTreeNode;
  path: string;
  depth: number;
  activePath: string | null;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  onHover: (path: string | null) => void;
  onSelect: (path: string) => void;
}) {
  const hasChildren = node.children.length > 0;
  const pathIsAncestor = Boolean(activePath?.startsWith(`${path}/`));
  const isOpen = expandedPaths.has(path) || pathIsAncestor;
  const active = activePath === path;
  const text = node.attributes.text || node.attributes["content-desc"] || node.text;
  const bounds = node.attributes.bounds;

  return (
    <div className="min-w-0">
      <div
        id={nodeElementId(path)}
        onMouseEnter={() => onHover(path)}
        onClick={() => onSelect(path)}
        title={`${node.attributes.class || node.tag}${text ? ` · ${text}` : ""}${bounds ? ` · ${bounds}` : ""}`}
        className={cn(
          "group flex min-w-0 cursor-pointer items-start gap-1.5 rounded px-1.5 py-1 scroll-mt-2 transition-colors",
          active ? "bg-emerald-400/10 ring-1 ring-inset ring-emerald-400/30" : "hover:bg-slate-800/70",
        )}
        style={{ paddingLeft: `${depth * 12 + 6}px` }}
      >
        <button
          type="button"
          aria-label={`${isOpen ? "收起" : "展开"} ${node.tag}`}
          aria-expanded={hasChildren ? isOpen : undefined}
          disabled={!hasChildren}
          onClick={(event) => {
            event.stopPropagation();
            onToggle(path);
          }}
          className="mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded text-slate-500 disabled:opacity-30"
        >
          {hasChildren ? (isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />) : <span className="h-1 w-1 rounded-full bg-slate-600" />}
        </button>
        <span className="shrink-0 font-mono text-[9px] text-sky-300">{node.tag}</span>
        {node.attributes.class && <span className="min-w-0 truncate font-mono text-[9px] text-violet-200">{node.attributes.class}</span>}
        {text && <span className="min-w-0 truncate text-[9px] text-slate-300">{text}</span>}
        {bounds && <span className="ml-auto shrink-0 font-mono text-[8px] text-slate-600">{bounds}</span>}
      </div>
      {hasChildren && isOpen && (
        <div className="border-l border-slate-700/60">
          {node.children.map((child, index) => (
            <InspectorTreeNode
              key={`${path}/${index}`}
              node={child}
              path={`${path}/${index}`}
              depth={depth + 1}
              activePath={activePath}
              expandedPaths={expandedPaths}
              onToggle={onToggle}
              onHover={onHover}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}
