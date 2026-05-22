# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from pathlib import Path
from unittest.mock import MagicMock, patch

from solstone_linux.config import Config
from solstone_linux.observer import MODE_SCREENCAST, Observer
from solstone_linux.screencast import StreamInfo


def _stream(connector: str = "HDMI-1", position: str = "right") -> StreamInfo:
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


def _observer(tmp_path: Path) -> Observer:
    observer = Observer(Config(base_dir=tmp_path))
    stream = _stream()
    observer.current_mode = MODE_SCREENCAST
    observer.current_streams = [stream]
    observer.start_at_mono = 0.0
    observer._reset_stream_liveness(observer.current_streams)
    observer.screencaster.liveness_snapshot = MagicMock()
    observer._dbus_service = MagicMock()
    observer._tray = MagicMock()
    return observer


def test_declares_silent_when_t60_and_t120_stay_below_threshold(tmp_path: Path):
    observer = _observer(tmp_path)

    with patch("solstone_linux.observer.subprocess.Popen") as popen:
        observer.screencaster.liveness_snapshot.return_value = {"HDMI-1": 418}
        with patch("solstone_linux.observer.time.monotonic", return_value=65.0):
            observer._poll_stream_liveness()

        observer._dbus_service.StreamHealthChanged.assert_not_called()

        with patch("solstone_linux.observer.time.monotonic", return_value=125.0):
            observer._poll_stream_liveness()

    observer._dbus_service.ErrorOccurred.assert_called_once_with(
        "stream silent: right (HDMI-1)"
    )
    observer._dbus_service.StreamHealthChanged.assert_called_once_with(
        "HDMI-1", "silent"
    )
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
    assert observer.stream_health()["HDMI-1"] == "silent"
    assert observer._tray.update.called is True


def test_does_not_declare_if_first_t60_poll_is_above_threshold(tmp_path: Path):
    observer = _observer(tmp_path)

    with patch("solstone_linux.observer.subprocess.Popen") as popen:
        observer.screencaster.liveness_snapshot.return_value = {"HDMI-1": 4096}
        with patch("solstone_linux.observer.time.monotonic", return_value=65.0):
            observer._poll_stream_liveness()

        observer.screencaster.liveness_snapshot.return_value = {"HDMI-1": 418}
        with patch("solstone_linux.observer.time.monotonic", return_value=125.0):
            observer._poll_stream_liveness()

    observer._dbus_service.ErrorOccurred.assert_not_called()
    observer._dbus_service.StreamHealthChanged.assert_not_called()
    popen.assert_not_called()


def test_mid_segment_declaration_only_fires_once_per_segment(tmp_path: Path):
    observer = _observer(tmp_path)
    observer.screencaster.liveness_snapshot.return_value = {"HDMI-1": 418}

    with patch("solstone_linux.observer.subprocess.Popen"):
        with patch("solstone_linux.observer.time.monotonic", return_value=65.0):
            observer._poll_stream_liveness()
        with patch("solstone_linux.observer.time.monotonic", return_value=125.0):
            observer._poll_stream_liveness()

        observer._dbus_service.StreamHealthChanged.reset_mock()
        observer._dbus_service.ErrorOccurred.reset_mock()

        with patch("solstone_linux.observer.time.monotonic", return_value=130.0):
            observer._poll_stream_liveness()

    observer._dbus_service.StreamHealthChanged.assert_not_called()
    observer._dbus_service.ErrorOccurred.assert_not_called()
