import { type MouseEvent, useCallback, useEffect, useState } from "react";
import { AlertCircle, LoaderCircle, MonitorPlay, Play, RefreshCw, Square } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { fetchJson, postJson } from "../lib/api";
import { mapPreviewPoint } from "../lib/screen-coordinates.mjs";
import { cn } from "../lib/utils";

type PreviewDevice = {
  serial: string;
  state: string;
  model: string;
  product: string;
};

type PreviewState = {
  status: "idle" | "starting" | "streaming" | "error";
  serial: string | null;
  connected: boolean;
  frame_ready: boolean;
  screen_width: number | null;
  screen_height: number | null;
  error: string | null;
  device_error: string | null;
  dependencies: { adb: boolean; scrcpy: boolean; scrcpy_server: boolean; ffmpeg: boolean };
  devices: PreviewDevice[];
};

const dependencyLabels: Record<keyof PreviewState["dependencies"], string> = {
  adb: "ADB",
  scrcpy: "scrcpy",
  scrcpy_server: "scrcpy server",
  ffmpeg: "FFmpeg",
};

export function ScreenPreview() {
  const [state, setState] = useState<PreviewState | null>(null);
  const [serial, setSerial] = useState("");
  const [error, setError] = useState("");
  const [streamKey, setStreamKey] = useState(0);
  const [frameLoaded, setFrameLoaded] = useState(false);
  const [coordinateMessage, setCoordinateMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const next = await fetchJson<PreviewState>("/api/preview/state");
      setState(next);
      setSerial((current) => {
        if (next.serial && next.devices.some((device) => device.serial === next.serial)) return next.serial;
        if (current && next.devices.some((device) => device.serial === current)) return current;
        return next.devices.find((device) => device.state === "device")?.serial ?? "";
      });
      setError("");
    } catch (reason) {
      setError((reason as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const start = async () => {
    setError("");
    setCoordinateMessage("");
    setFrameLoaded(false);
    try {
      const next = await postJson<PreviewState>("/api/preview/start", { serial });
      setState(next);
      setSerial(next.serial ?? serial);
      setStreamKey((value) => value + 1);
    } catch (reason) {
      setError((reason as Error).message);
      void refresh();
    }
  };

  const stop = async () => {
    setError("");
    setCoordinateMessage("");
    try {
      const next = await postJson<PreviewState>("/api/preview/stop", {});
      setState(next);
      setFrameLoaded(false);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const copyClickCoordinates = async (event: MouseEvent<HTMLImageElement>) => {
    const image = event.currentTarget;
    const { naturalWidth, naturalHeight } = image;
    if (!naturalWidth || !naturalHeight) return;
    if (!state?.screen_width || !state.screen_height) {
      setCoordinateMessage("无法读取设备分辨率，不能生成坐标");
      return;
    }
    const point = mapPreviewPoint({
      clientX: event.clientX,
      clientY: event.clientY,
      bounds: image.getBoundingClientRect(),
      frameWidth: naturalWidth,
      frameHeight: naturalHeight,
      screenWidth: state.screen_width,
      screenHeight: state.screen_height,
    });
    if (!point) {
      setCoordinateMessage("请点击设备画面范围内");
      return;
    }

    const snippet = `phone.click(${point.x}, ${point.y})`;
    try {
      await navigator.clipboard.writeText(snippet);
      setCoordinateMessage(`已复制 ${snippet}`);
    } catch {
      setCoordinateMessage(`复制失败：${snippet}`);
    }
  };

  const status = state?.status ?? "idle";
  const running = status === "starting" || status === "streaming";
  const devices = state?.devices ?? [];
  const missingDependencies = state
    ? (Object.entries(state.dependencies) as [keyof PreviewState["dependencies"], boolean][])
      .filter(([, installed]) => !installed)
      .map(([name]) => dependencyLabels[name])
    : [];
  const currentDevice = devices.find((device) => device.serial === serial);
  const previewUrl = `/api/preview/stream?session=${streamKey}`;

  return (
    <Card className="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden border-border/80 bg-[#10151c]/85">
      <div className="flex min-h-0 flex-1 flex-col p-3 sm:p-4">
      <div className="mb-2 flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <MonitorPlay className="h-4 w-4 text-emerald-300" />
          <span className="text-xs font-semibold text-slate-200">scrcpy 预览</span>
          <Badge
            variant={status === "streaming" ? "success" : status === "error" ? "danger" : "outline"}
            className="px-1.5 py-0 text-[9px]"
          >
            {status === "streaming" ? "实时" : status === "starting" ? "连接中" : status === "error" ? "异常" : "已停止"}
          </Badge>
        </div>
        <Button variant="ghost" size="icon" title="刷新设备列表" onClick={() => void refresh()} className="h-7 w-7 text-slate-500">
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="mb-2 flex shrink-0 gap-2">
        <select
          value={serial}
          onChange={(event) => setSerial(event.target.value)}
          disabled={running}
          aria-label="选择 ADB 设备"
          className="h-9 min-w-0 flex-1 rounded-md border border-border bg-[#0b0f14] px-2 text-[10px] text-slate-200 outline-none focus:border-emerald-400/50 disabled:opacity-60 sm:text-[11px]"
        >
          {devices.length === 0 && <option value="">未发现 ADB 设备</option>}
          {devices.map((device) => {
            const label = device.model || device.product || device.serial;
            return (
              <option key={device.serial} value={device.serial} disabled={device.state !== "device"}>
                {label} · {device.state} · {device.serial}
              </option>
            );
          })}
        </select>
        {running ? (
          <Button variant="destructive" size="sm" onClick={() => void stop()} className="h-9 shrink-0 px-3 text-[11px]">
            <Square className="h-3 w-3" />停止
          </Button>
        ) : (
          <Button size="sm" onClick={() => void start()} disabled={!serial || missingDependencies.length > 0} className="h-9 shrink-0 px-3 text-[11px]">
            <Play className="h-3 w-3" />开始预览
          </Button>
        )}
      </div>

      {missingDependencies.length > 0 && (
        <div className="mb-2 max-h-14 shrink-0 overflow-hidden flex items-start gap-2 rounded-md border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-[10px] leading-relaxed text-amber-200/80">
          <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>缺少 {missingDependencies.join("、")}。请安装并加入 PATH 后重启 nier web。</span>
        </div>
      )}
      {state?.device_error && devices.length === 0 && (
        <p className="mb-2 max-h-10 shrink-0 overflow-hidden text-[10px] text-amber-200/80">{state.device_error}</p>
      )}
      {(error || state?.error) && (
        <p className="mb-2 max-h-14 shrink-0 overflow-hidden flex items-start gap-1.5 rounded-md border border-rose-400/20 bg-rose-400/5 px-3 py-2 text-[10px] leading-relaxed text-rose-200">
          <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />{error || state?.error}
        </p>
      )}

      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-lg border border-border/70 bg-black">
        {running ? (
          <>
            <img
              key={streamKey}
              src={previewUrl}
              alt={`设备 ${currentDevice?.model || serial} 的当前界面`}
              onLoad={() => setFrameLoaded(true)}
              onError={() => setError("预览视频流已断开，请停止后重新启动")}
              onClick={(event) => void copyClickCoordinates(event)}
              title="点击画面复制 phone.click(x, y) 坐标"
              className={cn("h-full w-full cursor-crosshair object-contain", !frameLoaded && "opacity-0")}
            />
            {!frameLoaded && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-500">
                <LoaderCircle className="h-5 w-5 animate-spin text-emerald-300/80" />
                <span className="text-[10px]">正在连接设备画面…</span>
              </div>
            )}
            {frameLoaded && (
              <div
                className={cn(
                  "pointer-events-none absolute bottom-3 left-1/2 max-w-[calc(100%-1.5rem)] -translate-x-1/2 truncate rounded-md border bg-[#10151c]/90 px-2.5 py-1.5 font-mono text-[10px] shadow-lg",
                  coordinateMessage.startsWith("已复制")
                    ? "border-emerald-400/20 text-emerald-200"
                    : coordinateMessage.startsWith("复制失败") || coordinateMessage.startsWith("请点击")
                      ? "border-rose-400/20 text-rose-200"
                      : "border-border/70 text-slate-300",
                )}
              >
                {coordinateMessage || "点击画面复制 phone.click(x, y) 坐标"}
              </div>
            )}
          </>
        ) : (
          <div className="flex flex-col items-center gap-2 px-5 text-center text-slate-600">
            <MonitorPlay className="h-8 w-8" />
            <span className="text-[11px] text-slate-400">选择在线设备后开始预览</span>
            <span className="text-[9px]">scrcpy 控制功能已关闭，此处为只读画面</span>
          </div>
        )}
      </div>

      <p className="mt-2 shrink-0 truncate text-center text-[9px] text-slate-600">
        {running ? `当前设备：${currentDevice?.model || serial}` : "视频经本机 ADB 转发，不启动手机网络服务"}
      </p>
      </div>
    </Card>
  );
}
