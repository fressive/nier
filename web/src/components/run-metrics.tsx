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
    <div className="grid shrink-0 grid-cols-4 gap-1.5">
      <Card className="relative min-w-0 border-border/70 bg-[#10151c]/80">
        <CardContent className="min-w-0 p-2 sm:p-2.5">
          <div className="min-w-0"><p className="truncate text-[9px] text-slate-500 sm:text-[10px]">当前脚本</p><p className="mt-0.5 truncate text-[10px] font-medium text-slate-200 sm:pr-5 sm:text-xs">{script || "尚未选择"}</p></div>
          <FileCode2 className="absolute right-2 top-2 hidden h-3.5 w-3.5 text-slate-500 sm:block" />
        </CardContent>
      </Card>
      <Card className="relative min-w-0 border-border/70 bg-[#10151c]/80">
        <CardContent className="p-2 sm:p-2.5">
          <div><p className="truncate text-[9px] text-slate-500 sm:text-[10px]">路径节点</p><p className="mt-0.5 text-sm font-semibold tabular-nums text-slate-100 sm:text-base">{String(pathCount).padStart(2, "0")}</p></div>
          <Layers3 className="absolute right-2 top-2 hidden h-3.5 w-3.5 text-cyan-300/70 sm:block" />
        </CardContent>
      </Card>
      <Card className="relative min-w-0 border-border/70 bg-[#10151c]/80">
        <CardContent className="p-2 sm:p-2.5">
          <div><p className="truncate text-[9px] text-slate-500 sm:text-[10px]">成功步骤</p><p className="mt-0.5 text-sm font-semibold tabular-nums text-emerald-300 sm:text-base">{String(successCount).padStart(2, "0")}</p></div>
          <Check className="absolute right-2 top-2 hidden h-3.5 w-3.5 text-emerald-400/70 sm:block" />
        </CardContent>
      </Card>
      <Card className="relative min-w-0 border-border/70 bg-[#10151c]/80">
        <CardContent className="p-2 sm:p-2.5">
          <div><p className="truncate text-[9px] text-slate-500 sm:text-[10px]">失败步骤</p><p className="mt-0.5 text-sm font-semibold tabular-nums text-rose-300 sm:text-base">{String(failureCount).padStart(2, "0")}</p></div>
          <XCircle className="absolute right-2 top-2 hidden h-3.5 w-3.5 text-rose-400/70 sm:block" />
        </CardContent>
      </Card>
    </div>
  );
}
