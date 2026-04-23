# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import argparse
import os
from pathlib import Path
from unittest.mock import patch

from solstone_linux import cli as cli_module
from solstone_linux.cli import cmd_install_service, cmd_setup
from solstone_linux.config import Config


def _args() -> argparse.Namespace:
    return argparse.Namespace()


_REAL_IS_DIR = Path.is_dir


def _is_dir_without_icons(self: Path) -> bool:
    icon_source = Path(cli_module.__file__).resolve().parent / "icons" / "hicolor"
    if self == icon_source:
        return False
    return _REAL_IS_DIR(self)


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
                        assert cmd_install_service(_args()) == 0

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
                        assert cmd_install_service(_args()) == 0

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
                        assert cmd_install_service(_args()) == 0

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


def test_cmd_install_service_always_rewrites(tmp_path: Path, capsys):
    binary = "/home/user/.local/pipx/venvs/solstone-linux/bin/solstone-linux"

    with patch.dict(os.environ, {"PATH": "/usr/local/bin:/usr/bin:/bin"}, clear=True):
        with patch("solstone_linux.cli.shutil.which", return_value=binary):
            with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
                with patch("solstone_linux.cli.subprocess.run") as run_mock:
                    with patch(
                        "solstone_linux.cli.Path.is_dir",
                        autospec=True,
                        side_effect=_is_dir_without_icons,
                    ):
                        assert cmd_install_service(_args()) == 0
                        assert cmd_install_service(_args()) == 0

    captured = capsys.readouterr()
    assert "nothing to do" not in captured.out.lower()
    assert run_mock.call_count == 8


def test_cmd_setup_non_interactive_happy_path(tmp_path: Path):
    args = argparse.Namespace(
        server_url="https://x",
        token="t",
        stream_name=None,
        non_interactive=True,
    )
    config = Config(base_dir=tmp_path)

    with patch("solstone_linux.cli.load_config", return_value=config):
        with patch("solstone_linux.cli.save_config") as save_mock:
            with patch("solstone_linux.cli.streams.stream_name", return_value="host-a"):
                with patch("solstone_linux.upload.UploadClient.ensure_registered"):
                    assert cmd_setup(args) == 0

    saved_config = save_mock.call_args.args[0]
    assert saved_config.server_url == "https://x"
    assert saved_config.key == "t"
    assert saved_config.stream == "host-a"


def test_cmd_setup_non_interactive_missing_server_url_fails(tmp_path: Path, capsys):
    args = argparse.Namespace(
        server_url=None,
        token=None,
        stream_name=None,
        non_interactive=True,
    )
    config = Config(base_dir=tmp_path)

    with patch.dict(os.environ, {}, clear=True):
        with patch("solstone_linux.cli.load_config", return_value=config):
            with patch("solstone_linux.upload.UploadClient.ensure_registered"):
                assert cmd_setup(args) == 2

    captured = capsys.readouterr()
    assert "--server-url" in captured.err


def test_cmd_setup_env_token_fallback(tmp_path: Path, capsys):
    args = argparse.Namespace(
        server_url="https://x",
        token=None,
        stream_name=None,
        non_interactive=True,
    )
    config = Config(base_dir=tmp_path)

    with patch.dict(os.environ, {"SOLSTONE_TOKEN": "envtok"}, clear=True):
        with patch("solstone_linux.cli.load_config", return_value=config):
            with patch("solstone_linux.cli.save_config") as save_mock:
                with patch(
                    "solstone_linux.cli.streams.stream_name",
                    return_value="host-a",
                ):
                    with patch("solstone_linux.upload.UploadClient.ensure_registered"):
                        assert cmd_setup(args) == 0

    saved_config = save_mock.call_args.args[0]
    captured = capsys.readouterr()
    assert saved_config.key == "envtok"
    assert "shared machines" not in captured.err


def test_cmd_setup_cli_token_beats_env(tmp_path: Path, capsys):
    args = argparse.Namespace(
        server_url="https://x",
        token="clitok",
        stream_name=None,
        non_interactive=True,
    )
    config = Config(base_dir=tmp_path)

    with patch.dict(os.environ, {"SOLSTONE_TOKEN": "envtok"}, clear=True):
        with patch("solstone_linux.cli.load_config", return_value=config):
            with patch("solstone_linux.cli.save_config") as save_mock:
                with patch(
                    "solstone_linux.cli.streams.stream_name",
                    return_value="host-a",
                ):
                    with patch("solstone_linux.upload.UploadClient.ensure_registered"):
                        assert cmd_setup(args) == 0

    saved_config = save_mock.call_args.args[0]
    captured = capsys.readouterr()
    assert saved_config.key == "clitok"
    assert "shared machines" in captured.err
