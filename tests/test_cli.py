# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import argparse
import os
from pathlib import Path
from unittest.mock import patch

from solstone_linux.cli import cmd_install_service


def test_cmd_install_service_uses_environment_path(tmp_path: Path):
    binary = "/home/user/.local/pipx/venvs/solstone-linux/bin/solstone-linux"
    unit_path = tmp_path / ".config" / "systemd" / "user" / "solstone-linux.service"
    env = {
        "PATH": "/home/user/.local/pipx/venvs/solstone-linux/bin:/usr/local/bin:/usr/bin:/bin:/home/user/.local/bin"
    }

    with patch.dict(os.environ, env, clear=True):
        with patch("solstone_linux.cli.shutil.which", return_value=binary):
            with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
                with patch("solstone_linux.cli.subprocess.run"):
                    with patch("solstone_linux.cli.Path.is_dir", return_value=False):
                        assert cmd_install_service(argparse.Namespace()) == 0

    unit_content = unit_path.read_text()
    path_line = next(
        line
        for line in unit_content.splitlines()
        if line.startswith("Environment=PATH=")
    )
    service_path = path_line.removeprefix("Environment=PATH=").split(":")

    assert service_path[0] == "/home/user/.local/pipx/venvs/solstone-linux/bin"
    assert service_path == list(dict.fromkeys(service_path))


def test_cmd_install_service_uses_default_path_when_missing(tmp_path: Path):
    binary = "/home/user/.local/pipx/venvs/solstone-linux/bin/solstone-linux"
    unit_path = tmp_path / ".config" / "systemd" / "user" / "solstone-linux.service"

    with patch.dict(os.environ, {}, clear=True):
        with patch("solstone_linux.cli.shutil.which", return_value=binary):
            with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
                with patch("solstone_linux.cli.subprocess.run"):
                    with patch("solstone_linux.cli.Path.is_dir", return_value=False):
                        assert cmd_install_service(argparse.Namespace()) == 0

    unit_content = unit_path.read_text()
    path_line = next(
        line
        for line in unit_content.splitlines()
        if line.startswith("Environment=PATH=")
    )

    assert (
        path_line
        == "Environment=PATH=/home/user/.local/pipx/venvs/solstone-linux/bin:/usr/local/bin:/usr/bin:/bin"
    )


def test_cmd_install_service_uses_default_path_when_empty(tmp_path: Path):
    binary = "/home/user/.local/pipx/venvs/solstone-linux/bin/solstone-linux"
    unit_path = tmp_path / ".config" / "systemd" / "user" / "solstone-linux.service"

    with patch.dict(os.environ, {"PATH": ""}, clear=True):
        with patch("solstone_linux.cli.shutil.which", return_value=binary):
            with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
                with patch("solstone_linux.cli.subprocess.run"):
                    with patch("solstone_linux.cli.Path.is_dir", return_value=False):
                        assert cmd_install_service(argparse.Namespace()) == 0

    unit_content = unit_path.read_text()
    path_line = next(
        line
        for line in unit_content.splitlines()
        if line.startswith("Environment=PATH=")
    )

    assert (
        path_line
        == "Environment=PATH=/home/user/.local/pipx/venvs/solstone-linux/bin:/usr/local/bin:/usr/bin:/bin"
    )
