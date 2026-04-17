# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import sys
from pathlib import Path

from solstone_linux import install_guard
from solstone_linux.install_guard import State


def _set_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(install_guard.Path, "home", lambda: tmp_path)


def _run_main(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["install_guard", *argv])
    return install_guard.main()


def test_state_absent(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()

    assert install_guard.check(curdir) == (State.ABSENT, None)

    assert _run_main(monkeypatch, "preinstall", str(curdir)) == 0
    captured = capsys.readouterr()
    assert captured.out == "mode: fresh install\n"
    assert captured.err == ""

    assert _run_main(monkeypatch, "preuninstall", str(curdir)) == 0
    captured = capsys.readouterr()
    assert captured.out == "no artifacts to remove\n"
    assert captured.err == ""


def test_state_unknown_pre_hygiene(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()
    install_guard.pipx_bin_path().parent.mkdir(parents=True)
    install_guard.pipx_bin_path().touch()

    assert install_guard.check(curdir) == (State.UNKNOWN, None)

    assert _run_main(monkeypatch, "preinstall", str(curdir)) == 2
    captured = capsys.readouterr()
    assert captured.out == "mode: aborted — unknown install state\n"
    assert (
        "error: installed: unknown (no .install-source marker — likely pre-hygiene install)\n"
        in captured.err
    )


def test_state_owned_install_mode(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()
    install_guard.write_marker(curdir)
    install_guard.pipx_bin_path().parent.mkdir(parents=True)
    install_guard.pipx_bin_path().touch()

    assert install_guard.check(curdir) == (State.OWNED, curdir.resolve())

    assert _run_main(monkeypatch, "preinstall", str(curdir)) == 10
    captured = capsys.readouterr()
    assert captured.out == "mode: upgrade\n"
    assert captured.err == ""


def test_state_owned_uninstall_mode(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()
    install_guard.write_marker(curdir)
    install_guard.pipx_bin_path().parent.mkdir(parents=True)
    install_guard.pipx_bin_path().touch()

    assert _run_main(monkeypatch, "preuninstall", str(curdir)) == 10
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_state_cross_repo(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    other = tmp_path / "other"
    curdir.mkdir()
    other.mkdir()
    install_guard.write_marker(other)
    install_guard.pipx_bin_path().parent.mkdir(parents=True)
    install_guard.pipx_bin_path().touch()

    assert install_guard.check(curdir) == (State.CROSS_REPO, other.resolve())

    assert _run_main(monkeypatch, "preinstall", str(curdir)) == 2
    captured = capsys.readouterr()
    assert captured.out == "mode: aborted — cross-repo contamination\n"
    assert "error: cross-repo contamination detected\n" in captured.err
    assert f"current repo: {curdir.resolve()}\n" in captured.err
    assert f"installed from: {other.resolve()}\n" in captured.err


def test_state_partial_owned(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()
    install_guard.write_marker(curdir)

    assert install_guard.check(curdir) == (State.PARTIAL_OWNED, curdir.resolve())

    assert _run_main(monkeypatch, "preinstall", str(curdir)) == 10
    captured = capsys.readouterr()
    assert (
        captured.out
        == "warning: .install-source marker present but pipx binary missing — reinstalling\nmode: upgrade\n"
    )
    assert captured.err == ""


def test_malformed_marker_empty(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()
    install_guard.marker_path().parent.mkdir(parents=True)
    install_guard.marker_path().write_text("", encoding="utf-8")
    install_guard.pipx_bin_path().parent.mkdir(parents=True)
    install_guard.pipx_bin_path().touch()

    assert install_guard.check(curdir) == (State.UNKNOWN, None)

    assert _run_main(monkeypatch, "preinstall", str(curdir)) == 2
    captured = capsys.readouterr()
    assert (
        "error: installed: unknown (.install-source marker is malformed)\n"
        in captured.err
    )


def test_malformed_marker_multiline(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()
    install_guard.marker_path().parent.mkdir(parents=True)
    install_guard.marker_path().write_text("/one\n/two\n", encoding="utf-8")
    install_guard.pipx_bin_path().parent.mkdir(parents=True)
    install_guard.pipx_bin_path().touch()

    assert install_guard.check(curdir) == (State.UNKNOWN, None)

    assert _run_main(monkeypatch, "preinstall", str(curdir)) == 2
    captured = capsys.readouterr()
    assert (
        "error: installed: unknown (.install-source marker is malformed)\n"
        in captured.err
    )


def test_malformed_marker_not_absolute_path(tmp_path: Path, monkeypatch, capsys):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()
    install_guard.marker_path().parent.mkdir(parents=True)
    install_guard.marker_path().write_text("relative/path\n", encoding="utf-8")
    install_guard.pipx_bin_path().parent.mkdir(parents=True)
    install_guard.pipx_bin_path().touch()

    assert install_guard.check(curdir) == (State.UNKNOWN, None)

    assert _run_main(monkeypatch, "preinstall", str(curdir)) == 2
    captured = capsys.readouterr()
    assert (
        "error: installed: unknown (.install-source marker is malformed)\n"
        in captured.err
    )


def test_write_and_remove_marker(tmp_path: Path, monkeypatch):
    _set_home(monkeypatch, tmp_path)
    curdir = tmp_path / "repo"
    curdir.mkdir()

    assert _run_main(monkeypatch, "write", str(curdir)) == 0
    assert (
        install_guard.marker_path().read_text(encoding="utf-8")
        == f"{curdir.resolve()}\n"
    )

    assert _run_main(monkeypatch, "remove") == 0
    assert not install_guard.marker_path().exists()
