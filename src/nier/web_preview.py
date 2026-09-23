"""Local scrcpy-to-MJPEG bridge used by the web dashboard."""

from __future__ import annotations

from collections import deque
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, BinaryIO


class PreviewUnavailable(RuntimeError):
    """A required host program or platform feature is unavailable."""


class PreviewRequestError(ValueError):
    """A requested ADB device is not available for mirroring."""


class ScrcpyPreview:
    """Capture one authorized ADB device through scrcpy and serve JPEG frames."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._status = "idle"
        self._serial: str | None = None
        self._error: str | None = None
        self._active = False
        self._connected = False
        self._scrcpy: subprocess.Popen[bytes] | None = None
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._pending_scrcpy: subprocess.Popen[bytes] | None = None
        self._pending_ffmpeg: subprocess.Popen[bytes] | None = None
        self._fifo_directory: str | None = None
        self._latest_frame: bytes | None = None
        self._subscribers: set[queue.Queue[bytes | None]] = set()
        self._stderr: dict[str, deque[str]] = {
            "scrcpy": deque(maxlen=12),
            "ffmpeg": deque(maxlen=12),
        }

    def status(self) -> dict[str, Any]:
        adb_path = shutil.which("adb")
        devices, device_error = self._list_devices(adb_path)
        with self._lock:
            return {
                "status": self._status,
                "serial": self._serial,
                "connected": self._connected,
                "frame_ready": self._latest_frame is not None,
                "error": self._error,
                "device_error": device_error,
                "dependencies": {
                    "adb": adb_path is not None,
                    "scrcpy": shutil.which("scrcpy") is not None,
                    "ffmpeg": shutil.which("ffmpeg") is not None,
                    "fifo": hasattr(os, "mkfifo"),
                },
                "devices": devices,
            }

    def start(self, serial: str) -> dict[str, Any]:
        if not isinstance(serial, str) or not serial or len(serial) > 512 or any(char.isspace() for char in serial):
            raise PreviewRequestError("请选择有效的 ADB 设备")

        adb_path = shutil.which("adb")
        scrcpy_path = shutil.which("scrcpy")
        ffmpeg_path = shutil.which("ffmpeg")
        missing = [name for name, path in (("adb", adb_path), ("scrcpy", scrcpy_path), ("ffmpeg", ffmpeg_path)) if path is None]
        if missing:
            raise PreviewUnavailable(f"缺少预览依赖：{', '.join(missing)}。请安装后重新启动 nier web。")
        if not hasattr(os, "mkfifo"):
            raise PreviewUnavailable("当前平台缺少 FIFO 管道支持，暂时无法运行嵌入式 scrcpy 预览")

        devices, device_error = self._list_devices(adb_path)
        device = next((item for item in devices if item["serial"] == serial), None)
        if device is None or device["state"] != "device":
            detail = f"：{device_error}" if device_error else ""
            raise PreviewRequestError(f"ADB 设备不可用或未授权：{serial}{detail}")

        with self._lock:
            if not (self._active and self._serial == serial):
                self._shutdown_locked(status="idle", error=None, bump_generation=True)
                generation = self._generation
                self._status = "starting"
                self._serial = serial
                self._error = None
                self._connected = False
                self._latest_frame = None
                self._stderr = {"scrcpy": deque(maxlen=12), "ffmpeg": deque(maxlen=12)}

                try:
                    self._start_processes(
                        serial,
                        scrcpy_path=scrcpy_path,
                        ffmpeg_path=ffmpeg_path,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    message = f"无法启动 scrcpy 预览：{exc}"
                    self._shutdown_locked(status="error", error=message, bump_generation=False)
                    raise PreviewUnavailable(message) from exc

                self._active = True
                self._scrcpy = self._pending_scrcpy
                self._ffmpeg = self._pending_ffmpeg
                self._pending_scrcpy = None
                self._pending_ffmpeg = None
                self._start_readers_locked(generation)
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._shutdown_locked(status="idle", error=None, bump_generation=True)
        return self.status()

    def subscribe(self) -> queue.Queue[bytes | None]:
        subscriber: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
        with self._lock:
            if not self._active:
                raise PreviewRequestError("scrcpy 预览尚未启动")
            self._subscribers.add(subscriber)
            if self._latest_frame is not None:
                subscriber.put_nowait(self._latest_frame)
        return subscriber

    def stream(self, subscriber: queue.Queue[bytes | None]):
        try:
            while True:
                try:
                    frame = subscriber.get(timeout=10)
                except queue.Empty:
                    with self._lock:
                        if not self._active:
                            return
                    continue
                if frame is None:
                    return
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(frame)).encode("ascii")
                    + b"\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)

    def _list_devices(self, adb_path: str | None) -> tuple[list[dict[str, str]], str | None]:
        if adb_path is None:
            return [], "找不到 adb，请安装 Android platform-tools 并加入 PATH"
        try:
            result = subprocess.run(
                [adb_path, "devices", "-l"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return [], f"无法读取 ADB 设备列表：{exc}"
        if result.returncode != 0:
            detail = result.stderr.strip()[-400:]
            return [], detail or "adb devices 执行失败"

        devices: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) < 2 or columns[0] == "List":
                continue
            metadata = dict(
                part.split(":", 1)
                for part in columns[2:]
                if ":" in part
            )
            devices.append(
                {
                    "serial": columns[0],
                    "state": columns[1],
                    "model": metadata.get("model", ""),
                    "product": metadata.get("product", ""),
                }
            )
        return devices, None

    def _start_processes(
        self,
        serial: str,
        *,
        scrcpy_path: str,
        ffmpeg_path: str,
    ) -> None:
        self._fifo_directory = tempfile.mkdtemp(prefix="nier-scrcpy-")
        os.chmod(self._fifo_directory, 0o700)
        fifo_path = str(Path(self._fifo_directory) / "video.mkv")
        os.mkfifo(fifo_path, 0o600)
        fifo_fd = os.open(fifo_path, os.O_RDWR)
        try:
            self._pending_ffmpeg = subprocess.Popen(
                [
                    ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-fflags",
                    "nobuffer",
                    "-f",
                    "matroska",
                    "-i",
                    "pipe:0",
                    "-an",
                    "-vf",
                    "fps=12",
                    "-q:v",
                    "8",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ],
                stdin=fifo_fd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        finally:
            os.close(fifo_fd)

        self._pending_scrcpy = subprocess.Popen(
            [
                scrcpy_path,
                "--serial",
                serial,
                "--no-audio",
                "--no-control",
                "--no-playback",
                "--max-size",
                "1280",
                "--video-bit-rate",
                "4M",
                "--record-format",
                "mkv",
                "--record",
                fifo_path,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def _start_readers_locked(self, generation: int) -> None:
        assert self._scrcpy is not None and self._ffmpeg is not None
        for label, process in (("scrcpy", self._scrcpy), ("ffmpeg", self._ffmpeg)):
            if process.stderr is not None:
                threading.Thread(
                    target=self._read_stderr,
                    args=(generation, label, process.stderr),
                    name=f"nier-preview-{label}",
                    daemon=True,
                ).start()
        if self._ffmpeg.stdout is not None:
            threading.Thread(
                target=self._read_frames,
                args=(generation, self._ffmpeg.stdout),
                name="nier-preview-frames",
                daemon=True,
            ).start()
        threading.Thread(
            target=self._watch_processes,
            args=(generation,),
            name="nier-preview-watch",
            daemon=True,
        ).start()

    def _read_stderr(self, generation: int, label: str, stream: BinaryIO) -> None:
        try:
            for line in stream:
                value = line.decode("utf-8", errors="replace").strip()
                if not value:
                    continue
                with self._lock:
                    if generation == self._generation:
                        self._stderr[label].append(value[:500])
        except OSError:
            return

    def _read_frames(self, generation: int, stream: BinaryIO) -> None:
        buffer = bytearray()
        try:
            while True:
                chunk = os.read(stream.fileno(), 64 * 1024)
                if not chunk:
                    return
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    if start < 0:
                        if len(buffer) > 1:
                            del buffer[:-1]
                        break
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if end < 0:
                        if start:
                            del buffer[:start]
                        break
                    frame = bytes(buffer[start : end + 2])
                    del buffer[: end + 2]
                    self._publish_frame(generation, frame)
        except OSError:
            return

    def _publish_frame(self, generation: int, frame: bytes) -> None:
        with self._lock:
            if generation != self._generation or not self._active:
                return
            self._status = "streaming"
            self._connected = True
            self._latest_frame = frame
            for subscriber in tuple(self._subscribers):
                if subscriber.full():
                    try:
                        subscriber.get_nowait()
                    except queue.Empty:
                        pass
                try:
                    subscriber.put_nowait(frame)
                except queue.Full:
                    pass

    def _watch_processes(self, generation: int) -> None:
        while True:
            with self._lock:
                if generation != self._generation or not self._active:
                    return
                scrcpy_process = self._scrcpy
                ffmpeg_process = self._ffmpeg
            if scrcpy_process is not None and scrcpy_process.poll() is not None:
                self._fail(generation, "scrcpy 已退出")
                return
            if ffmpeg_process is not None and ffmpeg_process.poll() is not None:
                self._fail(generation, "ffmpeg 视频转换已退出")
                return
            time.sleep(0.5)

    def _fail(self, generation: int, message: str) -> None:
        with self._lock:
            if generation != self._generation or not self._active:
                return
            detail = self._error_detail_locked()
            if detail:
                message = f"{message}：{detail}"
            self._shutdown_locked(status="error", error=message, bump_generation=True)

    def _error_detail_locked(self) -> str:
        lines = [line for label in ("scrcpy", "ffmpeg") for line in self._stderr[label]]
        return " | ".join(lines[-3:])[-900:]

    def _shutdown_locked(self, *, status: str, error: str | None, bump_generation: bool) -> None:
        if bump_generation:
            self._generation += 1
        self._active = False
        self._status = status
        self._error = error
        self._connected = False
        self._latest_frame = None

        for subscriber in tuple(self._subscribers):
            if subscriber.full():
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
            try:
                subscriber.put_nowait(None)
            except queue.Full:
                pass
        self._subscribers.clear()

        for process in (self._scrcpy, self._ffmpeg, getattr(self, "_pending_ffmpeg", None), getattr(self, "_pending_scrcpy", None)):
            self._terminate(process)
        self._scrcpy = None
        self._ffmpeg = None
        self._pending_scrcpy = None
        self._pending_ffmpeg = None

        if self._fifo_directory is not None:
            shutil.rmtree(self._fifo_directory, ignore_errors=True)
            self._fifo_directory = None
        if status == "idle":
            self._serial = None

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes] | None) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            return
        try:
            process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError):
                pass
        except OSError:
            return


__all__ = ["PreviewRequestError", "PreviewUnavailable", "ScrcpyPreview"]
