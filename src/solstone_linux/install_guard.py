# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc
"""Install ownership guard for pipx-managed service installs."""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

MARKER_REL = Path(".config/solstone-linux/.install-source")
PIPX_BIN_REL = Path(".local/bin/solstone-linux")


def marker_path() -> Path:
    return Path.home() / MARKER_REL


def pipx_bin_path() -> Path:
    return Path.home() / PIPX_BIN_REL


class State(str, Enum):
    ABSENT = "ABSENT"
    OWNED = "OWNED"
    CROSS_REPO = "CROSS_REPO"
    PARTIAL_OWNED = "PARTIAL_OWNED"
    UNKNOWN = "UNKNOWN"


def _parse_marker() -> Path | None:
    try:
        raw = marker_path().read_text(encoding="utf-8")
    except OSError:
        return None

    stripped = raw.strip()
    if not stripped:
        return None

    lines = stripped.splitlines()
    if len(lines) != 1:
        return None

    candidate = Path(lines[0].strip())
    if not candidate.is_absolute():
        return None

    return candidate.resolve()


def check(curdir: Path) -> tuple[State, Path | None]:
    resolved_curdir = curdir.resolve()
    marker = marker_path()
    pipx_bin_present = pipx_bin_path().exists()

    if not marker.exists():
        if not pipx_bin_present:
            return (State.ABSENT, None)
        return (State.UNKNOWN, None)

    owner = _parse_marker()
    if owner is None:
        return (State.UNKNOWN, None)
    if owner != resolved_curdir:
        return (State.CROSS_REPO, owner)
    if pipx_bin_present:
        return (State.OWNED, owner)
    return (State.PARTIAL_OWNED, owner)


def write_marker(curdir: Path) -> None:
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{curdir.resolve()}\n", encoding="utf-8")


def remove_marker() -> None:
    marker_path().unlink(missing_ok=True)


def _unknown_reason() -> str:
    if marker_path().exists():
        return ".install-source marker is malformed"
    return "no .install-source marker — likely pre-hygiene install"


def _print_cross_repo_error(curdir: Path, owner: Path | None, uninstall: bool) -> None:
    lines = [
        "error: cross-repo contamination detected",
        f"current repo: {curdir.resolve()}",
        f"installed from: {owner}",
        "",
        "To recover, run from the installed repo:",
        "  make uninstall-service",
        "Or manually:",
    ]
    if uninstall:
        lines.extend(
            [
                "  systemctl --user stop solstone-linux.service",
                "  systemctl --user disable solstone-linux.service",
                "  rm -f ~/.config/systemd/user/solstone-linux.service",
            ]
        )
    lines.extend(
        [
            "  pipx uninstall solstone-linux",
            "  rm ~/.config/solstone-linux/.install-source",
        ]
    )
    print("\n".join(lines), file=sys.stderr)


def _print_unknown_error(uninstall: bool) -> None:
    lines = [
        f"error: installed: unknown ({_unknown_reason()})",
        "",
        "To recover:",
    ]
    if uninstall:
        lines.extend(
            [
                "  systemctl --user stop solstone-linux.service",
                "  systemctl --user disable solstone-linux.service",
                "  rm -f ~/.config/systemd/user/solstone-linux.service",
            ]
        )
    lines.extend(
        [
            "  pipx uninstall solstone-linux",
            "  rm -f ~/.config/solstone-linux/.install-source",
            "Then re-run make install-service.",
        ]
    )
    print("\n".join(lines), file=sys.stderr)


def _preinstall(curdir: Path) -> int:
    state, owner = check(curdir)
    if state is State.ABSENT:
        print("mode: fresh install")
        return 0
    if state is State.OWNED:
        print("mode: upgrade")
        return 10
    if state is State.PARTIAL_OWNED:
        print(
            "warning: .install-source marker present but pipx binary missing — reinstalling"
        )
        print("mode: upgrade")
        return 10
    if state is State.CROSS_REPO:
        print("mode: aborted — cross-repo contamination")
        _print_cross_repo_error(curdir, owner, uninstall=False)
        return 2

    print("mode: aborted — unknown install state")
    _print_unknown_error(uninstall=False)
    return 2


def _preuninstall(curdir: Path) -> int:
    state, owner = check(curdir)
    if state is State.ABSENT:
        print("no artifacts to remove")
        return 0
    if state in {State.OWNED, State.PARTIAL_OWNED}:
        return 10
    if state is State.CROSS_REPO:
        print("mode: aborted — cross-repo contamination")
        _print_cross_repo_error(curdir, owner, uninstall=True)
        return 2

    print("mode: aborted — unknown install state")
    _print_unknown_error(uninstall=True)
    return 2


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: install_guard <preinstall|preuninstall|write|remove> [curdir]",
            file=sys.stderr,
        )
        return 2

    command = sys.argv[1]
    if command == "remove":
        remove_marker()
        return 0

    if command in {"preinstall", "preuninstall", "write"}:
        if len(sys.argv) != 3:
            print(f"usage: install_guard {command} <curdir>", file=sys.stderr)
            return 2
        curdir = Path(sys.argv[2])
        if command == "preinstall":
            return _preinstall(curdir)
        if command == "preuninstall":
            return _preuninstall(curdir)
        write_marker(curdir)
        return 0

    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
