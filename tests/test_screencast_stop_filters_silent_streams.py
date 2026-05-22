# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from solstone_linux import screencast
from solstone_linux.screencast import Screencaster, SilentStream, StreamInfo


def _stream(
    file_path: Path,
    *,
    node_id: int = 42,
    connector: str = "HDMI-1",
    position: str = "right",
) -> StreamInfo:
    return StreamInfo(
        node_id=node_id,
        position=position,
        connector=connector,
        x=0,
        y=0,
        width=1920,
        height=1080,
        file_path=str(file_path),
    )


def _caster(tmp_path: Path, streams: list[StreamInfo]) -> Screencaster:
    caster = Screencaster(restore_token_path=tmp_path / "fake")
    caster.streams = streams
    caster.gst_process = MagicMock()
    caster.gst_process.poll = MagicMock(return_value=None)
    caster.gst_process.send_signal = MagicMock()
    caster.gst_process.wait = MagicMock(return_value=0)
    caster.gst_process.kill = MagicMock()
    caster.pw_fd = None
    caster._close_session = AsyncMock()
    return caster


@pytest.mark.asyncio
async def test_stop_partitions_healthy_and_silent_by_frame_count(
    tmp_path: Path, monkeypatch
):
    healthy_path = tmp_path / "healthy.webm"
    silent_path = tmp_path / "silent.webm"
    healthy_path.write_bytes(b"h" * 4096)
    silent_path.write_bytes(b"s" * 418)
    monkeypatch.setattr(
        screencast,
        "_count_video_frames",
        lambda path: 30 if path == healthy_path else 0,
    )
    caster = _caster(
        tmp_path,
        [
            _stream(healthy_path, node_id=10, connector="DP-1", position="left"),
            _stream(silent_path, node_id=42, connector="HDMI-1", position="right"),
        ],
    )

    healthy_streams, silent_streams = await caster.stop()

    assert len(healthy_streams) == 1
    assert len(silent_streams) == 1
    assert healthy_path.exists()
    assert not silent_path.exists()
    silent = silent_streams[0]
    assert isinstance(silent, SilentStream)
    assert silent.file_frames == 0
    assert silent.file_bytes == 418
    assert silent.connector == "HDMI-1"
    assert silent.position == "right"
    assert silent.node_id == 42
    assert silent.file_path == silent_path


@pytest.mark.asyncio
async def test_stop_treats_missing_file_as_silent(tmp_path: Path, monkeypatch):
    missing_path = tmp_path / "missing.webm"
    monkeypatch.setattr(screencast, "_count_video_frames", lambda path: 0)
    caster = _caster(tmp_path, [_stream(missing_path)])

    healthy_streams, silent_streams = await caster.stop()

    assert healthy_streams == []
    assert len(silent_streams) == 1
    assert silent_streams[0].file_frames == 0
    assert silent_streams[0].file_bytes == 0
    assert silent_streams[0].file_path == missing_path


@pytest.mark.asyncio
async def test_stop_logs_silent_stream_dropped_prefix(
    tmp_path: Path, caplog, monkeypatch
):
    silent_path = tmp_path / "silent.webm"
    silent_path.write_bytes(b"s" * 418)
    monkeypatch.setattr(screencast, "_count_video_frames", lambda path: 1)
    caster = _caster(tmp_path, [_stream(silent_path)])

    caplog.set_level(logging.WARNING)
    await caster.stop()

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("silent stream dropped:")
        and "connector=HDMI-1" in message
        and "position=right" in message
        and "file_frames=1" in message
        and "file_bytes=418" in message
        and f"path={silent_path}" in message
        for message in messages
    )


@pytest.mark.asyncio
async def test_stop_handles_unlink_oserror(tmp_path: Path, caplog, monkeypatch):
    silent_path = tmp_path / "silent.webm"
    silent_path.write_bytes(b"s" * 418)
    monkeypatch.setattr(screencast, "_count_video_frames", lambda path: 0)
    caster = _caster(tmp_path, [_stream(silent_path)])

    def raise_oserror(self, missing_ok=False):
        raise OSError("disk error")

    monkeypatch.setattr(Path, "unlink", raise_oserror)
    caplog.set_level(logging.WARNING)

    healthy_streams, silent_streams = await caster.stop()

    assert healthy_streams == []
    assert len(silent_streams) == 1
    assert any("could not unlink" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_stop_treats_large_sparse_file_as_silent(tmp_path: Path, monkeypatch):
    sparse_path = tmp_path / "sparse.webm"
    sparse_path.write_bytes(b"s" * 106_529)
    monkeypatch.setattr(screencast, "_count_video_frames", lambda path: 3)
    caster = _caster(tmp_path, [_stream(sparse_path)])

    healthy_streams, silent_streams = await caster.stop()

    assert healthy_streams == []
    assert len(silent_streams) == 1
    assert silent_streams[0].file_frames == 3
    assert silent_streams[0].file_bytes == 106_529


def test_liveness_snapshot_stats_current_stream_files(tmp_path: Path):
    present_path = tmp_path / "present.webm"
    missing_path = tmp_path / "missing.webm"
    present_path.write_bytes(b"h" * 4096)
    caster = Screencaster(restore_token_path=tmp_path / "fake")
    caster.streams = [
        _stream(present_path, connector="DP-1", position="left"),
        _stream(missing_path, connector="HDMI-1", position="right"),
    ]

    assert caster.liveness_snapshot() == {"DP-1": 4096, "HDMI-1": 0}


def test_count_video_frames_logs_when_ffprobe_missing(
    tmp_path: Path, caplog, monkeypatch
):
    video_path = tmp_path / "video.webm"
    video_path.write_bytes(b"webm")
    screencast._ffprobe_missing_logged = False

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(screencast.subprocess, "run", raise_missing)
    caplog.set_level(logging.WARNING)

    assert screencast._count_video_frames(video_path) == 0

    assert any("ffprobe not found" in record.getMessage() for record in caplog.records)
