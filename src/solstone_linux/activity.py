# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Activity detection using DBus APIs.

Extracted from solstone's observe/gnome/activity.py. The DBus services
probed here are GNOME-specific; on other desktops (KDE, etc.) they may
not be available. Every function degrades gracefully — returning a safe
default — so the observer keeps running regardless of desktop environment.

Changes from monorepo version:
- Replaces `from observe.utils import assign_monitor_positions` with local module
"""

import logging
import os

from dbus_next.aio import MessageBus

logger = logging.getLogger(__name__)

# GTK4/GDK4 — optional, only needed for monitor geometry detection.
# On systems without GTK4, get_monitor_geometries() will raise RuntimeError
# but screencast recording still works (monitors labeled as "monitor-N").
try:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    _HAS_GTK = True
except (ImportError, ValueError):
    _HAS_GTK = False

# DBus service constants
IDLE_MONITOR_BUS = "org.gnome.Mutter.IdleMonitor"
IDLE_MONITOR_PATH = "/org/gnome/Mutter/IdleMonitor/Core"
IDLE_MONITOR_IFACE = "org.gnome.Mutter.IdleMonitor"

SCREENSAVER_BUS = "org.gnome.ScreenSaver"
SCREENSAVER_PATH = "/org/gnome/ScreenSaver"
SCREENSAVER_IFACE = "org.gnome.ScreenSaver"

DISPLAY_CONFIG_BUS = "org.gnome.Mutter.DisplayConfig"
DISPLAY_CONFIG_PATH = "/org/gnome/Mutter/DisplayConfig"
DISPLAY_CONFIG_IFACE = "org.gnome.Mutter.DisplayConfig"


async def probe_activity_services(bus: MessageBus) -> dict[str, bool]:
    """Check which activity DBus services are reachable.

    Returns a dict of service name -> available. Used for startup logging
    only — the observer runs regardless of what's available.
    """
    services = {
        "idle_monitor": IDLE_MONITOR_BUS,
        "screensaver": SCREENSAVER_BUS,
        "display_config": DISPLAY_CONFIG_BUS,
    }
    results = {}
    for name, bus_name in services.items():
        try:
            await bus.introspect(bus_name, "/")
            results[name] = True
        except Exception:
            results[name] = False

    available = [k for k, v in results.items() if v]
    missing = [k for k, v in results.items() if not v]
    if missing:
        logger.warning(
            "Activity signals unavailable: %s — observer will assume active",
            ", ".join(missing),
        )
    if available:
        logger.info("Activity signals available: %s", ", ".join(available))
    if not available:
        logger.warning(
            "No activity signals available (non-GNOME desktop?) "
            "— running in always-capture mode"
        )

    results["gtk4"] = _HAS_GTK
    if not _HAS_GTK:
        logger.warning("GTK4 not available — monitor geometry labels will be missing")

    return results


async def get_idle_time_ms(bus: MessageBus) -> int:
    """
    Get the current idle time in milliseconds.

    Args:
        bus: Connected DBus session bus

    Returns:
        Idle time in milliseconds, or 0 if the service is unavailable
        (0 = assume active, so the observer keeps capturing).
    """
    try:
        introspection = await bus.introspect(IDLE_MONITOR_BUS, IDLE_MONITOR_PATH)
        proxy_obj = bus.get_proxy_object(
            IDLE_MONITOR_BUS, IDLE_MONITOR_PATH, introspection
        )
        idle_monitor = proxy_obj.get_interface(IDLE_MONITOR_IFACE)
        idle_time = await idle_monitor.call_get_idletime()
        return idle_time
    except Exception:
        return 0


async def is_screen_locked(bus: MessageBus) -> bool:
    """
    Check if the screen is currently locked using GNOME ScreenSaver.

    Args:
        bus: Connected DBus session bus

    Returns:
        True if screen is locked, False otherwise
    """
    try:
        intro = await bus.introspect(SCREENSAVER_BUS, SCREENSAVER_PATH)
        obj = bus.get_proxy_object(SCREENSAVER_BUS, SCREENSAVER_PATH, intro)
        iface = obj.get_interface(SCREENSAVER_IFACE)
        return bool(await iface.call_get_active())
    except Exception:
        return False


async def is_power_save_active(bus: MessageBus) -> bool:
    """
    Check if display power save mode is active (screen blanked).

    Args:
        bus: Connected DBus session bus

    Returns:
        True if power save is active, False otherwise
    """
    try:
        intro = await bus.introspect(DISPLAY_CONFIG_BUS, DISPLAY_CONFIG_PATH)
        obj = bus.get_proxy_object(DISPLAY_CONFIG_BUS, DISPLAY_CONFIG_PATH, intro)
        iface = obj.get_interface("org.freedesktop.DBus.Properties")
        mode_variant = await iface.call_get(DISPLAY_CONFIG_IFACE, "PowerSaveMode")
        mode = int(mode_variant.value)
        return mode != 0
    except Exception:
        return False


def get_monitor_geometries() -> list[dict]:
    """
    Get structured monitor information.

    Returns:
        List of dicts with format:
        [{"id": "connector-id", "box": [x1, y1, x2, y2], "position": "center|left|right|..."}, ...]
        where box contains [left, top, right, bottom] coordinates

    Raises:
        RuntimeError: If GTK4/GDK4 is not available.
    """
    if not _HAS_GTK:
        raise RuntimeError("GTK4 not available for monitor geometry detection")

    from .monitor_positions import assign_monitor_positions

    # Initialize GTK before using GDK functions
    Gtk.init()

    # Get the default display. If it is None, try opening one from the environment.
    display = Gdk.Display.get_default()
    if display is None:
        env_display = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")
        if env_display is not None:
            display = Gdk.Display.open(env_display)
        if display is None:
            raise RuntimeError("No display available")
    monitors = display.get_monitors()

    # Collect monitor geometries
    geometries = []
    for monitor in monitors:
        geom = monitor.get_geometry()
        connector = monitor.get_connector() or f"monitor-{len(geometries)}"
        geometries.append(
            {
                "id": connector,
                "box": [geom.x, geom.y, geom.x + geom.width, geom.y + geom.height],
            }
        )

    # Assign position labels using shared algorithm
    return assign_monitor_positions(geometries)
