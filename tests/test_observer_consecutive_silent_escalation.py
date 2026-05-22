# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from solstone_linux import observer as observer_module
from solstone_linux import session_env
from solstone_linux.config import Config
from solstone_linux.observer import MODE_SCREENCAST, Observer
from solstone_linux.screencast import SilentStream, StreamInfo


def _healthy(connector: str = "HDMI-1", position: str = "right") -> StreamInfo:
    return StreamInfo(
        node_id=42,
        position=position,
        connector=connector,
        x=0,
        y=0,
        width=1920,
        height=1080,
        file_path=f"/tmp/{position}_{connector}_screen.webm",
    )


def _silent(connector: str = "HDMI-1", position: str = "right") -> SilentStream:
    return SilentStream(
        node_id=42,
        connector=connector,
        position=position,
        file_path=Path(f"/tmp/{position}_{connector}_screen.webm"),
        file_frames=0,
        file_bytes=418,
    )


def _observer(tmp_path: Path) -> Observer:
    observer = Observer(Config(base_dir=tmp_path))
    observer._dbus_service = MagicMock()
    observer._tray = MagicMock()
    return observer


def test_three_consecutive_silent_segments_invalidates_restore_token(tmp_path: Path):
    observer = _observer(tmp_path)
    observer.config.config_dir.mkdir(parents=True)
    observer.config.restore_token_path.write_text("token\n")

    with patch("solstone_linux.observer.subprocess.Popen") as popen:
        for _ in range(3):
            observer._handle_boundary_stream_health([], [_silent()])

    assert not observer.config.restore_token_path.exists()
    assert observer._consecutive_silent["HDMI-1"] == 0
    assert "HDMI-1" in observer._recovering
    observer._dbus_service.StreamHealthChanged.assert_any_call("HDMI-1", "recovering")
    assert any(
        call.args[0][-1]
        == "sol observer reconfiguring screen access — you may see a permission prompt."
        for call in popen.call_args_list
    )


def test_all_silent_streak_exits_with_tempfail_after_five_boundaries(tmp_path: Path):
    observer = _observer(tmp_path)

    with patch("solstone_linux.observer.subprocess.Popen"):
        for _ in range(5):
            observer._handle_boundary_stream_health([], [_silent()])

    assert observer._all_silent_streak == 5
    assert observer.exit_code == 75
    assert observer.running is False


def test_healthy_boundary_resets_streak_and_silent_state(tmp_path: Path):
    observer = _observer(tmp_path)

    with patch("solstone_linux.observer.subprocess.Popen"):
        observer._handle_boundary_stream_health([], [_silent()])
        observer._handle_boundary_stream_health([_healthy()], [])

    assert observer._all_silent_streak == 0
    assert observer._consecutive_silent["HDMI-1"] == 0
    assert "HDMI-1" not in observer._notified_silent
    observer._dbus_service.StreamHealthChanged.assert_any_call("HDMI-1", "ok")


@pytest.mark.asyncio
async def test_shutdown_stop_site_does_not_advance_silent_counters(
    tmp_path: Path, monkeypatch
):
    observer = _observer(tmp_path)
    observer.current_mode = MODE_SCREENCAST
    observer.screencaster.stop = AsyncMock(return_value=([], [_silent()]))
    observer.audio_recorder.stop_recording = MagicMock()
    monkeypatch.setattr(observer_module.asyncio, "sleep", AsyncMock())

    await observer.shutdown()

    assert observer._consecutive_silent == {}
    assert observer._all_silent_streak == 0


@pytest.mark.asyncio
async def test_async_run_returns_observer_exit_code(tmp_path: Path, monkeypatch):
    class FakeLoop:
        def add_signal_handler(self, *args):
            pass

    class FakeObserver:
        def __init__(self, config):
            self.running = True
            self.exit_code = 75

        async def setup(self):
            return True

        async def main_loop(self):
            return None

    monkeypatch.setattr(session_env, "check_session_ready", lambda: None)
    monkeypatch.setattr(observer_module.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(observer_module, "Observer", FakeObserver)

    assert await observer_module.async_run(Config(base_dir=tmp_path)) == 75
