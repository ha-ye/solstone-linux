# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Tests for session environment checks."""

import os
from unittest.mock import patch

from solstone_linux.session_env import check_session_ready


class TestCheckSessionReady:
    """Test desktop session readiness checks."""

    def test_no_display_server(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("DISPLAY", "WAYLAND_DISPLAY")
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("solstone_linux.session_env._recover_session_env"):
                result = check_session_ready()
                assert result is not None
                assert "display server" in result

    def test_no_dbus(self):
        env = {k: v for k, v in os.environ.items() if k != "DBUS_SESSION_BUS_ADDRESS"}
        env["DISPLAY"] = ":0"
        with patch.dict(os.environ, env, clear=True):
            with patch("solstone_linux.session_env._recover_session_env"):
                result = check_session_ready()
                assert result is not None
                assert "DBus" in result

    def test_ready_with_display_and_dbus(self):
        env = dict(os.environ)
        env["DISPLAY"] = ":0"
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        with patch.dict(os.environ, env, clear=True):
            with patch("solstone_linux.session_env._recover_session_env"):
                with patch("solstone_linux.session_env.shutil") as mock_shutil:
                    mock_shutil.which.return_value = None  # No pactl
                    result = check_session_ready()
                    assert result is None  # Ready
