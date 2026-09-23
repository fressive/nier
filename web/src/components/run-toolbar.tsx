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
    <div className="flex flex-wrap items-center gap-2.5">
      <div className="relative min-w-[260px] flex-1 xl:flex-none">
        <FileCode2 className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <select
          value={selectedScript}
          onChange={(event) => onSelect(event.target.value)}
          disabled={busy || scripts.length === 0}
          aria-label="选择 Python 脚本"
          className="h-10 w-full appearance-none rounded-md border border-input bg-[#111720] pl-9 pr-9 text-sm text-slate-200 outline-none transition-colors focus:border-emerald-400/60 disabled:opacity-50 xl:w-[330px]"
        >
          {scripts.length === 0 && <option value="">未找到 Python 脚本</option>}
          {scripts.map((script) => <option key={script.path} value={script.path}>{script.path}</option>)}
        </select>
        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
      </div>
      {busy ? (
        <Button variant="destructive" onClick={onStop} className="gap-2">
          <Square className="h-3.5 w-3.5 fill-current" />停止运行
        </Button>
      ) : (
        <>
          <Button onClick={() => onStart(false)} disabled={!selectedScript} className="gap-2 bg-emerald-400 text-slate-950 hover:bg-emerald-300">
            <Play className="h-3.5 w-3.5 fill-current" />运行脚本
          </Button>
          <Button variant="outline" onClick={() => onStart(true)} disabled={!selectedScript} className="gap-2">
            <Bug className="h-3.5 w-3.5" />调试运行
          </Button>
        </>
      )}
    </div>
  );
}
