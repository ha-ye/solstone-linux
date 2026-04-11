# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import time
from pathlib import Path
from unittest.mock import MagicMock

from solstone_linux.config import Config
from solstone_linux.dbusmenu import MenuItem, separator
from solstone_linux.tray import AGENT_INSTRUCTIONS, ICONS, SOURCE_DIR, TrayApp


def _make_app(tmp_path=None):
    config = Config()
    if tmp_path:
        config.base_dir = tmp_path
    config.server_url = "https://test.example.com"
    observer = MagicMock()
    observer.config = config
    observer._paused = False
    observer._pause_until = 0.0
    observer.current_mode = "screencast"
    observer.segment_dir = None
    observer.interval = 300
    observer.start_at_mono = time.monotonic()
    observer._sync = None
    observer._dbus_service = None
    bus = MagicMock()
    app = TrayApp(observer, bus)
    return app


class TestTrayInit:
    def test_make_app_uses_observer_config(self):
        app = _make_app()

        assert isinstance(app, TrayApp)
        assert app.config.server_url == "https://test.example.com"
        assert app.sni is not None
        assert app.menu is not None


class TestBuildMenu:
    def test_build_menu_creates_expected_items(self):
        app = _make_app()

        app._build_menu()

        assert isinstance(app._status_item, MenuItem)
        assert app._status_item.label == "observing"
        assert app._status_item.enabled is False
        assert app._sync_item.label == "sync: up to date"
        assert app._pause_submenu.children_display == "submenu"
        assert len(app._pause_submenu.children) == 4
        assert app._resume_item.visible is False
        assert app.menu._root.children[1].item_type == separator().item_type
        assert len(app.menu._root.children) == 9


class TestUpdateStatus:
    def test_update_status_paused(self):
        app = _make_app()
        app._build_menu()
        app.menu.update_item = MagicMock()

        app._update_status("paused")

        assert app.status == "paused"
        assert app._pause_submenu.visible is False
        assert app._resume_item.visible is True
        assert app._status_item.label == "paused"
        assert app.menu.update_item.call_count == 3

    def test_update_status_idle(self):
        app = _make_app()
        app._build_menu()

        app._update_status("idle")

        assert app._status_item.label == "idle (screen inactive)"

    def test_update_status_stopped_sets_attention(self):
        app = _make_app()
        app._build_menu()

        app._update_status("stopped")

        assert app._status_item.label == "not running"
        assert app.sni._status == "NeedsAttention"

    def test_update_status_recording_uses_error_icon_when_error_set(self):
        app = _make_app()
        app._build_menu()
        app._update_status("paused")
        app.error = "Auth failed"

        app._update_status("recording")

        assert app.sni._icon_name == ICONS["error"]


class TestUpdateSync:
    def test_update_sync_synced(self):
        app = _make_app()
        app._build_menu()

        app._update_sync("synced", "")

        assert app._sync_item.label == "sync: up to date"

    def test_update_sync_syncing(self):
        app = _make_app()
        app._build_menu()

        app._update_sync("syncing", "3/10 segments")

        assert app._sync_item.label == "sync: 3/10 segments"

    def test_update_sync_offline(self):
        app = _make_app()
        app._build_menu()

        app._update_sync("offline", "")

        assert app._sync_item.label == "sync: offline"


class TestUpdateLiveStats:
    def test_update_live_stats_updates_labels(self):
        app = _make_app()
        app._build_menu()
        app.stats = {
            "captures_today": 5,
            "total_size_mb": 42,
            "synced_days": 7,
            "uptime_seconds": 7260,
        }

        app._update_live_stats(245, 0)

        assert app._segment_item.label == "segment: 4:05 remaining"
        assert app._cache_item.label == "cache: 42 MB (7 days synced)"
        assert app._captures_item.label == "captures today: 5 segments"
        assert app._uptime_item.label == "uptime: 2h 1m"


class TestBuildTooltip:
    def test_build_tooltip_default(self):
        app = _make_app()

        tooltip = app._build_tooltip()

        assert "<b>observing</b>" in tooltip
        assert "all segments synced" in tooltip

    def test_build_tooltip_stopped(self):
        app = _make_app()
        app.status = "stopped"

        tooltip = app._build_tooltip()

        assert "not running" in tooltip

    def test_build_tooltip_error(self):
        app = _make_app()
        app.error = "Auth failed"

        tooltip = app._build_tooltip()

        assert "Auth failed" in tooltip

    def test_build_tooltip_sync_progress(self):
        app = _make_app()
        app.sync_status = "syncing"
        app.sync_progress = "2/5"

        tooltip = app._build_tooltip()

        assert "sync: 2/5" in tooltip


class TestUpdate:
    def test_update_reads_observer_state(self):
        app = _make_app()
        app._build_menu()
        app._observer.current_mode = "screencast"
        app._observer._paused = False
        app._observer.segment_dir = Path("/tmp/test.incomplete")
        app._observer.start_at_mono = time.monotonic() - 60
        app._observer.interval = 300

        app.update()

        assert app.status == "recording"
        assert app._segment_item.label.startswith(("segment: 4:", "segment: 3:"))

    def test_update_shows_paused(self):
        app = _make_app()
        app._build_menu()
        app._observer._paused = True
        app._observer._pause_until = time.monotonic() + 600

        app.update()

        assert app.status == "paused"
        assert app._resume_item.visible is True


class TestConfigIntegration:
    def test_config_paths_use_base_dir(self, tmp_path):
        app = _make_app(tmp_path)

        assert str(app.config.captures_dir).startswith(str(tmp_path))
        assert str(app.config.config_path).startswith(str(tmp_path))

    def test_agent_instructions_template_uses_config_values(self, tmp_path):
        app = _make_app(tmp_path)

        text = AGENT_INSTRUCTIONS.format(
            source_dir=SOURCE_DIR,
            config_path=str(app.config.config_path),
            captures_dir=str(app.config.captures_dir),
        )

        assert SOURCE_DIR in text
        assert str(app.config.config_path) in text
        assert str(app.config.captures_dir) in text
