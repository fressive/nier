import { useCallback, useEffect, useMemo, useState } from "react";
import { type Edge, type Node } from "@xyflow/react";
import { ClipboardList, Code2, MonitorPlay, Workflow, XCircle } from "lucide-react";
import { ExecutionGraph } from "./components/execution-graph";
import { LogSidebar } from "./components/log-sidebar";
import { RunConfirmDialog } from "./components/run-confirm-dialog";
import { RunMetrics } from "./components/run-metrics";
import { RunStatusBadge } from "./components/status-indicator";
import { RunToolbar } from "./components/run-toolbar";
import { ScreenPreview } from "./components/screen-preview";
import { fetchJson, postJson } from "./lib/api";
import { isBusy, isPathEvent, isResponseOrResultEvent, localTime } from "./lib/dashboard";
import { cn } from "./lib/utils";
import { initialRun, type ApiState, type DebugCommand, type RunState, type ScriptInfo, type StepNodeData, type WebEvent } from "./types";

const NODE_SPACING = 146;
type DashboardPanel = "graph" | "logs" | "preview";

export default function App() {
  const [scripts, setScripts] = useState<ScriptInfo[]>([]);
  const [selectedScript, setSelectedScript] = useState("");
  const [run, setRun] = useState<RunState>(initialRun);
  const [events, setEvents] = useState<WebEvent[]>([]);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [pendingDebug, setPendingDebug] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [activePanel, setActivePanel] = useState<DashboardPanel>("graph");

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
        debug: incoming.debug ?? false,
        debug_state: incoming.debug ? "running" : "inactive",
        debug_location: null,
        execution_location: null,
      }));
      return;
    }
    if (incoming.type === "execution.location") {
      setRun((current) => ({
        ...current,
        execution_location: {
          file: incoming.file ?? "",
          line: incoming.line ?? 0,
          function: incoming.function ?? "",
        },
      }));
      return;
    }
    setEvents((current) => {
      if (current.some((event) => event.event_id === incoming.event_id)) return current;
      return [...current, incoming].slice(-2500);
    });
    if (incoming.type === "run.running") setRun((current) => ({ ...current, status: "running" }));
    if (incoming.type === "run.stopping") setRun((current) => ({ ...current, status: "stopping", debug_state: current.debug ? "running" : current.debug_state }));
    if (incoming.type === "debug.paused") {
      setRun((current) => ({
        ...current,
        debug_state: "paused",
        debug_location: {
          step_id: incoming.step_id ?? null,
          category: incoming.category ?? "STEP",
          message: incoming.message ?? "",
          details: incoming.details ?? {},
          depth: incoming.depth ?? 0,
          file: incoming.file ?? "",
          line: incoming.line ?? 0,
          function: incoming.function ?? "",
          stack: incoming.stack ?? [],
        },
      }));
    }
    if (incoming.type === "debug.resumed") setRun((current) => ({ ...current, debug_state: "running" }));
    if (incoming.type === "run.finished") {
      setRun((current) => ({
        ...current,
        status: incoming.status as RunState["status"],
        finished_at: incoming.timestamp,
        exit_code: incoming.exit_code ?? null,
        error: incoming.error ?? null,
        debug_state: current.debug ? "finished" : "inactive",
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
      setRun((current) => ({
        ...state.run,
        execution_location: current.execution_location ?? state.run.execution_location,
      }));
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
  const activeStep = [...pathEvents].reverse().find((event) => event.type === "log" && event.category === "STEP");
  const selectedEvent = selectedEventId === null
    ? pathEvents.at(-1)
    : pathEvents.find((event) => event.event_id === selectedEventId) ?? pathEvents.at(-1);
  const selectedScriptInfo = scripts.find((script) => script.path === selectedScript);
  const busy = isBusy(run.status);
  const successCount = pathEvents.filter((event) =>
    event.type === "log" && event.category === "STEP" && (
      event.details?.status === "ok"
      || (event.message === "read" && events.some((candidate) =>
        candidate.category === "READ RESULT" && candidate.step_id === event.event_id,
      ))
    ),
  ).length;
  const failureCount = pathEvents.filter((event) => event.type === "log" && event.category === "STEP" && event.details?.status === "failed").length;

  const handleStart = (debug: boolean) => {
    setPendingDebug(debug);
    setConfirmed(false);
    setShowConfirm(true);
  };

  const handleRun = async () => {
    setError("");
    try {
      const state = await postJson<ApiState>("/api/run", { script: selectedScript, confirmed: true, debug: pendingDebug });
      setRun((current) => ({
        ...state.run,
        execution_location: current.id === state.run.id
          ? current.execution_location ?? state.run.execution_location
          : state.run.execution_location,
      }));
      setShowConfirm(false);
      setConfirmed(false);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const handleStop = async () => {
    setError("");
    try {
      const state = await postJson<ApiState>("/api/stop", {});
      setRun(state.run);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const handleDebugCommand = async (command: DebugCommand) => {
    setError("");
    try {
      const state = await postJson<ApiState>("/api/debug", { command });
      setRun(state.run);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const onSelectNode = useCallback((id: number) => setSelectedEventId(id), []);
  const nodes = useMemo<Node<StepNodeData>[]>(() => pathEvents.map((event, index) => {
    const relatedResponses = events.filter((candidate) =>
      isResponseOrResultEvent(candidate) && candidate.step_id === event.event_id,
    );
    const response = isResponseOrResultEvent(event)
      ? event
      : relatedResponses.filter((candidate) => candidate.category === "READ RESULT").at(-1)
        ?? relatedResponses.filter((candidate) => candidate.category?.endsWith("RESULT")).at(-1)
        ?? relatedResponses.at(-1);
    return {
      id: String(event.event_id),
      type: "step",
      position: { x: 60, y: index * NODE_SPACING + 36 },
      data: {
        event,
        response,
        index: index + 1,
        selected: selectedEvent?.event_id === event.event_id,
        active: activeStep?.event_id === event.event_id && busy,
        onSelect: onSelectNode,
      },
    };
  }), [pathEvents, events, selectedEvent?.event_id, activeStep?.event_id, busy, onSelectNode]);
  const edges = useMemo<Edge[]>(() => pathEvents.slice(1).map((event, index) => ({
    id: `path-${pathEvents[index].event_id}-${event.event_id}`,
    source: String(pathEvents[index].event_id),
    target: String(event.event_id),
    type: "smoothstep",
    animated: busy && index === pathEvents.length - 2,
    style: { stroke: busy && index === pathEvents.length - 2 ? "#42cea3" : "#394958", strokeWidth: 1.5 },
  })), [pathEvents, busy]);

  return (
    <div className="app-shell flex h-dvh min-h-0 flex-col overflow-hidden text-foreground">
      <header className="z-20 h-14 shrink-0 border-b border-border/80 bg-[#0b0e13]/90 backdrop-blur-xl">
        <div className="mx-auto flex h-full w-full items-center justify-between px-3 sm:px-5 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/10 text-emerald-300"><Workflow className="h-4 w-4" /></div>
            <div>
              <div className="flex items-center gap-2"><span className="text-sm font-semibold tracking-wide text-slate-100">NIER</span><span className="hidden text-xs text-slate-600 sm:inline">/</span><span className="hidden text-xs font-medium text-slate-400 sm:inline">Execution Studio</span></div>
              <p className="mt-0.5 hidden text-[9px] tracking-wide text-slate-600 sm:block">ANDROID AUTOMATION · LIVE TRACE</p>
            </div>
          </div>
          <div className="flex min-w-0 items-center gap-2 sm:gap-4">
            <div className="flex items-center gap-2 text-[10px] text-slate-500 sm:text-[11px]"><span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", connected ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-rose-400")} /><span className="hidden sm:inline">{connected ? "本地连接正常" : "正在连接"}</span></div>
            <div className="hidden h-5 w-px bg-border sm:block" />
            <RunStatusBadge status={run.status} />
          </div>
        </div>
      </header>

      <main className="mx-auto flex min-h-0 w-full flex-1 flex-col gap-2 overflow-hidden px-3 py-2 sm:px-5 lg:px-6">
        <div className="flex shrink-0 flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            <h1 className="shrink-0 text-base font-semibold tracking-tight text-slate-100 sm:text-lg">执行路径</h1>
            <p className="hidden truncate text-xs text-slate-500 lg:block">实时追踪执行步骤与模型通信</p>
          </div>
          <RunToolbar
            scripts={scripts}
            selectedScript={selectedScript}
            busy={busy}
            onSelect={setSelectedScript}
            onStart={handleStart}
            onStop={handleStop}
          />
        </div>

        {error && (
          <div className="flex max-h-14 shrink-0 items-center justify-between gap-3 overflow-hidden rounded-lg border border-rose-400/20 bg-rose-400/5 px-3 py-2 text-xs text-rose-200">
            <span className="min-w-0 break-words">{error}</span>
            <button className="shrink-0 text-rose-300/70 hover:text-rose-200" onClick={() => setError("")} aria-label="关闭错误提示"><XCircle className="h-4 w-4" /></button>
          </div>
        )}

        <RunMetrics script={run.script || selectedScript} pathCount={pathEvents.length} successCount={successCount} failureCount={failureCount} />

        <div className="flex min-w-0 shrink-0 items-center gap-2 rounded-lg border border-border/70 bg-[#10151c]/80 px-3 py-2">
          <Code2 className="h-3.5 w-3.5 shrink-0 text-emerald-300" />
          <span className="shrink-0 text-[10px] text-slate-500">当前代码行</span>
          {run.execution_location ? (
            <>
              <code
                className="min-w-0 truncate text-[11px] font-medium text-emerald-200"
                title={`${run.execution_location.file}:${run.execution_location.line}`}
              >
                {run.execution_location.file}:{run.execution_location.line}
              </code>
              <span className="min-w-0 truncate text-[10px] text-slate-500">{run.execution_location.function}</span>
            </>
          ) : (
            <span className="truncate text-[10px] text-slate-600">{busy ? "等待 Python 执行…" : "暂无运行位置"}</span>
          )}
        </div>

        <nav aria-label="运行面板" className="flex h-9 shrink-0 items-center gap-1 rounded-lg border border-border/70 bg-[#10151c]/80 p-1 xl:hidden">
          {([
            { id: "graph", label: "拓扑", Icon: Workflow },
            { id: "logs", label: "执行日志", Icon: ClipboardList },
            { id: "preview", label: "scrcpy 预览", Icon: MonitorPlay },
          ] as const).map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              aria-pressed={activePanel === id}
              onClick={() => setActivePanel(id)}
              className={cn(
                "flex h-full min-w-0 flex-1 items-center justify-center gap-1.5 rounded-md px-2 text-[10px] font-medium transition-colors sm:text-[11px]",
                activePanel === id ? "bg-emerald-400/10 text-emerald-200" : "text-slate-500 hover:text-slate-300",
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{label}</span>
            </button>
          ))}
        </nav>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1.5fr)_minmax(260px,0.85fr)_minmax(260px,0.85fr)]">
          <div className={cn("min-h-0 min-w-0", activePanel === "graph" ? "flex" : "hidden", "xl:flex")}>
            <ExecutionGraph
              nodes={nodes}
              edges={edges}
              activeStep={activeStep}
              running={busy}
              onSelectNode={onSelectNode}
              onRefresh={() => window.location.reload()}
            />
          </div>
          <div className={cn("min-h-0 min-w-0", activePanel === "logs" ? "flex" : "hidden", "xl:flex")}>
            <LogSidebar
              run={run}
              connected={connected}
              events={events}
              selectedEvent={selectedEvent}
              selectedScript={selectedScript}
              onDebugCommand={handleDebugCommand}
            />
          </div>
          <div className={cn("min-h-0 min-w-0", activePanel === "preview" ? "flex" : "hidden", "xl:flex")}>
            <ScreenPreview />
          </div>
        </div>

        <footer className="flex h-5 shrink-0 items-center justify-between gap-2 border-t border-border/50 pt-1 text-[9px] text-slate-600">
          <span className="hidden min-w-0 items-center gap-1.5 truncate sm:flex"><Code2 className="h-3 w-3 shrink-0" />Nier 结构化事件按日志策略脱敏；脚本输出按原样展示</span>
          <span className="ml-auto truncate font-mono">NIER WEB / {run.id ? run.id.slice(0, 8) : "READY"} · {localTime(run.started_at)}</span>
        </footer>
      </main>

      <RunConfirmDialog
        open={showConfirm}
        confirmed={confirmed}
        debug={pendingDebug}
        script={selectedScriptInfo}
        onOpenChange={setShowConfirm}
        onConfirmedChange={setConfirmed}
        onConfirm={handleRun}
      />
    </div>
  );
}
