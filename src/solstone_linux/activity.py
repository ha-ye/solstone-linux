# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Activity detection using DBus APIs.

Detects screen lock and power save state across GNOME and KDE desktops
using freedesktop, GNOME, and KDE DBus interfaces with ordered fallback
chains. Every function degrades gracefully — returning a safe default —
so the observer keeps running regardless of desktop environment.
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
FDO_SCREENSAVER_BUS = "org.freedesktop.ScreenSaver"
FDO_SCREENSAVER_PATH = "/ScreenSaver"
FDO_SCREENSAVER_IFACE = "org.freedesktop.ScreenSaver"

GNOME_SCREENSAVER_BUS = "org.gnome.ScreenSaver"
GNOME_SCREENSAVER_PATH = "/org/gnome/ScreenSaver"
GNOME_SCREENSAVER_IFACE = "org.gnome.ScreenSaver"

DISPLAY_CONFIG_BUS = "org.gnome.Mutter.DisplayConfig"
DISPLAY_CONFIG_PATH = "/org/gnome/Mutter/DisplayConfig"
DISPLAY_CONFIG_IFACE = "org.gnome.Mutter.DisplayConfig"

KDE_POWER_BUS = "org.kde.Solid.PowerManagement"
KDE_POWER_PATH = "/org/kde/Solid/PowerManagement"
KDE_POWER_IFACE = "org.kde.Solid.PowerManagement"


async def probe_activity_services(bus: MessageBus) -> dict[str, bool]:
    """Check which activity DBus services are reachable."""
    services = {
        "fdo_screensaver": FDO_SCREENSAVER_BUS,
        "gnome_screensaver": GNOME_SCREENSAVER_BUS,
        "gnome_display_config": DISPLAY_CONFIG_BUS,
        "kde_power": KDE_POWER_BUS,
    }
    results = {}
    for name, bus_name in services.items():
        try:
            await bus.introspect(bus_name, "/")
            results[name] = True
        except Exception:
            results[name] = False

    lock_backends = ["fdo_screensaver", "gnome_screensaver"]
    power_backends = ["gnome_display_config", "kde_power"]

    lock_available = [name for name in lock_backends if results.get(name)]
    power_available = [name for name in power_backends if results.get(name)]

    if lock_available:
        logger.info("Screen lock backends: %s", ", ".join(lock_available))
    else:
        logger.warning("No screen lock backends available — will assume unlocked")

    if power_available:
        logger.info("Power save backends: %s", ", ".join(power_available))
    else:
        logger.warning("No power save backends available — will assume active display")

    results["gtk4"] = _HAS_GTK
    if not _HAS_GTK:
        logger.warning("GTK4 not available — monitor geometry labels will be missing")

    return results


async def is_screen_locked(bus: MessageBus) -> bool:
    """Check if the screen is currently locked.

    Tries freedesktop.ScreenSaver first (works on KDE, GNOME, and others),
    then falls back to GNOME ScreenSaver.
    """
    try:
        intro = await bus.introspect(FDO_SCREENSAVER_BUS, FDO_SCREENSAVER_PATH)
        obj = bus.get_proxy_object(FDO_SCREENSAVER_BUS, FDO_SCREENSAVER_PATH, intro)
        iface = obj.get_interface(FDO_SCREENSAVER_IFACE)
        return bool(await iface.call_get_active())
    except Exception:
        pass

    try:
        intro = await bus.introspect(GNOME_SCREENSAVER_BUS, GNOME_SCREENSAVER_PATH)
        obj = bus.get_proxy_object(GNOME_SCREENSAVER_BUS, GNOME_SCREENSAVER_PATH, intro)
        iface = obj.get_interface(GNOME_SCREENSAVER_IFACE)
        return bool(await iface.call_get_active())
    except Exception:
        return False


async def is_power_save_active(bus: MessageBus) -> bool:
    """Check if display power save mode is active.

    Tries GNOME Mutter DisplayConfig first (DPMS state), then falls back
    to KDE Solid PowerManagement lid state.
    """
    try:
        intro = await bus.introspect(DISPLAY_CONFIG_BUS, DISPLAY_CONFIG_PATH)
        obj = bus.get_proxy_object(DISPLAY_CONFIG_BUS, DISPLAY_CONFIG_PATH, intro)
        iface = obj.get_interface("org.freedesktop.DBus.Properties")
        mode_variant = await iface.call_get(DISPLAY_CONFIG_IFACE, "PowerSaveMode")
        mode = int(mode_variant.value)
        return mode != 0
    except Exception:
        pass

    try:
        intro = await bus.introspect(KDE_POWER_BUS, KDE_POWER_PATH)
        obj = bus.get_proxy_object(KDE_POWER_BUS, KDE_POWER_PATH, intro)
        iface = obj.get_interface(KDE_POWER_IFACE)
        return bool(await iface.call_is_lid_closed())
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
