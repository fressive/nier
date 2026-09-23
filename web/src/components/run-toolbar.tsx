import { Bug, ChevronDown, FileCode2, Play, Square } from "lucide-react";
import { Button } from "./ui/button";
import type { ScriptInfo } from "../types";

type Props = {
  scripts: ScriptInfo[];
  selectedScript: string;
  busy: boolean;
  onSelect: (script: string) => void;
  onStart: (debug: boolean) => void;
  onStop: () => void;
};

export function RunToolbar({ scripts, selectedScript, busy, onSelect, onStart, onStop }: Props) {
  return (
    <div className="flex w-full min-w-0 flex-nowrap items-center gap-1.5 sm:w-auto sm:gap-2">
      <div className="relative min-w-0 flex-1 sm:flex-none">
        <FileCode2 className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500 sm:left-3 sm:h-4 sm:w-4" />
        <select
          value={selectedScript}
          onChange={(event) => onSelect(event.target.value)}
          disabled={busy || scripts.length === 0}
          aria-label="选择 Python 脚本"
          className="h-9 w-full appearance-none rounded-md border border-input bg-[#111720] pl-8 pr-8 text-xs text-slate-200 outline-none transition-colors focus:border-emerald-400/60 disabled:opacity-50 sm:w-[min(38vw,300px)] sm:pl-9 sm:pr-9 sm:text-sm"
        >
          {scripts.length === 0 && <option value="">未找到 Python 脚本</option>}
          {scripts.map((script) => <option key={script.path} value={script.path}>{script.path}</option>)}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500 sm:right-3 sm:h-4 sm:w-4" />
      </div>
      {busy ? (
        <Button variant="destructive" onClick={onStop} aria-label="停止运行" title="停止运行" className="h-9 shrink-0 gap-1.5 px-2 text-xs sm:px-3 sm:text-sm">
          <Square className="h-3.5 w-3.5 fill-current" /><span className="hidden sm:inline">停止运行</span>
        </Button>
      ) : (
        <>
          <Button onClick={() => onStart(false)} disabled={!selectedScript} aria-label="运行脚本" title="运行脚本" className="h-9 shrink-0 gap-1.5 px-2 text-xs bg-emerald-400 text-slate-950 hover:bg-emerald-300 sm:px-3 sm:text-sm">
            <Play className="h-3.5 w-3.5 fill-current" /><span className="hidden sm:inline">运行脚本</span>
          </Button>
          <Button variant="outline" onClick={() => onStart(true)} disabled={!selectedScript} aria-label="调试运行" title="调试运行" className="h-9 shrink-0 gap-1.5 px-2 text-xs sm:px-3 sm:text-sm">
            <Bug className="h-3.5 w-3.5" /><span className="hidden sm:inline">调试运行</span>
          </Button>
        </>
      )}
    </div>
  );
}
