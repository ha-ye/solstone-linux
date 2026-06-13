# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from pathlib import Path

from solstone_linux.config import Config, load_config, save_config


class TestConfig:
    def test_defaults(self):
        config = Config()
        assert config.server_url == ""
        assert config.key == ""
        assert config.segment_interval == 300

    def test_captures_dir(self):
        config = Config()
        assert config.captures_dir == config.base_dir / "captures"

    def test_restore_token_path(self):
        config = Config()
        assert config.restore_token_path == config.base_dir / "config" / "restore_token"

    def test_round_trip(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        config.server_url = "https://example.com"
        config.key = "test-key-123"
        config.stream = "archon"
        config.segment_interval = 600

        save_config(config)

        loaded = load_config(tmp_path)
        assert loaded.server_url == "https://example.com"
        assert loaded.key == "test-key-123"
        assert loaded.stream == "archon"
        assert loaded.segment_interval == 600

    def test_load_missing(self, tmp_path: Path):
        config = load_config(tmp_path)
        assert config.server_url == ""
        assert config.key == ""

    def test_load_corrupt(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text("not json!")

        config = load_config(tmp_path)
        assert config.server_url == ""

    def test_permissions(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        config.server_url = "https://example.com"
        config.key = "secret"
        save_config(config)

        mode = config.config_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_sync_config_roundtrip(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        config.sync_retry_delays = [10, 60, 300]
        config.sync_max_retries = 5
        save_config(config)

        loaded = load_config(tmp_path)
        assert loaded.sync_retry_delays == [10, 60, 300]
        assert loaded.sync_max_retries == 5

    def test_cache_retention_days_roundtrip(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        config.cache_retention_days = 14
        save_config(config)

        loaded = load_config(tmp_path)
        assert loaded.cache_retention_days == 14

    def test_cache_retention_days_default(self, tmp_path: Path):
        """Existing configs without cache_retention_days default to 7."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text('{"server_url": "http://test"}')

        loaded = load_config(tmp_path)
        assert loaded.cache_retention_days == 7

    def test_capture_framerate_default(self):
        config = Config()
        assert config.capture_framerate == 1

    def test_draw_cursor_default(self):
        config = Config()
        assert config.draw_cursor is True

    def test_capture_framerate_roundtrip(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        config.capture_framerate = 2
        save_config(config)

        loaded = load_config(tmp_path)
        assert loaded.capture_framerate == 2

    def test_draw_cursor_roundtrip(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        config.draw_cursor = False
        save_config(config)

        loaded = load_config(tmp_path)
        assert loaded.draw_cursor is False

    def test_capture_framerate_defaults_on_old_config(self, tmp_path: Path):
        """Existing configs without capture_framerate default to 1."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text('{"server_url": "http://test"}')

        loaded = load_config(tmp_path)
        assert loaded.capture_framerate == 1
        assert loaded.draw_cursor is True

    def test_capture_framerate_clamped_to_max(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text('{"capture_framerate": 999}')

        loaded = load_config(tmp_path)
        assert loaded.capture_framerate == 10

    def test_capture_framerate_clamped_to_min(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text('{"capture_framerate": 0}')

        loaded = load_config(tmp_path)
        assert loaded.capture_framerate == 1

    def test_start_paused_default(self):
        config = Config()
        assert config.start_paused is False

    def test_start_paused_roundtrip(self, tmp_path: Path):
        config = Config(base_dir=tmp_path)
        config.start_paused = True
        save_config(config)

        loaded = load_config(tmp_path)
        assert loaded.start_paused is True

    def test_start_paused_defaults_on_old_config(self, tmp_path: Path):
        """Existing configs without start_paused default to False."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text('{"server_url": "http://test"}')

        loaded = load_config(tmp_path)
        assert loaded.start_paused is False
