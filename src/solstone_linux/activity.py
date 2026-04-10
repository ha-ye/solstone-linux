# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Activity detection using DBus APIs.

Detects screen lock and display power-save state via DBus, with ordered
fallback chains that cover GNOME and KDE desktops. Every function
degrades gracefully — returning a safe default — so the observer keeps
running regardless of desktop environment.
"""

import logging
import os

from dbus_next import Variant
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

# DBus service constants — screen lock
FDO_SCREENSAVER_BUS = "org.freedesktop.ScreenSaver"
FDO_SCREENSAVER_PATH = "/ScreenSaver"
FDO_SCREENSAVER_IFACE = "org.freedesktop.ScreenSaver"

GNOME_SCREENSAVER_BUS = "org.gnome.ScreenSaver"
GNOME_SCREENSAVER_PATH = "/org/gnome/ScreenSaver"
GNOME_SCREENSAVER_IFACE = "org.gnome.ScreenSaver"

# DBus service constants — power save
DISPLAY_CONFIG_BUS = "org.gnome.Mutter.DisplayConfig"
DISPLAY_CONFIG_PATH = "/org/gnome/Mutter/DisplayConfig"
DISPLAY_CONFIG_IFACE = "org.gnome.Mutter.DisplayConfig"

KDE_POWER_BUS = "org.kde.Solid.PowerManagement"
KDE_POWER_PATH = "/org/kde/Solid/PowerManagement"
KDE_POWER_IFACE = "org.kde.Solid.PowerManagement"

# DBus service constants — monitor geometry (KDE)
KSCREEN_BUS = "org.kde.KScreen"
KSCREEN_PATH = "/backend"
KSCREEN_IFACE = "org.kde.kscreen.Backend"


async def probe_activity_services(bus: MessageBus) -> dict[str, bool]:
    """Check which activity DBus services are reachable."""
    services = {
        "fdo_screensaver": FDO_SCREENSAVER_BUS,
        "gnome_screensaver": GNOME_SCREENSAVER_BUS,
        "gnome_display_config": DISPLAY_CONFIG_BUS,
        "kde_power": KDE_POWER_BUS,
        "kscreen": KSCREEN_BUS,
    }
    results = {}
    for name, bus_name in services.items():
        try:
            await bus.introspect(bus_name, "/")
            results[name] = True
        except Exception:
            results[name] = False

    # Log grouped by function
    lock_backends = ["fdo_screensaver", "gnome_screensaver"]
    power_backends = ["gnome_display_config", "kde_power"]
    monitor_backends = ["kscreen"]
    results["gtk4"] = _HAS_GTK

    def _status(keys):
        return ", ".join(f"{k} [{'ok' if results[k] else 'missing'}]" for k in keys)

    logger.info("Screen lock backends: %s", _status(lock_backends))
    logger.info("Power save backends: %s", _status(power_backends))
    logger.info(
        "Monitor backends: %s, gtk4 [%s]",
        _status(monitor_backends),
        "ok" if results["gtk4"] else "missing",
    )

    any_lock = any(results[k] for k in lock_backends)
    any_power = any(results[k] for k in power_backends)
    if not any_lock and not any_power:
        logger.warning(
            "No activity backends available — running in always-capture mode"
        )

    return results


async def is_screen_locked(bus: MessageBus) -> bool:
    """Check if the screen is locked via FDO ScreenSaver, then GNOME ScreenSaver.

    Returns True if locked, False if unlocked or all backends unavailable.
    """
    # Try freedesktop.org ScreenSaver first (KDE kwin + GNOME)
    try:
        intro = await bus.introspect(FDO_SCREENSAVER_BUS, FDO_SCREENSAVER_PATH)
        obj = bus.get_proxy_object(FDO_SCREENSAVER_BUS, FDO_SCREENSAVER_PATH, intro)
        iface = obj.get_interface(FDO_SCREENSAVER_IFACE)
        return bool(await iface.call_get_active())
    except Exception:
        pass

    # Fall back to GNOME ScreenSaver
    try:
        intro = await bus.introspect(GNOME_SCREENSAVER_BUS, GNOME_SCREENSAVER_PATH)
        obj = bus.get_proxy_object(GNOME_SCREENSAVER_BUS, GNOME_SCREENSAVER_PATH, intro)
        iface = obj.get_interface(GNOME_SCREENSAVER_IFACE)
        return bool(await iface.call_get_active())
    except Exception:
        return False


async def is_power_save_active(bus: MessageBus) -> bool:
    """Check display power save via GNOME Mutter, then KDE Solid.

    Returns True if power save is active, False otherwise.
    """
    # Try GNOME Mutter DisplayConfig first
    try:
        intro = await bus.introspect(DISPLAY_CONFIG_BUS, DISPLAY_CONFIG_PATH)
        obj = bus.get_proxy_object(DISPLAY_CONFIG_BUS, DISPLAY_CONFIG_PATH, intro)
        iface = obj.get_interface("org.freedesktop.DBus.Properties")
        mode_variant = await iface.call_get(DISPLAY_CONFIG_IFACE, "PowerSaveMode")
        mode = int(mode_variant.value)
        return mode != 0
    except Exception:
        pass

    # Fall back to KDE Solid PowerManagement
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


def _unwrap_variants(obj):
    """Recursively unwrap dbus-next Variants in nested DBus structures."""
    if isinstance(obj, Variant):
        return _unwrap_variants(obj.value)
    if isinstance(obj, dict):
        return {key: _unwrap_variants(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_unwrap_variants(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(_unwrap_variants(value) for value in obj)
    return obj


async def get_monitor_geometries_kscreen(bus: MessageBus) -> list[dict]:
    """
    Get monitor geometry information from KDE KScreen DBus.

    Returns:
        List of dicts with format:
        [{"id": "connector-id", "box": [x1, y1, x2, y2], "position": "center|left|right|..."}, ...]
    """
    try:
        from .monitor_positions import assign_monitor_positions

        intro = await bus.introspect(KSCREEN_BUS, KSCREEN_PATH)
        obj = bus.get_proxy_object(KSCREEN_BUS, KSCREEN_PATH, intro)
        iface = obj.get_interface(KSCREEN_IFACE)
        config = _unwrap_variants(await iface.call_get_config())
        outputs = config.get("outputs", {})
        output_values = outputs.values() if isinstance(outputs, dict) else outputs

        geometries = []
        for output in output_values:
            if not isinstance(output, dict):
                continue
            if not output.get("enabled") or not output.get("connected"):
                continue

            name = output.get("name")
            pos = output.get("pos", {})
            size = output.get("size", {})
            if not isinstance(name, str) or not isinstance(pos, dict):
                continue
            if not isinstance(size, dict):
                continue

            x = int(pos.get("x", 0))
            y = int(pos.get("y", 0))
            scale = float(output.get("scale", 1.0) or 1.0)
            width = int(size.get("width", 0))
            height = int(size.get("height", 0))
            logical_width = round(width / scale)
            logical_height = round(height / scale)
            geometries.append(
                {
                    "id": name,
                    "box": [x, y, x + logical_width, y + logical_height],
                }
            )

        monitors = assign_monitor_positions(geometries)
        logger.debug("KScreen monitor geometries found: %d", len(monitors))
        return monitors
    except Exception:
        return []
