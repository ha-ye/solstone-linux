# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Desktop session environment checks and recovery.

Extracted from solstone's observe/linux/observer.py (lines 598-666).

_recover_session_env() is kept as fallback for manual CLI launch.
For systemd service launch, PassEnvironment= in the unit file is
the primary mechanism.
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Exit codes
EXIT_TEMPFAIL = 75  # EX_TEMPFAIL: session not ready, retry later


def _recover_session_env() -> None:
    """Try to recover desktop session env vars from the systemd user manager.

    On GNOME Wayland, gnome-shell pushes DISPLAY, WAYLAND_DISPLAY, and
    DBUS_SESSION_BUS_ADDRESS into the systemd user environment on startup.
    When the observer is launched from a non-desktop shell, these vars may be missing
    from the inherited environment — but systemctl --user show-environment
    has them.
    """
    needed = {"DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"}
    missing = {v for v in needed if not os.environ.get(v)}
    if not missing:
        return

    # Ensure XDG_RUNTIME_DIR is set (required for systemctl --user to connect)
    if not os.environ.get("XDG_RUNTIME_DIR"):
        os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return

    recovered = []
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key in missing and value:
            os.environ[key] = value
            recovered.append(f"{key}={value}")

    if recovered:
        logger.info("Recovered session env from systemd: %s", ", ".join(recovered))


def check_session_ready() -> str | None:
    """Check if the desktop session is ready for observation.

    Returns None if ready, or a description of what's missing.
    """
    # Try to recover missing session vars from systemd user manager
    _recover_session_env()

    # Display server
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return "no display server (DISPLAY/WAYLAND_DISPLAY not set)"

    # DBus session bus
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return "no DBus session bus (DBUS_SESSION_BUS_ADDRESS not set)"

    # PulseAudio / PipeWire audio
    pactl = shutil.which("pactl")
    if pactl:
        try:
            subprocess.run(
                [pactl, "info"],
                capture_output=True,
                timeout=5,
            ).check_returncode()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return "audio server not responding (pactl info failed)"
    return None
