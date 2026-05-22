# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from pathlib import Path
from unittest.mock import MagicMock, patch

from solstone_linux.config import Config
from solstone_linux.observer import Observer
from solstone_linux.screencast import SilentStream, StreamInfo


def _healthy() -> StreamInfo:
    return StreamInfo(
        node_id=42,
        position="right",
        connector="HDMI-1",
        x=0,
        y=0,
        width=1920,
        height=1080,
        file_path="/tmp/right_HDMI-1_screen.webm",
    )


def _silent() -> SilentStream:
    return SilentStream(
        node_id=42,
        connector="HDMI-1",
        position="right",
        file_path=Path("/tmp/right_HDMI-1_screen.webm"),
        file_frames=0,
        file_bytes=418,
    )


def _observer(tmp_path: Path) -> Observer:
    observer = Observer(Config(base_dir=tmp_path))
    observer._dbus_service = MagicMock()
    return observer


def test_silent_notification_fires_once_per_connector(tmp_path: Path):
    observer = _observer(tmp_path)

    with patch("solstone_linux.observer.subprocess.Popen") as popen:
        observer._handle_boundary_stream_health([], [_silent()])
        observer._handle_boundary_stream_health([], [_silent()])

    assert popen.call_count == 1
    popen.assert_called_once_with(
        [
            "notify-send",
            "-a",
            "sol observer",
            "sol observer",
            "right monitor (HDMI-1) stopped being observed. "
            "Check display power/cable, or sign in to portal again.",
        ]
    )


def test_recovery_notification_fires_when_connector_is_healthy_again(tmp_path: Path):
    observer = _observer(tmp_path)

    with patch("solstone_linux.observer.subprocess.Popen") as popen:
        observer._handle_boundary_stream_health([], [_silent()])
        observer._handle_boundary_stream_health([_healthy()], [])

    assert popen.call_args_list[-1].args[0] == [
        "notify-send",
        "-a",
        "sol observer",
        "sol observer",
        "right monitor (HDMI-1) back online.",
    ]
    assert "HDMI-1" not in observer._notified_silent


def test_notify_send_failure_does_not_raise(tmp_path: Path):
    observer = _observer(tmp_path)

    with patch("solstone_linux.observer.subprocess.Popen", side_effect=OSError):
        observer._notify("sol observer", "body")


def test_restore_token_invalidation_sends_reconfigure_notification(tmp_path: Path):
    observer = _observer(tmp_path)
    observer.config.config_dir.mkdir(parents=True)
    observer.config.restore_token_path.write_text("token\n")

    with patch("solstone_linux.observer.subprocess.Popen") as popen:
        for _ in range(3):
            observer._handle_boundary_stream_health([], [_silent()])

    assert any(
        call.args[0]
        == [
            "notify-send",
            "-a",
            "sol observer",
            "sol observer",
            "sol observer reconfiguring screen access — you may see a permission prompt.",
        ]
        for call in popen.call_args_list
    )
