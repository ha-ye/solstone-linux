# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import argparse
import os
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from solstone_linux import cli as cli_module
from solstone_linux.cli import cmd_install_service, cmd_setup
from solstone_linux.config import Config


def _args() -> argparse.Namespace:
    return argparse.Namespace()


_BINARY = "/home/user/.local/pipx/venvs/solstone-linux/bin/solstone-linux"
_EXPECTED_SVGS = {
    "solstone-error.svg",
    "solstone-paused.svg",
    "solstone-recording.svg",
    "solstone-syncing.svg",
}


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


def test_cmd_install_service_installs_svgs_without_index_theme(tmp_path: Path):
    with patch("solstone_linux.cli.shutil.which", return_value=_BINARY):
        with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
            with patch("solstone_linux.cli.subprocess.run"):
                assert cmd_install_service(_args()) == 0

    hicolor = tmp_path / ".local/share/icons/hicolor"
    status = hicolor / "scalable/status"

    assert {path.name for path in status.glob("*.svg")} == _EXPECTED_SVGS
    assert not (hicolor / "index.theme").exists()


def test_cmd_install_service_removes_stale_solstone_index_theme(tmp_path: Path):
    hicolor = tmp_path / ".local/share/icons/hicolor"
    hicolor.mkdir(parents=True)
    (hicolor / "index.theme").write_text(
        "[Icon Theme]\nName=solstone\nInherits=hicolor\nDirectories=scalable/status\n"
    )

    with patch("solstone_linux.cli.shutil.which", return_value=_BINARY):
        with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
            with patch("solstone_linux.cli.subprocess.run"):
                assert cmd_install_service(_args()) == 0

    assert not (hicolor / "index.theme").exists()


def test_cmd_install_service_keeps_foreign_index_theme(tmp_path: Path):
    hicolor = tmp_path / ".local/share/icons/hicolor"
    hicolor.mkdir(parents=True)
    index = hicolor / "index.theme"
    content = "[Icon Theme]\nName=MyTheme\nName=solstone-custom\n"
    index.write_text(content)

    with patch("solstone_linux.cli.shutil.which", return_value=_BINARY):
        with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
            with patch("solstone_linux.cli.subprocess.run"):
                assert cmd_install_service(_args()) == 0

    assert index.exists()
    assert index.read_text() == content


def test_cmd_install_service_reports_unreadable_index_theme(
    tmp_path: Path,
    capsys,
):
    hicolor = tmp_path / ".local/share/icons/hicolor"
    hicolor.mkdir(parents=True)
    index = hicolor / "index.theme"
    index.write_bytes(b"\xff\xfe\x00not utf8")

    with patch("solstone_linux.cli.shutil.which", return_value=_BINARY):
        with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
            with patch("solstone_linux.cli.subprocess.run"):
                assert cmd_install_service(_args()) == 0

    captured = capsys.readouterr()
    warning_lines = [
        line
        for line in captured.out.splitlines()
        if "Left existing icon theme index in place" in line
    ]

    assert index.exists()
    assert len(warning_lines) == 1
    assert str(index) in warning_lines[0]


def test_cmd_install_service_icon_step_idempotent(tmp_path: Path):
    with patch("solstone_linux.cli.shutil.which", return_value=_BINARY):
        with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
            with patch("solstone_linux.cli.subprocess.run"):
                assert cmd_install_service(_args()) == 0
                assert cmd_install_service(_args()) == 0

    hicolor = tmp_path / ".local/share/icons/hicolor"
    status = hicolor / "scalable/status"

    assert {path.name for path in status.glob("*.svg")} == _EXPECTED_SVGS
    assert not (hicolor / "index.theme").exists()


def test_cmd_install_service_survives_missing_gtk_update_icon_cache(tmp_path: Path):
    with patch("solstone_linux.cli.shutil.which", return_value=_BINARY):
        with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
            with patch(
                "solstone_linux.cli.subprocess.run",
                side_effect=FileNotFoundError,
            ):
                assert cmd_install_service(_args()) == 0

    hicolor = tmp_path / ".local/share/icons/hicolor"
    status = hicolor / "scalable/status"

    assert {path.name for path in status.glob("*.svg")} == _EXPECTED_SVGS
    assert not (hicolor / "index.theme").exists()


def test_cmd_install_service_survives_nonzero_gtk_update_icon_cache(tmp_path: Path):
    with patch("solstone_linux.cli.shutil.which", return_value=_BINARY):
        with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
            with patch("solstone_linux.cli.subprocess.run") as run_mock:
                run_mock.return_value = MagicMock(returncode=1)

                assert cmd_install_service(_args()) == 0


def test_cmd_install_service_writes_autostart_entry(tmp_path: Path):
    with patch("solstone_linux.cli.shutil.which", return_value=_BINARY):
        with patch("solstone_linux.cli.Path.home", return_value=tmp_path):
            with patch("solstone_linux.cli.subprocess.run"):
                assert cmd_install_service(_args()) == 0

    autostart = tmp_path / ".config" / "autostart" / "solstone-linux.desktop"
    assert autostart.exists()
    content = autostart.read_text()
    assert "Type=Application" in content
    assert "solstone-linux.service" in content
    assert "import-environment" in content
    assert "DISPLAY" in content
    assert "XAUTHORITY" in content
    assert "XDG_SESSION_TYPE" in content


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


def test_cmd_setup_registers_via_http_when_no_token(tmp_path: Path):
    args = argparse.Namespace(
        server_url="http://localhost:9",
        token=None,
        stream_name=None,
        non_interactive=True,
    )
    config = Config(base_dir=tmp_path)

    def _register(cfg):
        cfg.key = "newkey00"
        cfg.stream = "locked-stream"
        return True

    with patch.dict(os.environ, {}, clear=True):
        with patch("solstone_linux.cli.load_config", return_value=config):
            with patch("solstone_linux.cli.save_config"):
                with patch(
                    "solstone_linux.cli.streams.stream_name", return_value="host-a"
                ):
                    with patch(
                        "solstone_linux.upload.UploadClient.ensure_registered",
                        side_effect=_register,
                    ) as reg_mock:
                        assert cmd_setup(args) == 0

    reg_mock.assert_called_once()
    assert config.key == "newkey00"
    assert config.stream == "locked-stream"


def test_cmd_setup_http_register_failure_non_interactive_returns_1(
    tmp_path: Path, capsys
):
    args = argparse.Namespace(
        server_url="http://localhost:9",
        token=None,
        stream_name=None,
        non_interactive=True,
    )
    config = Config(base_dir=tmp_path)

    with patch.dict(os.environ, {}, clear=True):
        with patch("solstone_linux.cli.load_config", return_value=config):
            with patch("solstone_linux.cli.save_config"):
                with patch(
                    "solstone_linux.cli.streams.stream_name", return_value="host-a"
                ):
                    with patch(
                        "solstone_linux.upload.UploadClient.ensure_registered",
                        return_value=False,
                    ):
                        assert cmd_setup(args) == 1

    captured = capsys.readouterr()
    assert "registration failed" in captured.out.lower()
