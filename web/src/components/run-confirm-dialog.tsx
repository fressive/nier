import { Bug, FileCode2, Play } from "lucide-react";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import type { ScriptInfo } from "../types";

type Props = {
  open: boolean;
  confirmed: boolean;
  debug: boolean;
  script?: ScriptInfo;
  onOpenChange: (open: boolean) => void;
  onConfirmedChange: (confirmed: boolean) => void;
  onConfirm: () => void;
};

export function RunConfirmDialog({ open, confirmed, debug, script, onOpenChange, onConfirmedChange, onConfirm }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{debug ? "调试所选脚本？" : "运行所选脚本？"}</DialogTitle>
          <DialogDescription>
            脚本会以当前用户权限在本机执行，也可能连接已配置的 Android 设备或调用模型服务。只运行你信任并获准使用的脚本。
          </DialogDescription>
        </DialogHeader>
        <div className="my-4 rounded-lg border border-border bg-[#0e131a] p-3">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-200">
            {debug ? <Bug className="h-4 w-4 text-emerald-300" /> : <FileCode2 className="h-4 w-4 text-emerald-300" />}
            {script?.path}
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{script?.description}</p>
        </div>
        {debug && <p className="-mt-2 mb-3 text-[11px] leading-relaxed text-slate-500">调试模式会在第一个 Nier STEP 事件处暂停。单步执行一个 STEP；步入和步出按脚本调用路径筛选后续 STEP 事件。</p>}
        <label className="flex cursor-pointer items-start gap-3 rounded-md px-1 py-1 text-xs leading-relaxed text-slate-400">
          <input type="checkbox" checked={confirmed} onChange={(event) => onConfirmedChange(event.target.checked)} className="mt-0.5 h-4 w-4 accent-emerald-400" />
          <span>我已确认该脚本可信，并授权本次运行可能产生的设备或模型操作。</span>
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button disabled={!confirmed} onClick={onConfirm} className="gap-2 bg-emerald-400 text-slate-950 hover:bg-emerald-300">
            {debug ? <Bug className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5 fill-current" />}
            {debug ? "开始调试" : "确认运行"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
