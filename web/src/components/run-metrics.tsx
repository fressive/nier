import { Check, FileCode2, Layers3, XCircle } from "lucide-react";
import { Card, CardContent } from "./ui/card";

type Props = {
  script: string;
  pathCount: number;
  successCount: number;
  failureCount: number;
};

export function RunMetrics({ script, pathCount, successCount, failureCount }: Props) {
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Card className="border-border/70 bg-[#10151c]/80">
        <CardContent className="flex items-center justify-between p-4">
          <div><p className="text-[11px] text-slate-500">当前脚本</p><p className="mt-1 truncate text-sm font-medium text-slate-200">{script || "尚未选择"}</p></div>
          <FileCode2 className="h-4 w-4 shrink-0 text-slate-500" />
        </CardContent>
      </Card>
      <Card className="border-border/70 bg-[#10151c]/80">
        <CardContent className="flex items-center justify-between p-4">
          <div><p className="text-[11px] text-slate-500">路径节点</p><p className="mt-1 text-lg font-semibold tabular-nums text-slate-100">{String(pathCount).padStart(2, "0")}</p></div>
          <Layers3 className="h-4 w-4 text-cyan-300/70" />
        </CardContent>
      </Card>
      <Card className="border-border/70 bg-[#10151c]/80">
        <CardContent className="flex items-center justify-between p-4">
          <div><p className="text-[11px] text-slate-500">成功步骤</p><p className="mt-1 text-lg font-semibold tabular-nums text-emerald-300">{String(successCount).padStart(2, "0")}</p></div>
          <Check className="h-4 w-4 text-emerald-400/70" />
        </CardContent>
      </Card>
      <Card className="border-border/70 bg-[#10151c]/80">
        <CardContent className="flex items-center justify-between p-4">
          <div><p className="text-[11px] text-slate-500">失败步骤</p><p className="mt-1 text-lg font-semibold tabular-nums text-rose-300">{String(failureCount).padStart(2, "0")}</p></div>
          <XCircle className="h-4 w-4 text-rose-400/70" />
        </CardContent>
      </Card>
    </div>
  );
}
