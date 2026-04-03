# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from solstone_linux.config import Config
from solstone_linux.recovery import recover_incomplete_segments
from solstone_linux.upload import ErrorType, UploadClient, UploadResult


class TestRecovery:
    """Test crash recovery for incomplete segments."""

    def _make_incomplete(
        self, captures_dir: Path, day: str, stream: str, time_prefix: str, age: int = 300
    ) -> Path:
        """Create an incomplete segment directory with a dummy file."""
        seg_dir = captures_dir / day / stream / f"{time_prefix}.incomplete"
        seg_dir.mkdir(parents=True)
        (seg_dir / "center_DP-3_screen.webm").write_bytes(b"\x00" * 100)

        # Set timestamps to simulate age
        old_time = time.time() - age
        os.utime(seg_dir, (old_time, old_time))
        return seg_dir

    def test_recovers_old_incomplete(self, tmp_path: Path):
        captures_dir = tmp_path / "captures"
        self._make_incomplete(captures_dir, "20260403", "archon", "140000", age=300)

        recovered = recover_incomplete_segments(captures_dir)
        assert recovered == 1

        stream_dir = captures_dir / "20260403" / "archon"
        dirs = [d.name for d in stream_dir.iterdir() if d.is_dir()]
        assert len(dirs) == 1
        assert dirs[0].startswith("140000_")
        assert not dirs[0].endswith(".incomplete")

    def test_recovers_with_metadata(self, tmp_path: Path):
        """Recovery uses .metadata start_timestamp for accurate duration."""
        captures_dir = tmp_path / "captures"
        seg_dir = captures_dir / "20260403" / "archon" / "140000.incomplete"
        seg_dir.mkdir(parents=True)
        (seg_dir / "center_DP-3_screen.webm").write_bytes(b"\x00" * 100)

        # Write metadata with known start timestamp (60 seconds ago)
        start_ts = time.time() - 60
        meta = {"start_timestamp": start_ts}
        (seg_dir / ".metadata").write_text(json.dumps(meta))

        # Age the directory
        old_time = time.time() - 300
        os.utime(seg_dir, (old_time, old_time))

        recovered = recover_incomplete_segments(captures_dir)
        assert recovered == 1

        stream_dir = captures_dir / "20260403" / "archon"
        dirs = [d.name for d in stream_dir.iterdir() if d.is_dir()]
        assert len(dirs) == 1
        # Duration should be based on metadata start timestamp, not mtime-ctime
        duration = int(dirs[0].split("_")[1])
        assert 55 <= duration <= 65  # ~60 seconds

    def test_skips_recent_incomplete(self, tmp_path: Path):
        captures_dir = tmp_path / "captures"
        seg_dir = captures_dir / "20260403" / "archon" / "140000.incomplete"
        seg_dir.mkdir(parents=True)
        (seg_dir / "test.webm").write_bytes(b"\x00")

        recovered = recover_incomplete_segments(captures_dir)
        assert recovered == 0
        assert seg_dir.exists()

    def test_marks_empty_as_failed(self, tmp_path: Path):
        captures_dir = tmp_path / "captures"
        seg_dir = captures_dir / "20260403" / "archon" / "140000.incomplete"
        seg_dir.mkdir(parents=True)
        # No files inside — should fail

        old_time = time.time() - 300
        os.utime(seg_dir, (old_time, old_time))

        recovered = recover_incomplete_segments(captures_dir)
        assert recovered == 0

        failed_dir = captures_dir / "20260403" / "archon" / "140000.failed"
        assert failed_dir.exists()

    def test_metadata_removed_on_recovery(self, tmp_path: Path):
        """The .metadata file should be removed during recovery."""
        captures_dir = tmp_path / "captures"
        seg_dir = captures_dir / "20260403" / "archon" / "140000.incomplete"
        seg_dir.mkdir(parents=True)
        (seg_dir / "screen.webm").write_bytes(b"\x00")
        (seg_dir / ".metadata").write_text('{"start_timestamp": 1000}')

        old_time = time.time() - 300
        os.utime(seg_dir, (old_time, old_time))

        recover_incomplete_segments(captures_dir)

        stream_dir = captures_dir / "20260403" / "archon"
        for d in stream_dir.iterdir():
            if d.is_dir() and not d.name.endswith((".incomplete", ".failed")):
                # .metadata should not be in the recovered dir
                assert not (d / ".metadata").exists()

    def test_no_captures_dir(self, tmp_path: Path):
        assert recover_incomplete_segments(tmp_path / "nonexistent") == 0


class TestSyncServiceCollect:
    """Test segment collection logic."""

    def test_skips_incomplete_and_failed(self, tmp_path: Path):
        from solstone_linux.sync import SyncService

        config = Config(base_dir=tmp_path)
        config.ensure_dirs()

        captures = config.captures_dir
        stream_dir = captures / "20260403" / "archon"
        stream_dir.mkdir(parents=True)

        (stream_dir / "140000_300").mkdir()
        (stream_dir / "140000_300" / "screen.webm").write_bytes(b"\x00")
        (stream_dir / "145000.incomplete").mkdir()
        (stream_dir / "143000.failed").mkdir()
        (stream_dir / "150000_300").mkdir()
        (stream_dir / "150000_300" / "audio.flac").write_bytes(b"\x00")

        client = UploadClient(config)
        sync = SyncService(config, client)

        segments = sync._collect_segments(captures)
        assert "20260403" in segments
        names = [s.name for s in segments["20260403"]]
        assert "140000_300" in names
        assert "150000_300" in names
        assert "145000.incomplete" not in names
        assert "143000.failed" not in names


class TestSyncedDaysPruning:
    """Test that synced-days cache is pruned to 90 days."""

    def test_prunes_old_entries(self, tmp_path: Path):
        from solstone_linux.sync import SyncService

        config = Config(base_dir=tmp_path)
        config.ensure_dirs()

        client = UploadClient(config)
        sync = SyncService(config, client)

        # Add entries spanning 100 days
        from datetime import datetime, timedelta
        today = datetime.now()
        for i in range(100):
            day = (today - timedelta(days=i)).strftime("%Y%m%d")
            sync._synced_days.add(day)

        sync._prune_synced_days()

        # Should have ~90 entries (not 100)
        assert len(sync._synced_days) <= 91  # Allow 1 day tolerance


class TestErrorClassification:
    """Test HTTP error classification for circuit breaker tuning."""

    def test_auth_errors(self):
        assert UploadClient.classify_error(401) == ErrorType.AUTH
        assert UploadClient.classify_error(403) == ErrorType.AUTH

    def test_client_errors(self):
        assert UploadClient.classify_error(400) == ErrorType.CLIENT

    def test_transient_errors(self):
        assert UploadClient.classify_error(500) == ErrorType.TRANSIENT
        assert UploadClient.classify_error(502) == ErrorType.TRANSIENT
        assert UploadClient.classify_error(503) == ErrorType.TRANSIENT

    def test_network_errors(self):
        assert UploadClient.classify_error(None, is_network_error=True) == ErrorType.TRANSIENT

    def test_unknown_status(self):
        assert UploadClient.classify_error(418) == ErrorType.TRANSIENT


class TestCircuitBreakerThresholds:
    """Test circuit breaker state transitions with error-type tuning."""

    def test_auth_opens_immediately(self, tmp_path: Path):
        from solstone_linux.sync import SyncService, CIRCUIT_THRESHOLD_AUTH

        config = Config(base_dir=tmp_path)
        config.ensure_dirs()
        client = UploadClient(config)
        sync = SyncService(config, client)

        sync._last_error_type = ErrorType.AUTH
        assert sync._circuit_threshold() == CIRCUIT_THRESHOLD_AUTH
        assert CIRCUIT_THRESHOLD_AUTH == 1

    def test_transient_allows_more_failures(self, tmp_path: Path):
        from solstone_linux.sync import SyncService, CIRCUIT_THRESHOLD_TRANSIENT

        config = Config(base_dir=tmp_path)
        config.ensure_dirs()
        client = UploadClient(config)
        sync = SyncService(config, client)

        sync._last_error_type = ErrorType.TRANSIENT
        assert sync._circuit_threshold() == CIRCUIT_THRESHOLD_TRANSIENT
        assert CIRCUIT_THRESHOLD_TRANSIENT >= 5


class TestRetryCapRespected:
    """Test that upload respects configured retry cap (no hard min(config,3))."""

    def test_respects_configured_max_retries(self):
        """Upload client should use the configured max_retries, not cap at 3."""
        config = Config()
        config.sync_max_retries = 10
        client = UploadClient(config)
        assert client._max_retries == 10

    def test_low_max_retries_respected(self):
        config = Config()
        config.sync_max_retries = 1
        client = UploadClient(config)
        assert client._max_retries == 1
