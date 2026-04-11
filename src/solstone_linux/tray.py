# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc
"""solstone tray app — pure D-Bus SNI implementation.

Connects to the observer backend over D-Bus and displays a system
tray icon with status, menus, and tooltip. No GUI toolkit dependency.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from dbus_next.aio import MessageBus

from .config import load_config
from .dbusmenu import DBusMenu, MenuItem, separator
from .sni import StatusNotifierItem, register_with_watcher

log = logging.getLogger(__name__)

BACKEND_BUS = "org.solpbc.solstone.Observer1"
BACKEND_PATH = "/org/solpbc/solstone/Observer1"

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


class TrayApp:
    """Main tray application coordinating SNI, menu, and backend."""

    def __init__(self):
        self.config = load_config()
        self.bus: MessageBus = None
        self.sni = StatusNotifierItem("solstone-observer")
        self.menu = DBusMenu()
        self.backend = None
        self.backend_props = None

        # State cache
        self.status = "recording"
        self.sync_status = "synced"
        self.sync_progress = ""
        self.error = ""
        self.paused_remaining = 0
        self.stats = {}

        # Menu item references for dynamic updates
        self._status_item: MenuItem = None
        self._sync_item: MenuItem = None
        self._segment_item: MenuItem = None
        self._cache_item: MenuItem = None
        self._captures_item: MenuItem = None
        self._uptime_item: MenuItem = None
        self._pause_submenu: MenuItem = None
        self._resume_item: MenuItem = None

    async def start(self):
        self.bus = await MessageBus().connect()

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
        self.sni.set_tooltip("solstone observer", "starting...")

        # Build menu
        self._build_menu()

        # Register with watcher (with retries)
        registered = False
        for attempt in range(6):
            registered = await register_with_watcher(self.bus, bus_name)
            if registered:
                break
            if attempt < 5:
                await asyncio.sleep(2)
                log.info(f"Retry {attempt + 1}/5...")

        if not registered:
            log.error("Could not register with StatusNotifierWatcher.")
            return False

        # Connect to backend
        await self._connect_backend()

        # Start background tasks
        asyncio.create_task(self._poll_backend())

        return True

    def _build_menu(self):
        """Build the full tray menu structure."""

        # ── Status submenu (live data) ──
        self._status_item = MenuItem(label="recording", enabled=False)
        self._sync_item = MenuItem(label="sync: up to date", enabled=False)
        self._segment_item = MenuItem(label="segment: --:--", enabled=False)
        self._cache_item = MenuItem(label="cache: --", enabled=False)
        self._captures_item = MenuItem(label="captures today: --", enabled=False)
        self._uptime_item = MenuItem(label="uptime: --", enabled=False)

        status_submenu = MenuItem(
            label="Status",
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
        pause_indef = MenuItem(label="Until I resume", callback=lambda: self._pause(0))

        self._pause_submenu = MenuItem(
            label="Pause",
            children_display="submenu",
        )
        self._pause_submenu.children = [pause_15m, pause_30m, pause_1h, pause_indef]

        self._resume_item = MenuItem(
            label="Resume",
            visible=False,
            callback=self._resume,
        )

        # ── Open journal / Show captures ──
        open_journal = MenuItem(
            label="Open journal",
            callback=self._open_journal,
        )

        open_captures = MenuItem(
            label="Show captures",
            callback=self._open_captures,
        )

        # ── Settings submenu ──
        settings_open_config = MenuItem(
            label="Open config.json",
            callback=self._open_config,
        )
        settings_copy_agent = MenuItem(
            label="Copy coding agent instructions",
            callback=self._copy_agent_instructions,
        )

        settings_submenu = MenuItem(
            label="Settings",
            children_display="submenu",
        )
        settings_submenu.children = [
            settings_open_config,
            settings_copy_agent,
        ]

        # ── About submenu ──
        about_observers = MenuItem(
            label="solstone.app/observers",
            callback=lambda: self._open_url("https://solstone.app/observers"),
        )
        about_privacy = MenuItem(
            label="Privacy policy",
            callback=lambda: self._open_url("https://solpbc.org/privacy"),
        )
        about_copyright = MenuItem(
            label="\u00a9 sol pbc",
            enabled=False,
        )

        about_submenu = MenuItem(
            label="About",
            children_display="submenu",
        )
        about_submenu.children = [
            about_observers,
            about_privacy,
            separator(),
            about_copyright,
        ]

        # ── Quit ──
        quit_item = MenuItem(
            label="Quit solstone observer",
            callback=self._quit,
        )

        # ── Assemble full menu ──
        self.menu.set_menu(
            [
                status_submenu,
                separator(),
                self._pause_submenu,
                self._resume_item,
                separator(),
                open_journal,
                open_captures,
                separator(),
                settings_submenu,
                about_submenu,
                separator(),
                quit_item,
            ]
        )

    async def _connect_backend(self):
        """Connect to the observer's D-Bus interface."""
        try:
            introspection = await self.bus.introspect(BACKEND_BUS, BACKEND_PATH)
            proxy = self.bus.get_proxy_object(BACKEND_BUS, BACKEND_PATH, introspection)
            self.backend = proxy.get_interface("org.solpbc.solstone.Observer1")
            self.backend_props = proxy.get_interface("org.freedesktop.DBus.Properties")

            # Subscribe to signals
            self.backend.on_status_changed(self._on_status_changed)
            self.backend.on_sync_progress_changed(self._on_sync_progress_changed)
            self.backend.on_error_occurred(self._on_error_occurred)

            log.info("Connected to observer backend")
        except Exception as e:
            log.warning(f"Backend not available: {e}")
            self._update_status("stopped")

    async def _poll_backend(self):
        """Poll backend for state updates every 5 seconds."""
        while True:
            await asyncio.sleep(5)
            try:
                if self.backend is None:
                    await self._connect_backend()
                    continue

                status = await self.backend.get_status()
                sync_status = await self.backend.get_sync_status()
                sync_progress = await self.backend.get_sync_progress()
                error = await self.backend.get_error()
                pause_remaining = await self.backend.get_pause_remaining()
                segment_timer = await self.backend.get_segment_timer()

                # Get stats
                try:
                    stats = await self.backend.call_get_stats()
                    self.stats = {k: v.value for k, v in stats.items()}
                except Exception:
                    pass

                self._update_status(status)
                self._update_sync(sync_status, sync_progress)
                self._update_live_stats(segment_timer, pause_remaining)
                self.paused_remaining = pause_remaining

                if error and error != self.error:
                    self.error = error
                    log.info(f"Error: {error}")
                elif not error and self.error:
                    self.error = ""
                    log.info("Error cleared")

            except Exception as e:
                log.warning(f"Poll failed: {e}")
                self.backend = None
                self.backend_props = None
                self._update_status("stopped")

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

        # Update status submenu item
        labels = {
            "recording": "recording",
            "paused": "paused",
            "idle": "idle (screen inactive)",
            "stopped": "not running",
        }
        self._status_item.label = labels.get(status, status)
        self.menu.update_item(self._status_item)

        # Toggle pause/resume
        is_paused = status == "paused"
        self._pause_submenu.visible = not is_paused
        self._resume_item.visible = is_paused
        if is_paused and self.paused_remaining > 0:
            mins = self.paused_remaining // 60
            self._resume_item.label = f"Resume ({mins}m remaining)"
        else:
            self._resume_item.label = "Resume"
        self.menu.update_item(self._pause_submenu)
        self.menu.update_item(self._resume_item)

        # SNI status
        if status == "stopped" or self.error:
            self.sni.set_status("NeedsAttention")
        else:
            self.sni.set_status("Active")

        log.info(f"Status \u2192 {status} (icon: {icon})")

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
        self.menu.update_item(self._sync_item)

        # Update icon — syncing state gets the half icon
        if not self.error:
            if sync_status in ("syncing", "uploading", "retrying"):
                self.sni.set_icon(ICONS["syncing"])
            else:
                self.sni.set_icon(ICONS.get(self.status, ICONS["recording"]))

        self.sni.set_tooltip("solstone observer", self._build_tooltip())

    def _update_live_stats(self, segment_timer: int, pause_remaining: int):
        """Update the live stats in the status submenu."""
        # Segment timer
        mins = segment_timer // 60
        secs = segment_timer % 60
        self._segment_item.label = f"segment: {mins}:{secs:02d} remaining"
        self.menu.update_item(self._segment_item)

        # Stats from GetStats
        if self.stats:
            captures = self.stats.get("captures_today", 0)
            size_mb = self.stats.get("total_size_mb", 0)
            synced_days = self.stats.get("synced_days", 0)
            uptime = self.stats.get("uptime_seconds", 0)

            self._cache_item.label = f"cache: {size_mb} MB ({synced_days} days synced)"
            self._captures_item.label = f"captures today: {captures} segments"

            hours = uptime // 3600
            mins_up = (uptime % 3600) // 60
            self._uptime_item.label = f"uptime: {hours}h {mins_up}m"

            self.menu.update_item(self._cache_item)
            self.menu.update_item(self._captures_item)
            self.menu.update_item(self._uptime_item)

        # Update pause remaining in resume button
        if self.status == "paused" and pause_remaining > 0:
            pr_mins = pause_remaining // 60
            self._resume_item.label = f"Resume ({pr_mins}m remaining)"
            self.menu.update_item(self._resume_item)

    def _build_tooltip(self) -> str:
        """Build rich tooltip body (HTML on KDE)."""
        parts = []

        status_html = {
            "recording": "<b>Recording</b>",
            "paused": "<b>Paused</b>",
            "idle": "Idle (screen inactive)",
            "stopped": "<font color='#cc3333'>Not running</font>",
        }
        parts.append(status_html.get(self.status, self.status))

        if self.sync_status == "synced":
            parts.append("All segments synced")
        elif self.sync_progress:
            parts.append(f"Sync: {self.sync_progress}")
        else:
            parts.append(f"Sync: {self.sync_status}")

        if self.error:
            parts.append(f"<font color='#cc3333'>{self.error}</font>")

        return "<br>".join(parts)

    # ── Signal handlers ──

    def _on_status_changed(self, status: str):
        self._update_status(status)

    def _on_sync_progress_changed(self, progress: str):
        if ":" in progress:
            sync_status, sync_progress = progress.split(":", 1)
            self._update_sync(sync_status, sync_progress)

    def _on_error_occurred(self, message: str):
        self.error = message
        if message:
            self.sni.set_status("NeedsAttention")
            self.sni.set_icon(ICONS["error"])
        else:
            self.sni.set_status("Active")
            self._update_status(self.status)

    # ── Menu callbacks ──

    def _pause(self, seconds: int):
        log.info(f"Pause: {seconds}s")
        if self.backend:
            asyncio.create_task(self._do_pause(seconds))

    async def _do_pause(self, seconds: int):
        try:
            await self.backend.call_pause(seconds)
        except Exception as e:
            log.error(f"Pause failed: {e}")

    def _resume(self):
        log.info("Resume")
        if self.backend:
            asyncio.create_task(self._do_resume())

    async def _do_resume(self):
        try:
            await self.backend.call_resume()
        except Exception as e:
            log.error(f"Resume failed: {e}")

    def _open_journal(self):
        log.info("Opening journal")
        self._open_url(self.config.server_url or "https://journal.solstone.app")

    def _open_captures(self):
        capture_dir = str(self.config.captures_dir)
        log.info(f"Opening captures: {capture_dir}")
        try:
            subprocess.Popen(
                ["xdg-open", capture_dir],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.error(f"Failed to open file manager: {e}")

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
            # Fallback: try xdg-open or xsel
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

    def _quit(self):
        log.info("Quit requested")
        asyncio.get_event_loop().stop()

    async def stop(self):
        if self.bus:
            self.bus.disconnect()


async def _async_main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = TrayApp()

    loop = asyncio.get_event_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, None)

    started = await app.start()
    if not started:
        sys.exit(1)

    log.info("Tray app running. Ctrl+C to stop.")
    await stop
    await app.stop()
    log.info("Stopped.")


def main():
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
