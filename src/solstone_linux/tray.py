# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc
"""solstone tray app — in-process D-Bus SNI component.

Exports the tray icon, menu, and tooltip on the observer's existing
session bus connection. No separate tray process is required.
"""

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime

from dbus_next.aio import MessageBus

from . import __version__
from .dbusmenu import DBusMenu, MenuItem, separator
from .sni import StatusNotifierItem, register_with_watcher

log = logging.getLogger(__name__)

# Icon names — these reference SVGs in our icon theme
ICONS = {
    "recording": "solstone-recording",
    "paused": "solstone-paused",
    "idle": "solstone-paused",
    "stopped": "solstone-error",
    "syncing": "solstone-syncing",
    "error": "solstone-error",
}

# Agent instructions template copied to clipboard
AGENT_INSTRUCTIONS = """solstone observer (Linux)
Source: {source_dir}
Read INSTALL.md in the source directory for setup and architecture.
Config: {config_path}
Captures: {captures_dir}
Logs: journalctl --user -u solstone-linux -f
Service: systemctl --user status solstone-linux"""

SOURCE_DIR = str(Path(__file__).resolve().parent)


def _compute_header_label(status, sync_status, pause_remaining) -> str:
    if status == "paused":
        if pause_remaining and pause_remaining > 0:
            mins = pause_remaining // 60
            return f"paused ({mins}m remaining)"
        return "paused"
    if status == "stopped":
        return "not running"
    if status == "recording":
        if sync_status == "offline":
            return "observing — offline (recording locally)"
        if sync_status in ("syncing", "uploading", "retrying"):
            return "observing — syncing"
        return "observing — connected"
    if status == "idle":
        if sync_status == "offline":
            return "idle — offline"
        if sync_status in ("syncing", "uploading", "retrying"):
            return "idle — syncing"
        return "idle — connected"
    return str(status)


class TrayApp:
    """In-process tray component — exports SNI on the observer's bus."""

    def __init__(self, observer, bus):
        self._observer = observer
        self.config = observer.config
        self.bus: MessageBus = bus
        self.sni = StatusNotifierItem("solstone-observer")
        self.menu = DBusMenu()

        # State cache (for change detection)
        self.status = "recording"
        self.sync_status = "synced"
        self.sync_progress = ""
        self.error = ""
        self.paused_remaining = 0
        self.stats = {}
        self._last_stats_time = 0.0

        # Menu item references for dynamic updates
        self._status_header: MenuItem = None
        self._status_item: MenuItem = None
        self._sync_item: MenuItem = None
        self._segment_item: MenuItem = None
        self._cache_item: MenuItem = None
        self._captures_item: MenuItem = None
        self._uptime_item: MenuItem = None
        self._pause_submenu: MenuItem = None
        self._resume_item: MenuItem = None

    async def start(self):
        pid = os.getpid()
        bus_name = f"org.kde.StatusNotifierItem-{pid}-1"
        await self.bus.request_name(bus_name)

        # Export interfaces
        self.bus.export("/StatusNotifierItem", self.sni)
        self.bus.export("/MenuBar", self.menu)

        # Resolve icon theme: installed location, then dev/contrib fallback
        installed_icon = (
            Path.home()
            / ".local/share/icons/hicolor/scalable/status/solstone-recording.svg"
        )
        if installed_icon.exists():
            self.sni._icon_theme_path = str(Path.home() / ".local/share/icons")
        else:
            contrib = (
                Path(__file__).resolve().parent.parent.parent / "contrib" / "icons"
            )
            if (contrib / "hicolor").is_dir():
                self.sni._icon_theme_path = str(contrib)
        if self.sni._icon_theme_path:
            log.info(f"Icon theme path: {self.sni._icon_theme_path}")

        # Set initial icon
        self.sni.set_icon(ICONS["recording"])
        self._update_accessible_descriptions()
        self.sni.set_tooltip("solstone observer", "starting...")

        # Build menu
        self._build_menu()

        # Register with watcher (3 attempts)
        registered = False
        for attempt in range(3):
            registered = await register_with_watcher(self.bus, bus_name)
            if registered:
                break
            if attempt < 2:
                await asyncio.sleep(1)
                log.info(f"SNI watcher retry {attempt + 1}/2...")

        if not registered:
            log.info("No StatusNotifierWatcher available")
            return False

        return True

    def update(self):
        """Read observer state and update tray display."""
        obs = self._observer

        # Determine status
        if obs._paused:
            status = "paused"
        elif obs.current_mode == "screencast":
            status = "recording"
        else:
            status = "idle"

        # Sync status
        sync_status = "synced"
        sync_progress = ""
        if obs._sync:
            sync_status = obs._sync.sync_status
            sync_progress = obs._sync.sync_progress

        # Segment timer
        if obs._paused or obs.segment_dir is None:
            segment_timer = 0
        else:
            remaining = obs.interval - (time.monotonic() - obs.start_at_mono)
            segment_timer = max(0, int(remaining))

        # Pause remaining
        if not obs._paused or obs._pause_until <= 0:
            pause_remaining = 0
        else:
            pause_remaining = max(0, int(obs._pause_until - time.monotonic()))

        # Compute stats (throttled — filesystem walk every 60s)
        now = time.monotonic()
        if now - self._last_stats_time >= 60:
            self._last_stats_time = now
            captures_today = 0
            total_size = 0
            today = datetime.now().strftime("%Y%m%d")
            captures_dir = obs.config.captures_dir

            try:
                if captures_dir.exists():
                    for day_dir in captures_dir.iterdir():
                        if not day_dir.is_dir():
                            continue
                        for stream_dir in day_dir.iterdir():
                            if not stream_dir.is_dir():
                                continue
                            for seg_dir in stream_dir.iterdir():
                                if not seg_dir.is_dir():
                                    continue
                                if seg_dir.name.endswith(".incomplete"):
                                    continue
                                if seg_dir.name.endswith(".failed"):
                                    continue
                                if day_dir.name == today:
                                    captures_today += 1
                                for file_path in seg_dir.iterdir():
                                    if file_path.is_file():
                                        total_size += file_path.stat().st_size
            except OSError:
                pass

            synced_days = 0
            if obs._sync:
                synced_days = len(obs._sync._synced_days)

            total_size_mb = int(total_size / (1024 * 1024))
            uptime_seconds = int(time.monotonic() - obs._start_mono)

            self.stats = {
                "captures_today": captures_today,
                "total_size_mb": total_size_mb,
                "synced_days": synced_days,
                "uptime_seconds": uptime_seconds,
            }

        self._update_status(status)
        self._update_sync(sync_status, sync_progress)
        self._update_header(pause_remaining)
        self._update_live_stats(segment_timer, pause_remaining)
        self.paused_remaining = pause_remaining

    def _build_menu(self):
        """Build the full tray menu structure."""

        self._status_header = MenuItem(label="observing", enabled=False)

        # ── Status submenu (live data) ──
        self._status_item = MenuItem(label="observing", enabled=False)
        self._sync_item = MenuItem(label="sync: up to date", enabled=False)
        self._segment_item = MenuItem(label="segment: --:--", enabled=False)
        self._cache_item = MenuItem(label="cache: --", enabled=False)
        self._captures_item = MenuItem(label="captures today: --", enabled=False)
        self._uptime_item = MenuItem(label="uptime: --", enabled=False)

        status_submenu = MenuItem(
            label="status",
            children_display="submenu",
        )
        status_submenu.children = [
            self._status_item,
            self._sync_item,
            separator(),
            self._segment_item,
            self._cache_item,
            self._captures_item,
            self._uptime_item,
        ]

        # ── Pause / Resume ──
        pause_15m = MenuItem(label="15 minutes", callback=lambda: self._pause(900))
        pause_30m = MenuItem(label="30 minutes", callback=lambda: self._pause(1800))
        pause_1h = MenuItem(label="1 hour", callback=lambda: self._pause(3600))
        pause_indef = MenuItem(label="until I resume", callback=lambda: self._pause(0))

        self._pause_submenu = MenuItem(
            label="pause",
            children_display="submenu",
        )
        self._pause_submenu.children = [pause_15m, pause_30m, pause_1h, pause_indef]

        self._resume_item = MenuItem(
            label="resume",
            visible=False,
            callback=self._resume,
        )

        # ── Open journal / Show captures ──
        open_journal = MenuItem(
            label="open journal",
            callback=self._open_journal,
        )

        # ── Settings submenu ──
        settings_open_config = MenuItem(
            label="open config.json",
            callback=self._open_config,
        )
        settings_submenu = MenuItem(
            label="settings",
            children_display="submenu",
        )
        settings_submenu.children = [
            settings_open_config,
        ]

        # ── About submenu ──
        about_version = MenuItem(
            label=f"solstone observer v{__version__}",
            enabled=False,
        )
        about_website = MenuItem(
            label="solstone.app",
            callback=lambda: self._open_url("https://solstone.app/observers"),
        )
        about_source = MenuItem(
            label="source code",
            callback=lambda: self._open_url("https://github.com/solpbc/solstone-linux"),
        )
        about_privacy = MenuItem(
            label="privacy policy",
            callback=lambda: self._open_url("https://solpbc.org/privacy"),
        )
        about_copyright = MenuItem(
            label="\u00a9 2026 sol pbc \u2014 a public benefit corporation",
            enabled=False,
        )

        about_submenu = MenuItem(
            label="about",
            children_display="submenu",
        )
        about_copy_agent = MenuItem(
            label="copy help agent instructions",
            callback=self._copy_agent_instructions,
        )

        about_submenu.children = [
            about_version,
            about_website,
            about_source,
            about_privacy,
            about_copy_agent,
            separator(),
            about_copyright,
        ]

        # ── Service hint ──
        service_hint = MenuItem(
            label="managed via systemctl",
            enabled=False,
        )

        # ── Assemble full menu ──
        self.menu.set_menu(
            [
                self._status_header,
                separator(),
                self._pause_submenu,
                self._resume_item,
                separator(),
                status_submenu,
                open_journal,
                settings_submenu,
                about_submenu,
                separator(),
                service_hint,
            ]
        )

    def _update_status(self, status: str):
        """Update tray icon and menu for observer status."""
        if status == self.status:
            return
        self.status = status

        # Pick icon
        if self.error:
            icon = ICONS["error"]
        elif self.sync_status in ("syncing", "uploading", "retrying"):
            icon = ICONS["syncing"]
        else:
            icon = ICONS.get(status, ICONS["recording"])
        self.sni.set_icon(icon)

        # Update tooltip
        self.sni.set_tooltip("solstone observer", self._build_tooltip())

        # Toggle pause/resume
        is_paused = status == "paused"
        self._pause_submenu.visible = not is_paused
        self._resume_item.visible = is_paused
        if is_paused and self.paused_remaining > 0:
            mins = self.paused_remaining // 60
            self._resume_item.label = f"resume ({mins}m remaining)"
        else:
            self._resume_item.label = "resume"
        self.menu.update_properties(self._pause_submenu, "visible")
        self.menu.update_properties(self._resume_item, "visible", "label")

        # SNI status
        if status == "stopped" or self.error:
            self.sni.set_status("NeedsAttention")
        else:
            self.sni.set_status("Active")
        self._update_accessible_descriptions()

        log.info(f"Status -> {status} (icon: {icon})")

    def _update_header(self, pause_remaining: int):
        label = _compute_header_label(self.status, self.sync_status, pause_remaining)
        if label == self._status_header.label:
            return
        self._status_header.label = label
        self._status_item.label = label
        self.menu.update_properties(self._status_header, "label")

    def _update_sync(self, sync_status: str, progress: str):
        """Update sync status display."""
        if sync_status == self.sync_status and progress == self.sync_progress:
            return
        self.sync_status = sync_status
        self.sync_progress = progress

        labels = {
            "synced": "sync: up to date",
            "syncing": f"sync: {progress}" if progress else "sync: checking...",
            "uploading": f"sync: {progress}" if progress else "sync: uploading...",
            "retrying": f"sync: {progress}" if progress else "sync: retrying...",
            "offline": "sync: offline",
        }
        self._sync_item.label = labels.get(sync_status, f"sync: {sync_status}")

        # Update icon — syncing state gets the half icon
        if not self.error:
            if sync_status in ("syncing", "uploading", "retrying"):
                self.sni.set_icon(ICONS["syncing"])
            else:
                self.sni.set_icon(ICONS.get(self.status, ICONS["recording"]))

        self.sni.set_tooltip("solstone observer", self._build_tooltip())
        self._update_accessible_descriptions()

    def _update_live_stats(self, segment_timer: int, pause_remaining: int):
        """Update the live stats in the status submenu."""
        # Segment timer
        mins = segment_timer // 60
        secs = segment_timer % 60
        new_label = f"segment: {mins}:{secs:02d} remaining"
        if self._segment_item.label != new_label:
            self._segment_item.label = new_label

        # Stats (computed in update())
        if self.stats:
            captures = self.stats.get("captures_today", 0)
            size_mb = self.stats.get("total_size_mb", 0)
            synced_days = self.stats.get("synced_days", 0)
            uptime = self.stats.get("uptime_seconds", 0)

            new_cache = f"cache: {size_mb} MB ({synced_days} days synced)"
            new_captures = f"captures today: {captures} segments"

            hours = uptime // 3600
            mins_up = (uptime % 3600) // 60
            new_uptime = f"uptime: {hours}h {mins_up}m"

            if self._cache_item.label != new_cache:
                self._cache_item.label = new_cache
            if self._captures_item.label != new_captures:
                self._captures_item.label = new_captures
            if self._uptime_item.label != new_uptime:
                self._uptime_item.label = new_uptime

        # Update pause remaining in resume button
        if self.status == "paused" and pause_remaining > 0:
            pr_mins = pause_remaining // 60
            new_resume = f"resume ({pr_mins}m remaining)"
            if self._resume_item.label != new_resume:
                self._resume_item.label = new_resume

    def _build_tooltip(self) -> str:
        """Build plain-text tooltip body (cross-DE compatible)."""
        parts = []

        status_labels = {
            "recording": "observing",
            "paused": "paused",
            "idle": "idle (screen inactive)",
            "stopped": "not running",
        }
        parts.append(status_labels.get(self.status, self.status))

        if self.sync_status == "synced":
            parts.append("all segments synced")
        elif self.sync_progress:
            parts.append(f"sync: {self.sync_progress}")
        else:
            parts.append(f"sync: {self.sync_status}")

        if self.error:
            parts.append(self.error)

        return "\n".join(parts)

    def _update_accessible_descriptions(self):
        if self.error:
            desc = "Solstone observer — error"
        elif self.sync_status in ("syncing", "uploading", "retrying"):
            desc = "Solstone observer — syncing"
        elif self.status == "paused":
            desc = "Solstone observer — paused"
        elif self.status == "idle":
            desc = "Solstone observer — idle"
        elif self.status == "stopped":
            desc = "Solstone observer — stopped"
        else:
            desc = "Solstone observer — recording"
            if self.config.stream:
                desc = f"{desc} ({self.config.stream})"

        self.sni.set_icon_accessible_desc(desc)
        self.sni.set_attention_accessible_desc(desc)

    # ── Menu callbacks ──

    def _pause(self, seconds: int):
        log.info(f"Pause: {seconds}s")
        self._observer.pause(seconds)

    def _resume(self):
        log.info("Resume")
        self._observer.resume()

    def _open_journal(self):
        log.info("Opening journal")
        self._open_url(self.config.server_url or "https://journal.solstone.app")

    def _open_config(self):
        config_path = str(self.config.config_path)
        log.info(f"Opening config: {config_path}")
        try:
            subprocess.Popen(
                ["xdg-open", config_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.error(f"Failed to open config: {e}")

    def _copy_agent_instructions(self):
        """Copy coding agent instructions to clipboard."""
        text = AGENT_INSTRUCTIONS.format(
            source_dir=SOURCE_DIR,
            config_path=str(self.config.config_path),
            captures_dir=str(self.config.captures_dir),
        )
        log.info("Copying agent instructions to clipboard")
        try:
            # wl-copy for Wayland, xclip for X11
            session_type = os.environ.get("XDG_SESSION_TYPE", "")
            if session_type == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
                proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            else:
                proc = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE
                )
            proc.communicate(text.encode())
            log.info("Copied to clipboard")
        except FileNotFoundError:
            # Fallback: try xsel
            try:
                proc = subprocess.Popen(
                    ["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE
                )
                proc.communicate(text.encode())
                log.info("Copied to clipboard (xsel)")
            except FileNotFoundError:
                log.error("No clipboard tool found (wl-copy, xclip, or xsel)")

    def _open_url(self, url: str):
        log.info(f"Opening: {url}")
        try:
            subprocess.Popen(
                ["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            log.error(f"Failed to open URL: {e}")
