import { useCallback, useEffect, useMemo, useState } from "react";
import { type Edge, type Node } from "@xyflow/react";
import { Code2, Workflow, XCircle } from "lucide-react";
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
    <div className="min-h-screen text-foreground">
      <header className="sticky top-0 z-20 border-b border-border/80 bg-[#0b0e13]/90 backdrop-blur-xl">
        <div className="mx-auto flex h-[68px] max-w-[1800px] items-center justify-between px-5 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/10 text-emerald-300"><Workflow className="h-5 w-5" /></div>
            <div>
              <div className="flex items-center gap-2"><span className="text-sm font-semibold tracking-wide text-slate-100">NIER</span><span className="text-xs text-slate-600">/</span><span className="text-xs font-medium text-slate-400">Execution Studio</span></div>
              <p className="mt-0.5 hidden text-[10px] tracking-wide text-slate-600 sm:block">ANDROID AUTOMATION · LIVE TRACE</p>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:gap-4">
            <div className="flex items-center gap-2 text-[11px] text-slate-500"><span className={cn("h-1.5 w-1.5 rounded-full", connected ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-rose-400")} /><span>{connected ? "本地连接正常" : "正在连接"}</span></div>
            <div className="hidden h-5 w-px bg-border sm:block" />
            <RunStatusBadge status={run.status} />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1800px] px-4 py-5 sm:px-5 lg:px-8 lg:py-7">
        <div className="mb-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-emerald-300/80"><span className="h-px w-5 bg-emerald-400/60" />Run observability</div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-100 sm:text-[28px]">执行路径</h1>
            <p className="mt-1.5 max-w-2xl text-sm text-slate-500">从脚本启动到每次设备操作，实时追踪执行步骤与模型通信。</p>
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
          <div className="mb-4 flex items-center justify-between rounded-lg border border-rose-400/20 bg-rose-400/5 px-4 py-3 text-sm text-rose-200">
            <span>{error}</span>
            <button className="text-rose-300/70 hover:text-rose-200" onClick={() => setError("")}><XCircle className="h-4 w-4" /></button>
          </div>
        )}

        <RunMetrics script={run.script || selectedScript} pathCount={pathEvents.length} successCount={successCount} failureCount={failureCount} />

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px] 2xl:grid-cols-[minmax(0,1fr)_400px_380px]">
          <ExecutionGraph
            nodes={nodes}
            edges={edges}
            activeStep={activeStep}
            running={busy}
            onSelectNode={onSelectNode}
            onRefresh={() => window.location.reload()}
          />
          <LogSidebar
            run={run}
            connected={connected}
            events={events}
            selectedEvent={selectedEvent}
            selectedScript={selectedScript}
            onDebugCommand={handleDebugCommand}
          />
          <ScreenPreview />
        </div>

        <footer className="mt-5 flex flex-col items-start justify-between gap-2 border-t border-border/50 py-4 text-[10px] text-slate-600 sm:flex-row sm:items-center">
          <span className="flex items-center gap-2"><Code2 className="h-3.5 w-3.5" />Nier 结构化事件按日志策略脱敏；脚本输出按原样展示</span>
          <span className="font-mono">NIER WEB / {run.id ? run.id.slice(0, 8) : "READY"} · {localTime(run.started_at)}</span>
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
