import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Activity,
  ArrowDown,
  Bot,
  Braces,
  Check,
  ChevronDown,
  CircleDot,
  Clock3,
  Code2,
  FileCode2,
  Layers3,
  LoaderCircle,
  Play,
  Radio,
  RefreshCw,
  Square,
  Terminal,
  Workflow,
  XCircle,
} from "lucide-react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./components/ui/dialog";
import { ScrollArea } from "./components/ui/scroll-area";
import { cn } from "./lib/utils";

type ScriptInfo = { path: string; name: string; description: string };
type RunState = {
  id: string | null;
  script: string | null;
  status: "idle" | "starting" | "running" | "stopping" | "completed" | "stopped" | "failed";
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  error?: string | null;
};
type WebEvent = {
  type: string;
  event_id: number;
  timestamp: string;
  run_id?: string;
  script?: string;
  category?: string;
  level?: string;
  message?: string;
  details?: Record<string, unknown>;
  step_id?: number | null;
  stream?: string;
  text?: string;
  status?: string;
  exit_code?: number | null;
  error?: string | null;
};
type ApiState = { run: RunState; events: WebEvent[] };
type StepNodeData = {
  event: WebEvent;
  index: number;
  selected: boolean;
  active: boolean;
  onSelect: (id: number) => void;
};
type StepNodeType = Node<StepNodeData, "step">;

const initialRun: RunState = {
  id: null,
  script: null,
  status: "idle",
  started_at: null,
  finished_at: null,
  exit_code: null,
};

function localTime(value?: string | null) {
  if (!value) return "--:--:--";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "--:--:--"
    : date.toLocaleTimeString("zh-CN", { hour12: false });
}

function shortName(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventTitle(event: WebEvent) {
  const details = event.details ?? {};
  const action = details.action ?? details.operation ?? details.name ?? details.provider;
  const message = event.message || event.category || "Event";
  return action ? `${shortName(String(message))} · ${String(action)}` : shortName(message);
}

function eventSubtitle(event: WebEvent) {
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

function isPathEvent(event: WebEvent) {
  return event.type === "log" && [
    "STEP",
    "TOOL CALL",
    "OCR RESULT",
    "JEV RESULT",
    "LLM RESULT",
  ].includes(event.category ?? "");
}

function isBusy(status: RunState["status"]) {
  return ["starting", "running", "stopping"].includes(status);
}

function statusLabel(status: RunState["status"]) {
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

function StatusIcon({ status }: { status: RunState["status"] }) {
  if (status === "running" || status === "starting" || status === "stopping") {
    return <LoaderCircle className="h-3.5 w-3.5 animate-spin" />;
  }
  if (status === "completed") return <Check className="h-3.5 w-3.5" />;
  if (status === "failed") return <XCircle className="h-3.5 w-3.5" />;
  return <CircleDot className="h-3.5 w-3.5" />;
}

function statusVariant(status: RunState["status"]) {
  if (status === "completed") return "success" as const;
  if (status === "stopped") return "warning" as const;
  if (status === "failed") return "danger" as const;
  if (isBusy(status)) return "warning" as const;
  return "outline" as const;
}

function NodeIcon({ category }: { category?: string }) {
  if (category === "TOOL CALL") return <Bot className="h-4 w-4" />;
  if (category === "JEV RESULT" || category === "LLM RESULT") return <Braces className="h-4 w-4" />;
  if (category === "OCR RESULT") return <Activity className="h-4 w-4" />;
  return <Workflow className="h-4 w-4" />;
}

function StepNode({ data }: NodeProps<StepNodeType>) {
  const { event, index, selected, active, onSelect } = data;
  const status = String(event.details?.status ?? "");
  const failed = status === "failed";
  const completed = ["ok", "success", "done"].includes(status);
  return (
    <div
      onClick={() => onSelect(event.event_id)}
      className={cn(
        "step-node w-[390px] cursor-pointer rounded-xl border bg-[#151b23] p-4 shadow-xl transition-all",
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
            <Badge variant={failed ? "danger" : completed ? "success" : "outline"} className="shrink-0 px-2 py-0">
              {failed ? "失败" : completed ? "完成" : event.category === "STEP" ? "STEP" : "MODEL"}
            </Badge>
          </div>
          <p className="mt-1 truncate text-xs text-slate-400">{eventSubtitle(event)}</p>
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

const nodeTypes = { step: StepNode };

function FollowLatest({ eventId, index, running }: { eventId?: number; index: number; running: boolean }) {
  const { setCenter } = useReactFlow();
  useEffect(() => {
    if (running && eventId !== undefined) {
      setCenter(255, index * 146 + 84, { zoom: 0.82, duration: 320 });
    }
  }, [eventId, index, running, setCenter]);
  return null;
}

function stringify(value: unknown) {
  if (value === undefined) return "暂无详细内容";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function detailTitle(event: WebEvent) {
  if (event.category === "HTTP REQUEST") return "Request";
  if (event.category === "HTTP RESPONSE") return "Response";
  if (event.type === "console") return event.stream === "stderr" ? "stderr" : "stdout";
  if (event.type.startsWith("run.")) return "运行状态";
  return event.category || "STEP";
}

function DetailEvent({ event }: { event: WebEvent }) {
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
      <pre className="code-scroll mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[#0b0f14] p-3 font-mono text-[10px] leading-relaxed text-slate-300">{stringify(raw)}</pre>
      {(isRequest || isResponse) && (
        <div className="mt-2 flex items-center gap-1.5 text-[9px] text-slate-600">
          <Radio className="h-3 w-3" />
          <span>已应用日志脱敏与 4 KB 截断</span>
        </div>
      )}
    </div>
  );
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload as T;
}

export default function App() {
  const [scripts, setScripts] = useState<ScriptInfo[]>([]);
  const [selectedScript, setSelectedScript] = useState("");
  const [run, setRun] = useState<RunState>(initialRun);
  const [events, setEvents] = useState<WebEvent[]>([]);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);

  const mergeEvent = useCallback((incoming: WebEvent) => {
    if (incoming.type === "run.started") {
      setSelectedEventId(null);
      setEvents([incoming]);
      setRun((current) => ({
        ...current,
        id: incoming.run_id ?? null,
        script: incoming.script ?? null,
        status: "starting",
        started_at: incoming.timestamp,
        finished_at: null,
        exit_code: null,
        error: null,
      }));
      return;
    }
    setEvents((current) => {
      if (current.some((event) => event.event_id === incoming.event_id)) return current;
      return [...current, incoming].slice(-2500);
    });
    if (incoming.type === "run.running") setRun((current) => ({ ...current, status: "running" }));
    if (incoming.type === "run.stopping") setRun((current) => ({ ...current, status: "stopping" }));
    if (incoming.type === "run.finished") {
      setRun((current) => ({
        ...current,
        status: incoming.status as RunState["status"],
        finished_at: incoming.timestamp,
        exit_code: incoming.exit_code ?? null,
        error: incoming.error ?? null,
      }));
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    Promise.all([
      fetchJson<{ scripts: ScriptInfo[] }>("/api/scripts"),
      fetchJson<ApiState>("/api/state"),
    ]).then(([scriptResponse, state]) => {
      if (!mounted) return;
      setScripts(scriptResponse.scripts);
      setSelectedScript((current) => current || scriptResponse.scripts[0]?.path || "");
      setRun(state.run);
      setEvents(state.events);
      setConnected(true);
    }).catch((reason: Error) => {
      if (mounted) setError(reason.message);
    });

    const source = new EventSource("/api/events");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (message) => {
      try {
        mergeEvent(JSON.parse(message.data) as WebEvent);
      } catch {
        setError("无法读取实时运行事件");
      }
    };
    return () => {
      mounted = false;
      source.close();
    };
  }, [mergeEvent]);

  const pathEvents = useMemo(() => events.filter(isPathEvent), [events]);
  const activeStep = [...events].reverse().find((event) => event.type === "log" && event.category === "STEP");
  const selectedEvent = selectedEventId === null
    ? pathEvents.at(-1)
    : pathEvents.find((event) => event.event_id === selectedEventId) ?? pathEvents.at(-1);
  const selectedStepId = selectedEvent?.category === "STEP"
    ? selectedEvent.event_id
    : selectedEvent?.step_id ?? activeStep?.event_id;
  const requestEvents = events.filter((event) =>
    event.type === "log" && ["HTTP REQUEST", "HTTP RESPONSE"].includes(event.category ?? "") &&
    (selectedStepId === undefined || selectedStepId === null || event.step_id === selectedStepId),
  );
  const selectedScriptInfo = scripts.find((script) => script.path === selectedScript);
  const isRunning = isBusy(run.status);
  const successCount = events.filter((event) => event.type === "log" && event.category === "STEP" && event.details?.status === "ok").length;
  const failureCount = events.filter((event) => event.type === "log" && event.category === "STEP" && event.details?.status === "failed").length;

  const handleRun = async () => {
    setError("");
    try {
      const state = await fetchJson<ApiState>("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script: selectedScript, confirmed: true }),
      });
      setRun(state.run);
      setShowConfirm(false);
      setConfirmed(false);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const handleStop = async () => {
    setError("");
    try {
      const state = await fetchJson<ApiState>("/api/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      setRun(state.run);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const onSelectNode = useCallback((id: number) => setSelectedEventId(id), []);
  const nodes = useMemo<Node<StepNodeData>[]>(() => pathEvents.map((event, index) => ({
    id: String(event.event_id),
    type: "step",
    position: { x: 60, y: index * 146 + 36 },
    data: {
      event,
      index: index + 1,
      selected: selectedEvent?.event_id === event.event_id,
      active: activeStep?.event_id === event.event_id && isRunning,
      onSelect: onSelectNode,
    },
  })), [pathEvents, selectedEvent?.event_id, activeStep?.event_id, isRunning, onSelectNode]);
  const edges = useMemo<Edge[]>(() => pathEvents.slice(1).map((event, index) => ({
    id: `path-${pathEvents[index].event_id}-${event.event_id}`,
    source: String(pathEvents[index].event_id),
    target: String(event.event_id),
    type: "smoothstep",
    animated: isRunning && index === pathEvents.length - 2,
    style: { stroke: isRunning && index === pathEvents.length - 2 ? "#42cea3" : "#394958", strokeWidth: 1.5 },
  })), [pathEvents, isRunning]);

  return (
    <div className="min-h-screen text-foreground">
      <header className="sticky top-0 z-20 border-b border-border/80 bg-[#0b0e13]/90 backdrop-blur-xl">
        <div className="mx-auto flex h-[68px] max-w-[1800px] items-center justify-between px-5 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/10 text-emerald-300">
              <Workflow className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold tracking-wide text-slate-100">NIER</span>
                <span className="text-xs text-slate-600">/</span>
                <span className="text-xs font-medium text-slate-400">Execution Studio</span>
              </div>
              <p className="mt-0.5 hidden text-[10px] tracking-wide text-slate-600 sm:block">ANDROID AUTOMATION · LIVE TRACE</p>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:gap-4">
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <span className={cn("h-1.5 w-1.5 rounded-full", connected ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-rose-400")} />
              <span>{connected ? "本地连接正常" : "正在连接"}</span>
            </div>
            <div className="hidden h-5 w-px bg-border sm:block" />
            <Badge variant={statusVariant(run.status)} className="gap-1.5 px-2.5 py-1">
              <StatusIcon status={run.status} />
              {statusLabel(run.status)}
            </Badge>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1800px] px-4 py-5 sm:px-5 lg:px-8 lg:py-7">
        <div className="mb-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-emerald-300/80">
              <span className="h-px w-5 bg-emerald-400/60" />
              Run observability
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-100 sm:text-[28px]">执行路径</h1>
            <p className="mt-1.5 max-w-2xl text-sm text-slate-500">从脚本启动到每次设备操作，实时追踪执行步骤与模型通信。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="relative min-w-[260px] flex-1 xl:flex-none">
              <FileCode2 className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <select
                value={selectedScript}
                onChange={(event) => setSelectedScript(event.target.value)}
                disabled={isRunning || scripts.length === 0}
                className="h-10 w-full appearance-none rounded-md border border-input bg-[#111720] pl-9 pr-9 text-sm text-slate-200 outline-none transition-colors focus:border-emerald-400/60 disabled:opacity-50 xl:w-[330px]"
              >
                {scripts.length === 0 && <option value="">未找到 Python 脚本</option>}
                {scripts.map((script) => <option key={script.path} value={script.path}>{script.path}</option>)}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            </div>
            {isRunning ? (
              <Button variant="destructive" onClick={handleStop} className="gap-2">
                <Square className="h-3.5 w-3.5 fill-current" />
                停止运行
              </Button>
            ) : (
              <Button onClick={() => { setConfirmed(false); setShowConfirm(true); }} disabled={!selectedScript} className="gap-2 bg-emerald-400 text-slate-950 hover:bg-emerald-300">
                <Play className="h-3.5 w-3.5 fill-current" />
                运行脚本
              </Button>
            )}
          </div>
        </div>

        {error && (
          <div className="mb-4 flex items-center justify-between rounded-lg border border-rose-400/20 bg-rose-400/5 px-4 py-3 text-sm text-rose-200">
            <span>{error}</span>
            <button className="text-rose-300/70 hover:text-rose-200" onClick={() => setError("")}><XCircle className="h-4 w-4" /></button>
          </div>
        )}

        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Card className="border-border/70 bg-[#10151c]/80">
            <CardContent className="flex items-center justify-between p-4">
              <div><p className="text-[11px] text-slate-500">当前脚本</p><p className="mt-1 truncate text-sm font-medium text-slate-200">{run.script || selectedScriptInfo?.path || "尚未选择"}</p></div>
              <FileCode2 className="h-4 w-4 shrink-0 text-slate-500" />
            </CardContent>
          </Card>
          <Card className="border-border/70 bg-[#10151c]/80">
            <CardContent className="flex items-center justify-between p-4">
              <div><p className="text-[11px] text-slate-500">路径节点</p><p className="mt-1 text-lg font-semibold tabular-nums text-slate-100">{pathEvents.length.toString().padStart(2, "0")}</p></div>
              <Layers3 className="h-4 w-4 text-cyan-300/70" />
            </CardContent>
          </Card>
          <Card className="border-border/70 bg-[#10151c]/80">
            <CardContent className="flex items-center justify-between p-4">
              <div><p className="text-[11px] text-slate-500">成功步骤</p><p className="mt-1 text-lg font-semibold tabular-nums text-emerald-300">{successCount.toString().padStart(2, "0")}</p></div>
              <Check className="h-4 w-4 text-emerald-400/70" />
            </CardContent>
          </Card>
          <Card className="border-border/70 bg-[#10151c]/80">
            <CardContent className="flex items-center justify-between p-4">
              <div><p className="text-[11px] text-slate-500">失败步骤</p><p className="mt-1 text-lg font-semibold tabular-nums text-rose-300">{failureCount.toString().padStart(2, "0")}</p></div>
              <XCircle className="h-4 w-4 text-rose-400/70" />
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
          <Card className="overflow-hidden border-border/80 bg-[#10151c]/85">
            <CardHeader className="flex-row items-center justify-between border-b border-border/70 py-4">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-800/70 text-slate-300"><Workflow className="h-4 w-4" /></div>
                <div>
                  <CardTitle className="text-sm">运行拓扑</CardTitle>
                  <p className="mt-1 text-[11px] text-slate-500">按实际事件顺序连接的执行轨迹</p>
                </div>
              </div>
              <div className="flex items-center gap-2 text-[10px] text-slate-500">
                <span className="hidden items-center gap-1.5 sm:flex"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />已完成</span>
                <span className="hidden items-center gap-1.5 sm:flex"><span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />当前节点</span>
                <Button variant="ghost" size="icon" title="刷新页面数据" onClick={() => window.location.reload()} className="h-8 w-8 text-slate-500"><RefreshCw className="h-3.5 w-3.5" /></Button>
              </div>
            </CardHeader>
            <div className="relative h-[580px] min-h-[440px] lg:h-[calc(100vh-330px)] lg:min-h-[610px]">
              {nodes.length ? (
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  onNodeClick={(_, node) => setSelectedEventId(Number(node.id))}
                  fitView
                  fitViewOptions={{ padding: 0.25, minZoom: 0.3, maxZoom: 0.9 }}
                  minZoom={0.18}
                  maxZoom={1.15}
                  nodesConnectable={false}
                  nodesDraggable={false}
                  elementsSelectable
                  proOptions={{ hideAttribution: true }}
                  className="flow-canvas"
                >
                  <FollowLatest eventId={pathEvents.at(-1)?.event_id} index={pathEvents.length - 1} running={isRunning} />
                  <Background color="#26313d" gap={22} size={1} />
                  <Controls showInteractive={false} />
                  <MiniMap nodeColor={(node) => node.id === String(activeStep?.event_id) && isRunning ? "#43d4a6" : "#65798a"} pannable zoomable />
                </ReactFlow>
              ) : (
                <div className="flow-canvas flex h-full flex-col items-center justify-center px-6 text-center">
                  <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-300/10 bg-emerald-300/[0.04] text-emerald-300/70">
                    <Workflow className="h-7 w-7" />
                    <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full border border-[#10151c] bg-emerald-400 text-[10px] font-bold text-slate-950">0</span>
                  </div>
                  <h2 className="mt-5 text-sm font-medium text-slate-300">等待执行事件</h2>
                  <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">选择一个 Python 脚本并启动运行。每个 STEP、模型调用和结果都会按实际顺序出现在这张路径图中。</p>
                  <div className="mt-5 flex items-center gap-2 rounded-full border border-border/70 bg-[#131922] px-3 py-1.5 text-[10px] text-slate-500"><Radio className="h-3 w-3 text-emerald-400" />等待本地运行流</div>
                </div>
              )}
            </div>
          </Card>

          <Card className="flex min-h-[580px] flex-col overflow-hidden border-border/80 bg-[#10151c]/85 xl:sticky xl:top-[88px] xl:h-[calc(100vh-108px)] xl:min-h-[610px]">
            <CardHeader className="border-b border-border/70 py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-400/10 text-sky-300"><Terminal className="h-4 w-4" /></div>
                  <div><CardTitle className="text-sm">执行日志</CardTitle><p className="mt-1 text-[11px] text-slate-500">STEP · Request / Response</p></div>
                </div>
                <Badge variant={statusVariant(run.status)} className="gap-1.5"><StatusIcon status={run.status} />{statusLabel(run.status)}</Badge>
              </div>
              {selectedEvent && (
                <div className="mt-4 flex items-start gap-2 rounded-md border border-border/70 bg-[#0e131a] px-3 py-2.5">
                  <span className="mt-0.5 font-mono text-[10px] text-emerald-300">#{String(selectedEvent.event_id).padStart(3, "0")}</span>
                  <div className="min-w-0"><p className="truncate text-xs font-medium text-slate-200">{eventTitle(selectedEvent)}</p><p className="mt-1 text-[10px] text-slate-500">{localTime(selectedEvent.timestamp)} · {eventSubtitle(selectedEvent)}</p></div>
                </div>
              )}
            </CardHeader>
            <div className="flex items-center justify-between border-b border-border/60 px-5 py-3">
              <div className="flex items-center gap-2 text-[10px] text-slate-500"><Clock3 className="h-3.5 w-3.5" /><span>{requestEvents.length} 条通信记录</span></div>
              <span className="max-w-[180px] truncate text-[10px] text-slate-500">{selectedScriptInfo?.path || run.script || "未选择脚本"}</span>
            </div>
            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-3 p-4">
                {selectedEvent && selectedEvent.category === "STEP" && (
                  <div className="rounded-lg border border-border/80 bg-[#10151c] p-3">
                    <div className="mb-2 flex items-center justify-between"><span className="text-[11px] font-semibold text-slate-300">STEP 详情</span><Badge variant="outline">{selectedEvent.level || "v"}</Badge></div>
                    <pre className="code-scroll max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[#0b0f14] p-3 font-mono text-[10px] leading-relaxed text-slate-300">{stringify(selectedEvent.details ?? {})}</pre>
                  </div>
                )}
                {requestEvents.map((event) => <DetailEvent key={event.event_id} event={event} />)}
                {requestEvents.length === 0 && (
                  <div className="rounded-lg border border-dashed border-border/80 bg-[#0e131a]/70 px-4 py-7 text-center">
                    <ArrowDown className="mx-auto h-4 w-4 text-slate-600" />
                    <p className="mt-3 text-xs font-medium text-slate-400">当前步骤没有请求 / 响应</p>
                    <p className="mt-1.5 text-[10px] leading-relaxed text-slate-600">当步骤调用模型或外部接口时，通信明细会关联到对应的 STEP。</p>
                  </div>
                )}
                {events.filter((event) => event.type === "console" || event.type === "run.finished").slice(-8).map((event) => (
                  <DetailEvent key={event.event_id} event={event} />
                ))}
              </div>
            </ScrollArea>
            <div className="flex items-center justify-between border-t border-border/70 px-4 py-3 text-[10px] text-slate-600">
              <span className="flex items-center gap-1.5"><Radio className={cn("h-3 w-3", connected && "text-emerald-400")} />实时事件流</span>
              <span className="font-mono">{events.length} events</span>
            </div>
          </Card>
        </div>

        <footer className="mt-5 flex flex-col items-start justify-between gap-2 border-t border-border/50 py-4 text-[10px] text-slate-600 sm:flex-row sm:items-center">
          <span className="flex items-center gap-2"><Code2 className="h-3.5 w-3.5" />Nier 结构化事件按日志策略脱敏；脚本输出按原样展示</span>
          <span className="font-mono">NIER WEB / {run.id ? run.id.slice(0, 8) : "READY"}</span>
        </footer>
      </main>

      <Dialog open={showConfirm} onOpenChange={setShowConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>运行所选脚本？</DialogTitle>
            <DialogDescription>
              脚本会以当前用户权限在本机执行，也可能连接已配置的 Android 设备或调用模型服务。只运行你信任并获准使用的脚本。
            </DialogDescription>
          </DialogHeader>
          <div className="my-4 rounded-lg border border-border bg-[#0e131a] p-3">
            <div className="flex items-center gap-2 text-xs font-medium text-slate-200"><FileCode2 className="h-4 w-4 text-emerald-300" />{selectedScriptInfo?.path}</div>
            <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{selectedScriptInfo?.description}</p>
          </div>
          <label className="flex cursor-pointer items-start gap-3 rounded-md px-1 py-1 text-xs leading-relaxed text-slate-400">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 h-4 w-4 accent-emerald-400" />
            <span>我已确认该脚本可信，并授权本次运行可能产生的设备或模型操作。</span>
          </label>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setShowConfirm(false)}>取消</Button>
            <Button disabled={!confirmed} onClick={handleRun} className="gap-2 bg-emerald-400 text-slate-950 hover:bg-emerald-300"><Play className="h-3.5 w-3.5 fill-current" />确认运行</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
