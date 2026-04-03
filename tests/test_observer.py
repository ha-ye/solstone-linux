# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Tests for the observer module — segment lifecycle and local cache."""

from pathlib import Path

from solstone_linux.config import Config
from solstone_linux.recovery import write_segment_metadata


class TestSegmentMetadata:
    """Test .metadata file creation for recovery."""

    def test_writes_metadata(self, tmp_path: Path):
        import json

        seg_dir = tmp_path / "test.incomplete"
        seg_dir.mkdir()
        write_segment_metadata(seg_dir, 1712160000.0)

        meta_path = seg_dir / ".metadata"
        assert meta_path.exists()

        data = json.loads(meta_path.read_text())
        assert data["start_timestamp"] == 1712160000.0


class TestSegmentDirStructure:
    """Test that config directories follow the expected structure."""

    def test_captures_dir_path(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        assert str(config.captures_dir).endswith("captures")

    def test_restore_token_path(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        assert str(config.restore_token_path).endswith("restore_token")
        assert "config" in str(config.restore_token_path)
