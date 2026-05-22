# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from pathlib import Path
from unittest.mock import MagicMock

from dbus_next.service import ServiceInterface

from solstone_linux.config import Config
from solstone_linux.dbus_service import ObserverService
from solstone_linux.observer import Observer
from solstone_linux.screencast import StreamInfo


def _get_prop(service, name):
    for prop in ServiceInterface._get_properties(service):
        if prop.name == name:
            return prop.prop_getter(service)
    raise KeyError(name)


def _stream(connector: str = "HDMI-1") -> StreamInfo:
    return StreamInfo(
        node_id=42,
        position="right",
        connector=connector,
        x=0,
        y=0,
        width=1920,
        height=1080,
        file_path=f"/tmp/right_{connector}_screen.webm",
    )


def test_stream_health_property_returns_observer_map():
    observer = MagicMock()
    observer.stream_health.return_value = {"HDMI-1": "silent"}
    service = ObserverService(observer)

    assert _get_prop(service, "StreamHealth") == {"HDMI-1": "silent"}


def test_stream_health_precedence_recovering_over_silent(tmp_path: Path):
    observer = Observer(Config(base_dir=tmp_path))
    observer.current_streams = [_stream()]
    observer._notified_silent.add("HDMI-1")
    observer._consecutive_silent["HDMI-1"] = 1
    observer._recovering.add("HDMI-1")
    service = ObserverService(observer)

    assert _get_prop(service, "StreamHealth") == {"HDMI-1": "recovering"}


def test_stream_health_defaults_current_streams_to_ok(tmp_path: Path):
    observer = Observer(Config(base_dir=tmp_path))
    observer.current_streams = [_stream("DP-1")]
    service = ObserverService(observer)

    assert _get_prop(service, "StreamHealth") == {"DP-1": "ok"}


def test_stream_health_changed_signal_is_registered():
    service = ObserverService(MagicMock())

    signals = {signal.name: signal for signal in ServiceInterface._get_signals(service)}

    assert "StreamHealthChanged" in signals
    assert service.StreamHealthChanged("HDMI-1", "silent") == [
        "HDMI-1",
        "silent",
    ]
