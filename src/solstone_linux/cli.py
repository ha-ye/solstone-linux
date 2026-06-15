# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""CLI entry point for solstone-linux.

Subcommands:
    run             Start capture loop + sync service (default)
    setup           Interactive configuration
    install-service Write systemd user unit, enable, start
    status          Show capture and sync state
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.resources
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from . import doctor, streams
from .config import DEFAULT_SERVER_URL, load_config, save_config
from .streams import stream_name


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_run(args: argparse.Namespace) -> int:
    """Start the capture loop + sync service."""
    from .observer import async_run
    from .recovery import recover_incomplete_segments

    config = load_config()
    config.ensure_dirs()

    if not config.stream:
        try:
            config.stream = stream_name(host=socket.gethostname())
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    if args.interval:
        config.segment_interval = args.interval

    # Crash recovery before starting
    recovered = recover_incomplete_segments(config.captures_dir)
    if recovered:
        print(f"Recovered {recovered} incomplete segment(s)")

    try:
        return asyncio.run(async_run(config))
    except KeyboardInterrupt:
        return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """Interactive setup — configure server URL and register."""
    cli_token = args.token if getattr(args, "token", None) else None
    env_token = os.environ.get("SOLSTONE_TOKEN")
    token = cli_token or env_token
    non_interactive = getattr(args, "non_interactive", False)

    if (
        cli_token is None
        and env_token is None
        and getattr(args, "server_url", None) is None
        and getattr(args, "stream_name", None) is None
        and not non_interactive
    ):
        return _cmd_setup_interactive()

    if cli_token:
        print(
            "warning: --token on the command line may be visible in shell history and /proc on shared machines",
            file=sys.stderr,
        )

    from .upload import UploadClient

    config = load_config()

    # Resolve the journal URL: an explicit --server-url wins, then any saved
    # URL, otherwise the local link default. Under pure-PL the journal is
    # reached over the localhost link, so no URL needs to be typed.
    server_url = (
        getattr(args, "server_url", None) or config.server_url or DEFAULT_SERVER_URL
    )
    config.server_url = server_url

    stream_override = getattr(args, "stream_name", None)
    if stream_override:
        config.stream = stream_override
    elif not config.stream:
        try:
            config.stream = streams.stream_name(host=socket.gethostname())
        except ValueError as e:
            print(f"Error deriving stream name: {e}", file=sys.stderr)
            return 1

    config.ensure_dirs()

    if token:
        config.key = token
        save_config(config)
        print(f"Journal: {config.server_url}")
        print(f"Stream: {config.stream}")
        print("Using provided token; skipping registration.")
        print(f"\nConfig saved to {config.config_path}")
        print(f"Captures will go to {config.captures_dir}")
        print(
            "\nRun 'solstone-linux run' to start, or 'solstone-linux install-service' for systemd."
        )
        return 0

    save_config(config)

    if not config.key:
        print("Registering with your journal...")
        client = UploadClient(config)
        if client.ensure_registered(config):
            print(f"Registered (key: {config.key[:8]}...)")
            print(f"Stream: {config.stream}")
        else:
            print(
                "Warning: registration failed. Run setup again when your journal is available."
            )
            if non_interactive:
                return 1
    else:
        print(f"Already registered (key: {config.key[:8]}...)")
        print(f"Stream: {config.stream}")

    print(f"\nConfig saved to {config.config_path}")
    print(f"Captures will go to {config.captures_dir}")
    print(
        "\nRun 'solstone-linux run' to start, or 'solstone-linux install-service' for systemd."
    )
    return 0


def _cmd_setup_interactive() -> int:
    # Keep the legacy no-flags setup path separate so its output stays stable.
    from .upload import UploadClient

    config = load_config()

    # No prompt: default to the local link. Under pure-PL the journal is reached
    # over the localhost link, so no URL needs to be typed; a saved URL (or
    # `solstone-linux setup --server-url <url>`) points at a journal reached
    # directly.
    config.server_url = config.server_url or DEFAULT_SERVER_URL

    # Derive stream name
    if not config.stream:
        try:
            config.stream = stream_name(host=socket.gethostname())
        except ValueError as e:
            print(f"Error deriving stream name: {e}", file=sys.stderr)
            return 1

    # Save config before registration (so URL is persisted)
    config.ensure_dirs()
    save_config(config)

    if not config.key:
        print("Registering with your journal...")
        client = UploadClient(config)
        if client.ensure_registered(config):
            print(f"Registered (key: {config.key[:8]}...)")
            print(f"Stream: {config.stream}")
        else:
            print(
                "Warning: registration failed. Run setup again when your journal is available."
            )
    else:
        print(f"Already registered (key: {config.key[:8]}...)")
        print(f"Stream: {config.stream}")

    print(f"\nConfig saved to {config.config_path}")
    print(f"Captures will go to {config.captures_dir}")
    print(
        "\nRun 'solstone-linux run' to start, or 'solstone-linux install-service' for systemd."
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    return doctor.run_doctor()


def cmd_install_service(args: argparse.Namespace) -> int:
    """Write systemd user unit file, enable, and start the service."""
    binary = shutil.which("solstone-linux")
    if not binary:
        print("Error: solstone-linux not found on PATH", file=sys.stderr)
        print(
            "Install with: pipx install --system-site-packages solstone-linux",
            file=sys.stderr,
        )
        return 1

    venv_bin = str(Path(binary).resolve().parent)
    raw_path = os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin"
    path_entries = [venv_bin] + raw_path.split(":")
    service_path = ":".join(dict.fromkeys(path_entries))

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_path = unit_dir / "solstone-linux.service"
    template = (
        importlib.resources.files("solstone_linux")
        .joinpath("solstone-linux.service.in")
        .read_text()
    )
    unit = template.replace("{BINARY}", binary).replace("{PATH}", service_path)
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(unit)
    print(f"Wrote {unit_path}")

    # XDG autostart entry — X11 session managers that don't activate
    # graphical-session.target (the systemd unit's WantedBy target) need this
    # to autostart the service.  On Wayland, `start` is a no-op when the
    # service is already running.
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    autostart_path = autostart_dir / "solstone-linux.desktop"
    autostart_path.write_text(
        "[Desktop Entry]\n"
        "Version=1.2\n"
        "Type=Application\n"
        "Name=Solstone Observer\n"
        "Comment=Experience screen and audio with your solstone journal\n"
        "Exec=/bin/sh -c 'systemctl --user import-environment"
        " DISPLAY XAUTHORITY XDG_SESSION_TYPE 2>/dev/null;"
        " systemctl --user start solstone-linux.service'\n"
        "StartupNotify=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Hidden=false\n"
    )
    print(f"Wrote {autostart_path}")

    # Reload, enable, restart, and show status
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "solstone-linux.service"],
            check=True,
        )
        subprocess.run(
            ["systemctl", "--user", "restart", "solstone-linux.service"],
            check=True,
        )
        subprocess.run(
            [
                "systemctl",
                "--user",
                "--no-pager",
                "status",
                "solstone-linux.service",
            ],
            check=False,
        )
    except FileNotFoundError:
        print("Warning: systemctl not found. Enable the service manually.")
    except subprocess.CalledProcessError as e:
        print(f"Warning: systemctl command failed: {e}")

    icon_source = Path(__file__).resolve().parent / "icons" / "hicolor"
    if icon_source.is_dir():
        icon_dest = Path.home() / ".local" / "share" / "icons" / "hicolor"
        status_dir = icon_dest / "scalable" / "status"
        status_dir.mkdir(parents=True, exist_ok=True)

        for svg in sorted((icon_source / "scalable" / "status").iterdir()):
            if svg.suffix == ".svg":
                shutil.copy2(svg, status_dir / svg.name)
                print(f"Installed {status_dir / svg.name}")

        # Self-heal: earlier installs copied a solstone index.theme into this
        # shared hicolor dir. Because the user icon dir out-ranks
        # /usr/share/icons, that file shadowed the system hicolor index (which
        # declares ~649 dirs) with one that declared only scalable/status, so
        # every unrelated app-icon lookup fell back to hicolor, missed, and
        # rendered as our diamond. Remove only our own file — matched on the
        # exact "Name=solstone" line — and never touch a foreign index.theme.
        legacy_index = icon_dest / "index.theme"
        if legacy_index.exists():
            try:
                content = legacy_index.read_text()
            except (OSError, UnicodeDecodeError):
                print(f"Left existing icon theme index in place: {legacy_index}")
            else:
                if "Name=solstone" in content.splitlines():
                    legacy_index.unlink()
                    print(f"Removed stale solstone icon theme index: {legacy_index}")

        # Refresh the icon cache (non-fatal). --ignore-theme-index keeps it
        # quiet now that this dir ships no index.theme of its own.
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "--ignore-theme-index", str(icon_dest)],
                check=False,
            )
        except FileNotFoundError:
            pass

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show capture and sync state."""
    config = load_config()

    print(f"Config: {config.config_path}")
    print(f"Journal: {config.server_url or '(not configured)'}")
    print(f"Key:    {config.key[:8] + '...' if config.key else '(not registered)'}")
    print(f"Stream: {config.stream or '(not set)'}")
    print()

    # Cache size
    captures_dir = config.captures_dir
    if captures_dir.exists():
        total_size = 0
        segment_count = 0
        day_count = 0
        incomplete_count = 0

        for day_dir in sorted(captures_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            day_count += 1
            for stream_dir in day_dir.iterdir():
                if not stream_dir.is_dir():
                    continue
                for seg_dir in stream_dir.iterdir():
                    if not seg_dir.is_dir():
                        continue
                    if seg_dir.name.endswith(".incomplete"):
                        incomplete_count += 1
                        continue
                    if seg_dir.name.endswith(".failed"):
                        continue
                    segment_count += 1
                    for f in seg_dir.iterdir():
                        if f.is_file():
                            total_size += f.stat().st_size

        size_mb = total_size / (1024 * 1024)
        print(f"Cache:  {captures_dir}")
        print(
            f"        {segment_count} segments across {day_count} day(s), {size_mb:.1f} MB"
        )
        if incomplete_count:
            print(f"        {incomplete_count} incomplete segment(s)")
    else:
        print(f"Cache:  {captures_dir} (not created yet)")

    # Retention policy
    retention = config.cache_retention_days
    if retention < 0:
        print("Retain: forever")
    elif retention == 0:
        print("Retain: delete after sync")
    else:
        print(f"Retain: {retention} day(s)")

    # Synced days
    synced_path = config.state_dir / "synced_days.json"
    if synced_path.exists():
        try:
            with open(synced_path) as f:
                synced = json.load(f)
            print(f"Synced: {len(synced)} day(s) fully synced")
        except (json.JSONDecodeError, OSError):
            pass

    # Systemd status
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "solstone-linux.service"],
            capture_output=True,
            text=True,
        )
        state = result.stdout.strip()
        print(f"\nService: {state}")
    except FileNotFoundError:
        pass

    return 0


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="solstone-linux",
        description="Standalone Linux desktop observer for solstone",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    subparsers = parser.add_subparsers(dest="command")

    # run
    run_parser = subparsers.add_parser("run", help="Start capture + sync")
    run_parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Segment duration in seconds (default: 300)",
    )

    # setup
    setup_parser = subparsers.add_parser("setup", help="Interactive configuration")
    setup_parser.add_argument("--server-url", help="Journal URL (skips prompt)")
    setup_parser.add_argument(
        "--token",
        help="Pre-issued registration key; skips journal registration",
    )
    setup_parser.add_argument(
        "--stream-name",
        help="Stream name (defaults to hostname-derived)",
    )
    setup_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting for missing values",
    )

    # doctor
    subparsers.add_parser(
        "doctor",
        help="Verify install prerequisites",
    )

    # install-service
    subparsers.add_parser("install-service", help="Install systemd user service")

    # status
    subparsers.add_parser("status", help="Show capture and sync state")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    # Default to run if no subcommand
    command = args.command or "run"

    commands = {
        "run": cmd_run,
        "setup": cmd_setup,
        "doctor": cmd_doctor,
        "install-service": cmd_install_service,
        "status": cmd_status,
    }

    handler = commands.get(command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)
