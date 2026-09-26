from __future__ import annotations

import asyncio
import queue
import subprocess

from nier import web_preview
from nier.web_preview import ScrcpyPreview


def test_preview_reads_override_screen_size(monkeypatch) -> None:
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Physical size: 1240x2772\nOverride size: 1080x2400\n",
            stderr="",
        )

    monkeypatch.setattr(web_preview.subprocess, "run", run)

    assert ScrcpyPreview._read_screen_size("adb", "device-1") == (1080, 2400)
    assert commands == [["adb", "-s", "device-1", "shell", "wm", "size"]]


def test_preview_state_exposes_screen_size_for_coordinate_mapping(monkeypatch) -> None:
    preview = ScrcpyPreview()
    monkeypatch.setattr(web_preview.shutil, "which", lambda name: f"/mock/{name}")
    monkeypatch.setattr(preview, "_find_server_path", lambda _path: "/mock/server")
    monkeypatch.setattr(
        preview,
        "_list_devices",
        lambda _path: ([{"serial": "device-1", "state": "device"}], None),
    )
    monkeypatch.setattr(preview, "_get_scrcpy_version", lambda _path: "3.3")
    monkeypatch.setattr(preview, "_start_processes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(preview, "_start_readers_locked", lambda _generation: None)
    monkeypatch.setattr(
        web_preview.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="Physical size: 1240x2772\n", stderr=""
        ),
    )

    state = preview.start("device-1")

    assert state["screen_width"] == 1240
    assert state["screen_height"] == 2772
    preview.close()


def test_preview_stream_ends_when_client_disconnects() -> None:
    preview = ScrcpyPreview()
    preview._active = True
    subscriber: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
    preview._subscribers.add(subscriber)

    async def disconnected() -> bool:
        return True

    async def consume() -> None:
        async for _ in preview.stream(subscriber, is_disconnected=disconnected):
            pass

    asyncio.run(consume())

    assert subscriber not in preview._subscribers


def test_preview_shutdown_wakes_active_streams() -> None:
    preview = ScrcpyPreview()
    subscriber: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
    preview._subscribers.add(subscriber)

    preview.stop_streams()

    assert subscriber.get_nowait() is None
