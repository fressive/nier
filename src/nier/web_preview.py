"""Local scrcpy-to-MJPEG bridge used by the web dashboard."""

from __future__ import annotations

from collections import deque
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, BinaryIO


class PreviewUnavailable(RuntimeError):
    """A required host program or platform feature is unavailable."""


class PreviewRequestError(ValueError):
    """A requested ADB device is not available for mirroring."""


class ScrcpyPreview:
    """Capture an authorized ADB device through scrcpy and serve JPEG frames."""

    _DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._status = "idle"
        self._serial: str | None = None
        self._error: str | None = None
        self._active = False
        self._connected = False
        self._screen_size: tuple[int, int] | None = None
        self._server: subprocess.Popen[bytes] | None = None
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._pending_server: subprocess.Popen[bytes] | None = None
        self._pending_ffmpeg: subprocess.Popen[bytes] | None = None
        self._video_socket: socket.socket | None = None
        self._adb_path: str | None = None
        self._forward_serial: str | None = None
        self._forward_port: int | None = None
        self._latest_frame: bytes | None = None
        self._subscribers: set[queue.Queue[bytes | None]] = set()
        self._stderr: dict[str, deque[str]] = {
            "scrcpy": deque(maxlen=12),
            "ffmpeg": deque(maxlen=12),
        }

    def status(self) -> dict[str, Any]:
        adb_path = shutil.which("adb")
        scrcpy_path = shutil.which("scrcpy")
        devices, device_error = self._list_devices(adb_path)
        with self._lock:
            return {
                "status": self._status,
                "serial": self._serial,
                "connected": self._connected,
                "frame_ready": self._latest_frame is not None,
                "screen_width": self._screen_size[0] if self._screen_size else None,
                "screen_height": self._screen_size[1] if self._screen_size else None,
                "error": self._error,
                "device_error": device_error,
                "dependencies": {
                    "adb": adb_path is not None,
                    "scrcpy": scrcpy_path is not None,
                    "scrcpy_server": self._find_server_path(scrcpy_path) is not None,
                    "ffmpeg": shutil.which("ffmpeg") is not None,
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
        assert adb_path is not None and scrcpy_path is not None and ffmpeg_path is not None

        server_path = self._find_server_path(scrcpy_path)
        if server_path is None:
            raise PreviewUnavailable(
                "找不到 scrcpy-server 文件。请安装完整的 scrcpy 软件包，或通过 SCRCPY_SERVER_PATH 指定它。"
            )
        version = self._get_scrcpy_version(scrcpy_path)

        devices, device_error = self._list_devices(adb_path)
        device = next((item for item in devices if item["serial"] == serial), None)
        if device is None or device["state"] != "device":
            detail = f"：{device_error}" if device_error else ""
            raise PreviewRequestError(f"ADB 设备不可用或未授权：{serial}{detail}")
        screen_size = self._read_screen_size(adb_path, serial)

        with self._lock:
            if not (self._active and self._serial == serial):
                self._shutdown_locked(status="idle", error=None, bump_generation=True)
                generation = self._generation
                self._status = "starting"
                self._serial = serial
                self._error = None
                self._connected = False
                self._latest_frame = None
                self._screen_size = screen_size
                self._stderr = {"scrcpy": deque(maxlen=12), "ffmpeg": deque(maxlen=12)}

                try:
                    self._start_processes(
                        serial,
                        adb_path=adb_path,
                        ffmpeg_path=ffmpeg_path,
                        server_path=server_path,
                        version=version,
                    )
                except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                    message = f"无法启动 scrcpy 预览：{exc}"
                    self._shutdown_locked(status="error", error=message, bump_generation=False)
                    raise PreviewUnavailable(message) from exc

                self._active = True
                self._server = self._pending_server
                self._ffmpeg = self._pending_ffmpeg
                self._pending_server = None
                self._pending_ffmpeg = None
                self._start_readers_locked(generation)
            else:
                self._screen_size = screen_size
        return self.status()

    @staticmethod
    def _read_screen_size(adb_path: str, serial: str) -> tuple[int, int] | None:
        """Read Android's absolute input-coordinate dimensions."""
        try:
            result = subprocess.run(
                [adb_path, "-s", serial, "shell", "wm", "size"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        matches = re.findall(r"(\d+)x(\d+)", result.stdout)
        if not matches:
            return None
        width, height = (int(value) for value in matches[-1])
        return (width, height) if width > 0 and height > 0 else None

    def stop(self) -> dict[str, Any]:
        self.close()
        return self.status()

    def close(self) -> None:
        """Stop preview processes and remove the temporary ADB forward."""
        with self._lock:
            self._shutdown_locked(status="idle", error=None, bump_generation=True)

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
        adb_path: str,
        ffmpeg_path: str,
        server_path: str,
        version: str,
    ) -> None:
        push = subprocess.run(
            [adb_path, "-s", serial, "push", server_path, self._DEVICE_SERVER_PATH],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if push.returncode != 0:
            detail = (push.stderr or push.stdout).strip()[-600:]
            raise RuntimeError(f"adb push scrcpy-server 失败：{detail or push.returncode}")

        scid = secrets.randbits(31)
        socket_name = f"scrcpy_{scid:08x}"
        forward = subprocess.run(
            [adb_path, "-s", serial, "forward", "tcp:0", f"localabstract:{socket_name}"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        if forward.returncode != 0:
            detail = (forward.stderr or forward.stdout).strip()[-600:]
            raise RuntimeError(f"创建临时 ADB 转发失败：{detail or forward.returncode}")
        try:
            port = int(forward.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise RuntimeError(f"adb forward 没有返回本地端口：{forward.stdout.strip()!r}") from exc
        if not 1 <= port <= 65535:
            raise RuntimeError(f"adb forward 返回了无效端口：{port}")

        self._adb_path = adb_path
        self._forward_serial = serial
        self._forward_port = port

        self._pending_ffmpeg = subprocess.Popen(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-probesize",
                "32",
                "-analyzeduration",
                "0",
                "-f",
                "h264",
                "-i",
                "pipe:0",
                "-an",
                "-q:v",
                "8",
                "-vcodec",
                "mjpeg",
                "-pix_fmt",
                "yuvj420p",
                "-threads:v",
                "1",
                "-flush_packets",
                "1",
                "-f",
                "image2pipe",
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        self._pending_server = subprocess.Popen(
            [
                adb_path,
                "-s",
                serial,
                "shell",
                f"CLASSPATH={self._DEVICE_SERVER_PATH}",
                "app_process",
                "/",
                "com.genymobile.scrcpy.Server",
                version,
                f"scid={scid:08x}",
                "log_level=info",
                "video=true",
                "video_bit_rate=4000000",
                "video_codec=h264",
                "audio=false",
                "control=false",
                "max_size=1280",
                "tunnel_forward=true",
                # Keep the video socket as a raw H.264 byte stream. The single
                # startup marker lets the host distinguish a ready server from
                # an ADB forward that accepted too early.
                "send_device_meta=false",
                "send_frame_meta=false",
                "send_stream_meta=false",
                "send_dummy_byte=true",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )

    def _start_readers_locked(self, generation: int) -> None:
        assert self._server is not None and self._ffmpeg is not None
        if self._server.stdout is not None:
            threading.Thread(
                target=self._read_output,
                args=(generation, "scrcpy", self._server.stdout),
                name="nier-preview-scrcpy",
                daemon=True,
            ).start()
        if self._ffmpeg.stderr is not None:
            threading.Thread(
                target=self._read_output,
                args=(generation, "ffmpeg", self._ffmpeg.stderr),
                name="nier-preview-ffmpeg",
                daemon=True,
            ).start()
        if self._ffmpeg.stdout is not None:
            threading.Thread(
                target=self._read_frames,
                args=(generation, self._ffmpeg.stdout),
                name="nier-preview-frames",
                daemon=True,
            ).start()
        assert self._forward_port is not None and self._ffmpeg.stdin is not None
        threading.Thread(
            target=self._read_video,
            args=(generation, self._forward_port, self._ffmpeg.stdin.fileno()),
            name="nier-preview-video",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._watch_processes,
            args=(generation,),
            name="nier-preview-watch",
            daemon=True,
        ).start()

    def _read_output(self, generation: int, label: str, stream: BinaryIO) -> None:
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

    def _read_video(self, generation: int, port: int, ffmpeg_stdin: int) -> None:
        deadline = time.monotonic() + 20
        video_socket: socket.socket | None = None
        while time.monotonic() < deadline:
            with self._lock:
                if generation != self._generation or not self._active:
                    return
            candidate: socket.socket | None = None
            try:
                candidate = socket.create_connection(("127.0.0.1", port), timeout=1)
                candidate.settimeout(1)
                # adb forward may accept the host connection before the device
                # has bound its abstract socket. scrcpy's client distinguishes
                # that early close from a ready server with this one-byte marker.
                marker = candidate.recv(1)
                if marker == b"\0":
                    video_socket = candidate
                    video_socket.settimeout(1)
                    break
            except OSError:
                pass
            if candidate is not None:
                try:
                    candidate.close()
                except OSError:
                    pass
            time.sleep(0.2)

        if video_socket is None:
            self._fail(generation, "等待 scrcpy 视频连接超时")
            return

        with self._lock:
            if generation != self._generation or not self._active:
                video_socket.close()
                return
            self._video_socket = video_socket
            self._connected = True

        try:
            while True:
                with self._lock:
                    if generation != self._generation or not self._active:
                        return
                try:
                    chunk = video_socket.recv(64 * 1024)
                except socket.timeout:
                    continue
                if not chunk:
                    self._fail(generation, "scrcpy 视频连接已断开")
                    return
                self._write_all(ffmpeg_stdin, chunk)
        except (BrokenPipeError, OSError) as exc:
            self._fail(generation, f"向 FFmpeg 传送 H.264 视频失败：{exc}")
        finally:
            with self._lock:
                if self._video_socket is video_socket:
                    self._video_socket = None
            try:
                video_socket.close()
            except OSError:
                pass

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise BrokenPipeError("FFmpeg stdin 已关闭")
            view = view[written:]

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
                server_process = self._server
                ffmpeg_process = self._ffmpeg
            if server_process is not None and server_process.poll() is not None:
                self._fail(generation, "scrcpy server 已退出")
                return
            if ffmpeg_process is not None and ffmpeg_process.poll() is not None:
                self._fail(generation, "FFmpeg 视频转换已退出")
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
        self._screen_size = None

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

        video_socket = self._video_socket
        self._video_socket = None
        if video_socket is not None:
            try:
                video_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                video_socket.close()
            except OSError:
                pass

        for process in (self._server, self._ffmpeg, self._pending_server, self._pending_ffmpeg):
            if process is self._ffmpeg or process is self._pending_ffmpeg:
                if process is not None and process.stdin is not None:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
            self._terminate(process)
        self._server = None
        self._ffmpeg = None
        self._pending_server = None
        self._pending_ffmpeg = None

        adb_path, serial, port = self._adb_path, self._forward_serial, self._forward_port
        self._adb_path = None
        self._forward_serial = None
        self._forward_port = None
        if adb_path is not None and serial is not None and port is not None:
            try:
                subprocess.run(
                    [adb_path, "-s", serial, "forward", "--remove", f"tcp:{port}"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=4,
                )
            except (OSError, subprocess.SubprocessError):
                pass

        if status == "idle":
            self._serial = None

    @staticmethod
    def _find_server_path(scrcpy_path: str | None) -> str | None:
        configured = os.environ.get("SCRCPY_SERVER_PATH")
        if configured:
            path = Path(configured).expanduser()
            return str(path) if path.is_file() else None
        if scrcpy_path is None:
            return None

        executable = Path(scrcpy_path).resolve()
        candidates = (
            executable.parent.parent / "share" / "scrcpy" / "scrcpy-server",
            executable.parent / "scrcpy-server",
            Path("/usr/share/scrcpy/scrcpy-server"),
            Path.cwd() / "scrcpy-server",
        )
        return next((str(path) for path in candidates if path.is_file()), None)

    @staticmethod
    def _get_scrcpy_version(scrcpy_path: str) -> str:
        try:
            result = subprocess.run(
                [scrcpy_path, "--version"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PreviewUnavailable(f"无法读取 scrcpy 版本：{exc}") from exc
        match = re.search(r"(?m)^scrcpy\s+([^\s]+)", result.stdout or result.stderr)
        if match is None:
            raise PreviewUnavailable("无法从 scrcpy --version 读取服务端版本")
        return match.group(1)

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
