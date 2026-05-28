# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import time
from pathlib import Path
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from solstone_linux.config import Config
from solstone_linux.dbusmenu import MenuItem, separator
from solstone_linux.sni import StatusNotifierItem
from solstone_linux.tray import (
    AGENT_INSTRUCTIONS,
    ICONS,
    SOURCE_DIR,
    TrayApp,
    _compute_header_label,
    resolve_icon_theme_path,
)


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
    observer._start_mono = time.monotonic()
    observer._sync = None
    observer._dbus_service = None
    bus = MagicMock()
    app = TrayApp(observer, bus)
    return app


class TestResolveIconThemePath:
    def test_resolve_icon_theme_path_prefers_installed(self, tmp_path):
        installed_icon = (
            tmp_path
            / ".local/share/icons/hicolor/scalable/status/solstone-recording.svg"
        )
        installed_icon.parent.mkdir(parents=True)
        installed_icon.touch()

        with patch("solstone_linux.tray.Path.home", return_value=tmp_path):
            assert resolve_icon_theme_path() == str(tmp_path / ".local/share/icons")

    def test_resolve_icon_theme_path_contrib_fallback(self, tmp_path):
        with patch("solstone_linux.tray.Path.home", return_value=tmp_path):
            result = resolve_icon_theme_path()

        assert result.endswith("contrib/icons")
        assert (Path(result) / "hicolor").is_dir() is True


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
        assert app.menu._root.children[0] is app._status_header
        assert app.menu._root.children[1].item_type == separator().item_type
        assert len(app.menu._root.children) == 11


class TestUpdateStatus:
    def test_update_status_paused(self):
        app = _make_app()
        app._build_menu()
        app.menu.update_properties = MagicMock()

        app._update_status("paused")

        assert app.status == "paused"
        assert app._pause_submenu.visible is False
        assert app._resume_item.visible is True
        assert app.menu.update_properties.call_count >= 2
        assert (
            call(app._pause_submenu, "visible")
            in app.menu.update_properties.call_args_list
        )
        assert (
            call(app._resume_item, "visible", "label")
            in app.menu.update_properties.call_args_list
        )

    def test_update_status_idle(self):
        app = _make_app()
        app._build_menu()

        app._update_status("idle")

        assert app.status == "idle"

    def test_update_status_stopped_sets_attention(self):
        app = _make_app()
        app._build_menu()

        app._update_status("stopped")

        assert app.status == "stopped"
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

    def test_update_live_stats_skips_unchanged_menu_updates(self):
        app = _make_app()
        app._build_menu()
        app.menu.update_properties = MagicMock()
        app.stats = {
            "captures_today": 5,
            "total_size_mb": 42,
            "synced_days": 7,
            "uptime_seconds": 7260,
        }

        app._update_live_stats(245, 0)
        app.menu.update_properties.reset_mock()

        app._update_live_stats(245, 0)

        app.menu.update_properties.assert_not_called()


class TestHeaderLabel:
    def test_update_header_emits_label_property_update(self):
        app = _make_app()
        app._build_menu()
        app.menu.update_properties = MagicMock()
        app.sync_status = "offline"

        app._update_header(0)
        app.menu.update_properties.reset_mock()

        app.sync_status = "synced"
        app._update_header(0)

        app.menu.update_properties.assert_called_with(app._status_header, "label")
        assert app._status_header.label == "observing — connected"

    def test_header_recording_synced(self):
        app = _make_app()
        app._build_menu()

        app.update()

        assert app._status_header.label == "observing — connected"
        assert app._status_item.label == "observing — connected"

    def test_header_paused_with_timer(self):
        app = _make_app()
        app._build_menu()
        app._observer._paused = True
        app._observer._pause_until = 1000.0

        with patch("solstone_linux.tray.time.monotonic", return_value=100.0):
            app.update()

        assert app._status_header.label == "paused (15m remaining)"
        assert app._status_item.label == "paused (15m remaining)"

    def test_header_recording_offline(self):
        app = _make_app()
        app._build_menu()
        app._observer._sync = MagicMock()
        app._observer._sync.sync_status = "offline"
        app._observer._sync.sync_progress = ""

        app.update()

        assert app._status_header.label == "observing — offline (recording locally)"
        assert app._status_item.label == "observing — offline (recording locally)"


class TestComputeHeaderLabel:
    @pytest.mark.parametrize(
        "status,sync_status,pause_remaining,expected",
        [
            ("recording", "synced", 0, "observing — connected"),
            ("recording", "syncing", 0, "observing — syncing"),
            ("recording", "uploading", 0, "observing — syncing"),
            ("recording", "retrying", 0, "observing — syncing"),
            ("recording", "offline", 0, "observing — offline (recording locally)"),
            ("idle", "synced", 0, "idle — connected"),
            ("idle", "syncing", 0, "idle — syncing"),
            ("idle", "uploading", 0, "idle — syncing"),
            ("idle", "retrying", 0, "idle — syncing"),
            ("idle", "offline", 0, "idle — offline"),
            ("paused", "synced", 0, "paused"),
            ("paused", "synced", 900, "paused (15m remaining)"),
            ("paused", "offline", 59, "paused (0m remaining)"),
            ("stopped", "synced", 0, "not running"),
            ("weird", "synced", 0, "weird"),
        ],
    )
    def test_compute_header_label(self, status, sync_status, pause_remaining, expected):
        assert _compute_header_label(status, sync_status, pause_remaining) == expected


class TestBuildTooltip:
    def test_build_tooltip_default(self):
        app = _make_app()

        tooltip = app._build_tooltip()

        assert "observing" in tooltip
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


class TestStatusNotifierItem:
    def test_accessible_desc_properties(self):
        sni = StatusNotifierItem()

        sni.set_icon_accessible_desc("Solstone observer — recording")
        sni.set_attention_accessible_desc("Solstone observer — recording")

        assert sni.IconAccessibleDesc == "Solstone observer — recording"
        assert sni.AttentionAccessibleDesc == "Solstone observer — recording"


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
