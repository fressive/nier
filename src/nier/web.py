"""Local web dashboard for running authorized Python scripts and viewing logs."""

from __future__ import annotations

import ast
from collections import deque
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit
import uuid
import webbrowser

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


_EVENT_PREFIX = "\x1eNIER_EVENT "
_NIER_TERMINAL_LINE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} \[nier ")


class RunRequest(BaseModel):
    script: str = Field(min_length=1, max_length=1024)
    confirmed: bool
    debug: bool = False


class DebugRequest(BaseModel):
    command: Literal["continue", "step", "step_into", "step_out"]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class _DashboardState:
    """Own one selected scripts directory, one child process, and live events."""

    def __init__(self, scripts: Path, cwd: Path) -> None:
        self.scripts = scripts.resolve()
        self.cwd = cwd.resolve()
        self.lock = threading.RLock()
        self.history: deque[dict[str, Any]] = deque(maxlen=2500)
        self.subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self.sequence = 0
        self.current_step_id: int | None = None
        self.process: subprocess.Popen[str] | None = None
        self.run_state: dict[str, Any] = {
            "id": None,
            "script": None,
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "debug": False,
            "debug_state": "inactive",
            "debug_location": None,
        }

    def list_scripts(self) -> list[dict[str, str]]:
        scripts: list[dict[str, str]] = []
        for path in sorted(self.scripts.rglob("*.py")):
            hidden_or_cache = any(
                part.startswith(".") or part == "__pycache__"
                for part in path.relative_to(self.scripts).parts
            )
            if path.is_symlink() or hidden_or_cache:
                continue
            relative = path.relative_to(self.scripts).as_posix()
            try:
                module = ast.parse(path.read_text(encoding="utf-8"))
                description = ast.get_docstring(module) or "Python script"
            except (OSError, SyntaxError, UnicodeError):
                description = "Python script"
            scripts.append(
                {
                    "path": relative,
                    "name": path.stem.replace("_", " "),
                    "description": description.splitlines()[0][:180],
                }
            )
        return scripts

    def _resolve_script(self, relative_path: str) -> Path:
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or "\x00" in relative_path
        ):
            raise ValueError("script path is required")
        available = {item["path"] for item in self.list_scripts()}
        if relative_path not in available:
            raise ValueError("script is not available in the selected scripts directory")
        candidate = (self.scripts / relative_path).resolve()
        if (
            not candidate.is_relative_to(self.scripts)
            or candidate.suffix != ".py"
            or not candidate.is_file()
        ):
            raise ValueError("script must be a Python file inside the selected scripts directory")
        return candidate

    def start(self, relative_path: str, *, debug: bool = False) -> dict[str, Any]:
        script = self._resolve_script(relative_path)
        with self.lock:
            if self.run_state["status"] in {"starting", "running", "stopping"}:
                raise RuntimeError("a script is already running")
            run_id = uuid.uuid4().hex
            self.history.clear()
            self.sequence = 0
            self.current_step_id = None
            self.run_state = {
                "id": run_id,
                "script": script.relative_to(self.scripts).as_posix(),
                "status": "starting",
                "started_at": _timestamp(),
                "finished_at": None,
                "exit_code": None,
                "debug": debug,
                "debug_state": "running" if debug else "inactive",
                "debug_location": None,
            }
            self._publish_locked(
                {
                    "type": "run.started",
                    "timestamp": self.run_state["started_at"],
                    "run_id": run_id,
                    "script": self.run_state["script"],
                    "debug": debug,
                }
            )
        threading.Thread(
            target=self._run_script,
            args=(script, run_id, debug),
            name=f"nier-web-{run_id[:8]}",
            daemon=True,
        ).start()
        return self.snapshot()

    def _run_script(self, script: Path, run_id: str, debug: bool) -> None:
        environment = os.environ.copy()
        environment["NIER_WEB_EVENT_STREAM"] = "1"
        environment["NIER_WEB_SCRIPT_ROOT"] = str(self.scripts)
        if debug:
            environment["NIER_WEB_DEBUG"] = "1"
        source_root = str(Path(__file__).resolve().parent.parent)
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            source_root
            if not existing_pythonpath
            else os.pathsep.join((source_root, existing_pythonpath))
        )
        try:
            command = (
                [sys.executable, "-u", "-m", "nier.web_runner", str(script)]
                if debug
                else [sys.executable, str(script)]
            )
            process = subprocess.Popen(
                command,
                cwd=self.cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                stdin=subprocess.PIPE if debug else None,
            )
        except OSError as exc:
            self._finish(run_id, None, f"could not start script: {exc}")
            return

        with self.lock:
            if self.run_state["id"] != run_id:
                process.terminate()
                return
            self.process = process
            self.run_state["pid"] = process.pid
            if self.run_state["status"] == "stopping":
                self._terminate_process(process)
            else:
                self.run_state["status"] = "running"
                self._publish_locked(
                    {
                        "type": "run.running",
                        "timestamp": _timestamp(),
                        "run_id": run_id,
                        "pid": process.pid,
                    }
                )

        readers = [
            threading.Thread(
                target=self._read_output,
                args=(stream, label, run_id),
                name=f"nier-web-{label}-{run_id[:8]}",
                daemon=True,
            )
            for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr"))
            if stream is not None
        ]
        for reader in readers:
            reader.start()
        exit_code = process.wait()
        for reader in readers:
            reader.join(timeout=2)
        self._finish(run_id, exit_code, None)

    def _read_output(self, stream, label: str, run_id: str) -> None:
        in_nier_block = False
        for line in stream:
            line = line.rstrip("\r\n")
            if label == "stdout" and line.startswith(_EVENT_PREFIX):
                try:
                    event = json.loads(line[len(_EVENT_PREFIX) :])
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and (
                    event.get("type") == "log"
                    or str(event.get("type", "")).startswith("debug.")
                ):
                    event["run_id"] = run_id
                    self.publish(event)
                continue
            if label == "stderr":
                if _NIER_TERMINAL_LINE.match(line):
                    in_nier_block = True
                    continue
                if in_nier_block and (not line or line[0].isspace()):
                    continue
                in_nier_block = False
            if line:
                self.publish(
                    {
                        "type": "console",
                        "timestamp": _timestamp(),
                        "run_id": run_id,
                        "stream": label,
                        "text": line[:4096],
                    }
                )

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if self.run_state["status"] not in {"starting", "running"}:
                return self.snapshot_locked()
            self.run_state["status"] = "stopping"
            if self.run_state.get("debug"):
                self.run_state["debug_state"] = "running"
            process = self.process
            self._publish_locked(
                {
                    "type": "run.stopping",
                    "timestamp": _timestamp(),
                    "run_id": self.run_state["id"],
                }
            )
        if process is not None:
            self._terminate_process(process)
        return self.snapshot()

    def debug(self, command: str) -> dict[str, Any]:
        """Send one execution control command to the paused debug runner."""
        with self.lock:
            if self.run_state.get("debug") is not True:
                raise RuntimeError("the current run was not started in debug mode")
            if self.run_state.get("status") not in {"starting", "running"}:
                raise RuntimeError("there is no active debug run")
            if self.run_state.get("debug_state") != "paused":
                raise RuntimeError("the debugger is not paused")
            process = self.process
            if process is None or process.stdin is None:
                raise RuntimeError("the debug runner is not ready")
            try:
                process.stdin.write(json.dumps({"command": command}) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError("the debug runner is no longer available") from exc
        return self.snapshot()

    @classmethod
    def _terminate_process(cls, process: subprocess.Popen[str]) -> None:
        try:
            process.terminate()
        except OSError:
            return
        force_kill = threading.Timer(3, cls._kill_if_running, args=(process,))
        force_kill.daemon = True
        force_kill.start()

    @staticmethod
    def _kill_if_running(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def _finish(self, run_id: str, exit_code: int | None, error: str | None) -> None:
        with self.lock:
            if self.run_state["id"] != run_id:
                return
            was_stopped = self.run_state["status"] == "stopping"
            status = (
                "stopped"
                if was_stopped
                else "completed"
                if exit_code == 0 and error is None
                else "failed"
            )
            self.run_state.update(
                status=status,
                finished_at=_timestamp(),
                exit_code=exit_code,
                error=error,
                debug_state="finished" if self.run_state.get("debug") else "inactive",
            )
            self.process = None
            self._publish_locked(
                {
                    "type": "run.finished",
                    "timestamp": self.run_state["finished_at"],
                    "run_id": run_id,
                    "status": status,
                    "exit_code": exit_code,
                    "error": error,
                }
            )

    def publish(self, event: dict[str, Any]) -> None:
        with self.lock:
            if event.get("run_id") != self.run_state.get("id"):
                return
            self._publish_locked(event)

    def _publish_locked(self, event: dict[str, Any]) -> None:
        self.sequence += 1
        event = dict(event)
        event["event_id"] = self.sequence
        event.setdefault("timestamp", _timestamp())
        if event.get("type") == "log" and event.get("category") == "STEP":
            self.current_step_id = self.sequence
            event["step_id"] = self.sequence
        elif event.get("type") == "log":
            event["step_id"] = self.current_step_id
        elif str(event.get("type", "")).startswith("debug."):
            event["step_id"] = self.current_step_id
        if event.get("type") == "debug.paused":
            self.run_state["debug_state"] = "paused"
            self.run_state["debug_location"] = {
                key: event.get(key)
                for key in ("step_id", "category", "message", "details", "depth", "file", "line", "function", "stack")
            }
        elif event.get("type") == "debug.resumed":
            self.run_state["debug_state"] = "running"
        self.history.append(event)
        for subscriber in tuple(self.subscribers):
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(event)
                except queue.Full:
                    pass

    def subscribe(self) -> tuple[queue.Queue[dict[str, Any]], list[dict[str, Any]]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
        with self.lock:
            self.subscribers.add(subscriber)
            return subscriber, list(self.history)

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            self.subscribers.discard(subscriber)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self.snapshot_locked()

    def snapshot_locked(self) -> dict[str, Any]:
        return {"run": dict(self.run_state), "events": list(self.history)}


def _asset_root() -> Path:
    return Path(__file__).resolve().parent / "web_static"


def create_app(scripts: Path, *, cwd: Path | None = None) -> FastAPI:
    """Create a FastAPI dashboard app for scripts inside ``scripts``."""
    scripts = scripts.resolve()
    if not scripts.is_dir():
        raise ValueError(f"scripts directory does not exist: {scripts}")
    asset_root = _asset_root()
    if not (asset_root / "index.html").is_file():
        raise RuntimeError(
            "Nier web assets are missing; run `npm install && npm run build` in the web directory"
        )

    state = _DashboardState(scripts, cwd or Path.cwd())
    app = FastAPI(
        title="Nier Execution Studio",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def check_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if not origin:
            return
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host"):
            raise HTTPException(status_code=403, detail="cross-origin requests are not allowed")

    @app.get("/api/scripts")
    def list_scripts() -> dict[str, Any]:
        return {"scripts": state.list_scripts()}

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        return state.snapshot()

    @app.get("/api/events")
    def stream_events():
        subscriber, history = state.subscribe()

        def events():
            try:
                for event in history:
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {event['event_id']}\ndata: {payload}\n\n"
                while True:
                    try:
                        event = subscriber.get(timeout=15)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {event['event_id']}\ndata: {payload}\n\n"
            finally:
                state.unsubscribe(subscriber)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/run", status_code=202)
    def run_script(payload: RunRequest, request: Request) -> dict[str, Any]:
        check_origin(request)
        if not payload.confirmed:
            raise HTTPException(status_code=400, detail="explicit run confirmation is required")
        try:
            return state.start(payload.script, debug=payload.debug)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/stop")
    def stop_script(request: Request) -> dict[str, Any]:
        check_origin(request)
        return state.stop()

    @app.post("/api/debug")
    def debug_script(payload: DebugRequest, request: Request) -> dict[str, Any]:
        check_origin(request)
        try:
            return state.debug(payload.command)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    app.mount("/", StaticFiles(directory=asset_root, html=True), name="web")
    app.state.dashboard = state
    return app


def serve_web(
    scripts: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Serve the dashboard through Uvicorn until interrupted."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - installation-specific
        raise RuntimeError("Uvicorn is required for `nier web`; reinstall Nier with its web dependencies") from exc
    if not 1 <= port <= 65535:
        raise ValueError("dashboard port must be between 1 and 65535")
    app = create_app(scripts)
    url = f"http://{host}:{port}"
    print(f"Nier web dashboard: {url}")
    print(f"Scripts: {scripts.resolve()}")
    if open_browser:
        webbrowser.open(url)
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        app.state.dashboard.stop()


__all__ = ["create_app", "serve_web"]
