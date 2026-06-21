# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Tests for session environment checks."""

import os
import subprocess
from unittest.mock import MagicMock, call, patch

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

    def test_pactl_succeeds_on_first_try(self):
        env = dict(os.environ)
        env["DISPLAY"] = ":0"
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        with patch.dict(os.environ, env, clear=True):
            with patch("solstone_linux.session_env._recover_session_env"):
                with patch("solstone_linux.session_env.shutil") as mock_shutil:
                    mock_shutil.which.return_value = "/usr/bin/pactl"
                    with patch("solstone_linux.session_env.subprocess") as mock_sub:
                        mock_run = MagicMock()
                        mock_run.check_returncode.return_value = None
                        mock_sub.run.return_value = mock_run
                        result = check_session_ready()
                        assert result is None
                        assert mock_sub.run.call_count == 1

    def test_pactl_fails_all_retries(self):
        env = dict(os.environ)
        env["DISPLAY"] = ":0"
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        with patch.dict(os.environ, env, clear=True):
            with patch("solstone_linux.session_env._recover_session_env"):
                with patch("solstone_linux.session_env.shutil") as mock_shutil:
                    mock_shutil.which.return_value = "/usr/bin/pactl"
                    with patch("solstone_linux.session_env.subprocess") as mock_sub:
                        mock_sub.CalledProcessError = subprocess.CalledProcessError
                        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
                        mock_run = MagicMock()
                        mock_run.check_returncode.side_effect = (
                            subprocess.CalledProcessError(1, "pactl")
                        )
                        mock_sub.run.return_value = mock_run
                        with patch("solstone_linux.session_env.time") as mock_time:
                            result = check_session_ready()
                            assert result is not None
                            assert "audio server" in result
                            assert mock_sub.run.call_count == 3
                            assert mock_time.sleep.call_count == 2

    def test_pactl_succeeds_on_retry(self):
        env = dict(os.environ)
        env["DISPLAY"] = ":0"
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        with patch.dict(os.environ, env, clear=True):
            with patch("solstone_linux.session_env._recover_session_env"):
                with patch("solstone_linux.session_env.shutil") as mock_shutil:
                    mock_shutil.which.return_value = "/usr/bin/pactl"
                    with patch("solstone_linux.session_env.subprocess") as mock_sub:
                        mock_sub.CalledProcessError = subprocess.CalledProcessError
                        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
                        fail = MagicMock()
                        fail.check_returncode.side_effect = (
                            subprocess.CalledProcessError(1, "pactl")
                        )
                        succeed = MagicMock()
                        succeed.check_returncode.return_value = None
                        mock_sub.run.side_effect = [fail, succeed]
                        with patch("solstone_linux.session_env.time") as mock_time:
                            result = check_session_ready()
                            assert result is None
                            assert mock_sub.run.call_count == 2
                            assert mock_time.sleep.call_count == 1
