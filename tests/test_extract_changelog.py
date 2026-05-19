# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_changelog.sh"


def _run(args, cwd):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_two_block_extracts_target_only(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n"
        "\n"
        "## [0.2.0] - 2026-06-01\n"
        "\n"
        "second release line.\n"
        "\n"
        "## [0.1.0] - 2026-05-19\n"
        "\n"
        "first release line.\n"
    )
    result = _run(["0.2.0", str(changelog)], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "## [0.2.0]" in result.stdout
    assert "second release line." in result.stdout
    assert "## [0.1.0]" not in result.stdout
    assert "first release line." not in result.stdout


def test_one_block_bootstrap(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n"
        "\n"
        "## [0.1.0] - 2026-05-19\n"
        "\n"
        "first release line.\n"
        "trailing line.\n"
    )
    result = _run(["0.1.0", str(changelog)], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "## [0.1.0]" in result.stdout
    assert "first release line." in result.stdout
    assert "trailing line." in result.stdout


def test_missing_version_errors(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [0.1.0] - 2026-05-19\n\nfirst release line.\n"
    )
    result = _run(["9.9.9", str(changelog)], cwd=tmp_path)
    assert result.returncode != 0
    assert "9.9.9" in result.stderr
