# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from pathlib import Path
from unittest.mock import MagicMock

from solstone_linux.config import Config, load_config
from solstone_linux.sync_health import ErrorType
from solstone_linux.upload import UploadClient


def test_ensure_registered_posts_descriptor_and_persists(tmp_path: Path):
    config = Config(
        base_dir=tmp_path,
        server_url="http://localhost:9999",
        stream="host-a",
    )
    client = UploadClient(config)
    client._session = MagicMock()
    client._session.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "key": "K123456789",
            "prefix": "K1234567",
            "name": "fedora",
            "ingest_url": "/app/observer/ingest",
            "protocol_version": 2,
        },
    )

    assert client.ensure_registered(config) is True

    client._session.post.assert_called_once()
    call = client._session.post.call_args
    assert call.args[0].endswith("/app/observer/register")
    descriptor = call.kwargs["json"]
    assert descriptor["stream_type"] == "desktop"
    assert descriptor["platform"]
    assert descriptor["hostname"]
    assert descriptor["version"]
    assert descriptor["label"] == "host-a"
    assert config.key == "K123456789"
    assert config.stream == "fedora"
    assert client._key == "K123456789"

    reloaded = load_config(base_dir=tmp_path)
    assert reloaded.key == "K123456789"
    assert reloaded.stream == "fedora"


def test_ensure_registered_skips_when_key_present(tmp_path: Path):
    config = Config(
        base_dir=tmp_path,
        server_url="http://localhost:9999",
        key="existing",
    )
    client = UploadClient(config)
    client._session = MagicMock()

    assert client.ensure_registered(config) is True
    client._session.post.assert_not_called()


def test_upload_segment_uses_bearer_and_keyless_route(tmp_path: Path):
    config = Config(base_dir=tmp_path, server_url="http://localhost:9999", key="K")
    client = UploadClient(config)
    client._session = MagicMock()
    client._session.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"status": "ok"},
    )
    media = tmp_path / "audio.flac"
    media.write_bytes(b"audio")

    result = client.upload_segment("20260101", "120000_005", [media])

    assert result.success
    call = client._session.post.call_args
    url = call.args[0]
    assert url.endswith("/app/observer/ingest")
    assert "/ingest/K" not in url
    assert call.kwargs["headers"] == {"Authorization": "Bearer K"}
    assert call.kwargs["data"] == {"day": "20260101", "segment": "120000_005"}
    assert "stream" not in call.kwargs["data"]
    assert "meta" not in call.kwargs["data"]
    assert "files" in call.kwargs


def test_relay_event_uses_bearer_and_keyless_route(tmp_path: Path):
    config = Config(base_dir=tmp_path, server_url="http://localhost:9999", key="K")
    client = UploadClient(config)
    client._session = MagicMock()
    client._session.post.return_value = MagicMock(status_code=200)

    assert client.relay_event("observe", "status", mode="idle") is True

    call = client._session.post.call_args
    assert call.args[0].endswith("/app/observer/ingest/event")
    assert call.kwargs["headers"] == {"Authorization": "Bearer K"}
    assert call.kwargs["json"] == {
        "tract": "observe",
        "event": "status",
        "mode": "idle",
    }
    assert "stream" not in call.kwargs["json"]


def test_get_server_segments_uses_bearer_and_keyless_route(tmp_path: Path):
    config = Config(base_dir=tmp_path, server_url="http://localhost:9999", key="K")
    client = UploadClient(config)
    client._session = MagicMock()
    client._session.get.return_value = MagicMock(status_code=200, json=lambda: [])

    result = client.get_server_segments("20260101")

    assert result.segments == []
    assert result.error_type is None
    assert result.status_code == 200

    call = client._session.get.call_args
    assert call.args[0].endswith("/app/observer/ingest/segments/20260101")
    assert call.kwargs["headers"] == {"Authorization": "Bearer K"}
    params = call.kwargs.get("params")
    assert params is None or "stream" not in params


def test_get_server_segments_classifies_404_as_incompatible(tmp_path: Path):
    config = Config(base_dir=tmp_path, server_url="http://localhost:9999", key="K")
    client = UploadClient(config)
    client._session = MagicMock()
    client._session.get.return_value = MagicMock(status_code=404)

    result = client.get_server_segments("20260101")

    assert result.segments is None
    assert result.error_type == ErrorType.INCOMPATIBLE
    assert result.status_code == 404
