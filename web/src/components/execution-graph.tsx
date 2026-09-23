import { useEffect } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { Radio, RefreshCw, Workflow } from "lucide-react";
import { nodeTypes } from "./step-node";
import { Button } from "./ui/button";
import { Card, CardHeader, CardTitle } from "./ui/card";
import type { StepNodeData, WebEvent } from "../types";

function FollowLatest({
  eventId,
  y,
  running,
}: {
  eventId?: string;
  y: number;
  running: boolean;
}) {
  const { getNode, setCenter } = useReactFlow();
  useEffect(() => {
    if (running && eventId !== undefined) {
      const node = getNode(eventId);
      const x = node?.position.x ?? 60;
      const nodeY = node?.position.y ?? y;
      const width = node?.measured?.width ?? 320;
      const height = node?.measured?.height ?? 100;
      setCenter(x + width / 2, nodeY + height / 2, { zoom: 0.82, duration: 320 });
    }
  }, [eventId, getNode, running, setCenter, y]);
  return null;
}

type Props = {
  nodes: Node<StepNodeData>[];
  edges: Edge[];
  activeStep?: WebEvent;
  running: boolean;
  onSelectNode: (id: number) => void;
  onRefresh: () => void;
};

export function ExecutionGraph({
  nodes,
  edges,
  activeStep,
  running,
  onSelectNode,
  onRefresh,
}: Props) {
  const latestNode = nodes.at(-1);
  return (
    <Card className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden border-border/80 bg-[#10151c]/85">
      <CardHeader className="shrink-0 flex-row items-center justify-between space-y-0 border-b border-border/70 px-3 py-2.5 sm:px-4 sm:py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-800/70 text-slate-300"><Workflow className="h-3.5 w-3.5" /></div>
          <div className="min-w-0">
            <CardTitle className="text-sm">运行拓扑</CardTitle>
            <p className="mt-0.5 hidden truncate text-[10px] text-slate-500 sm:block">按实际事件顺序连接的执行轨迹</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <span className="hidden items-center gap-1.5 xl:flex"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />已完成</span>
          <span className="hidden items-center gap-1.5 xl:flex"><span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />当前节点</span>
          <Button variant="ghost" size="icon" title="刷新页面数据" onClick={onRefresh} className="h-7 w-7 text-slate-500"><RefreshCw className="h-3.5 w-3.5" /></Button>
        </div>
      </CardHeader>
      <div className="relative min-h-0 flex-1">
        {nodes.length ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodeClick={(_, node) => onSelectNode(Number(node.id))}
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
            <FollowLatest
              eventId={latestNode?.id}
              y={latestNode?.position.y ?? 36}
              running={running}
            />
            <Background color="#26313d" gap={22} size={1} />
            <Controls showInteractive={false} />
            <MiniMap nodeColor={(node) => node.id === String(activeStep?.event_id) && running ? "#43d4a6" : "#65798a"} pannable zoomable />
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
  );
}
