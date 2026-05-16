# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Background sync service for uploading captured segments.

Modeled on solstone-macos's SyncService.swift. Runs as an asyncio
background task in the same event loop as capture. Walks cache days
newest-to-oldest, queries server for existing segments, uploads missing ones.

Refinements over tmux baseline:
- Respects configured sync_max_retries (no hard min(config,3) cap)
- Circuit breaker tuned by error type: auth=immediate, transient=5-10
- Transient circuit breaker recovers via half-open probe with exponential backoff
- Auth/revoked circuit breaker is permanent (requires restart)
- Synced-days pruning at 90 days to prevent unbounded cache growth
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .upload import ErrorType, UploadClient

logger = logging.getLogger(__name__)

# Circuit breaker thresholds by error type
CIRCUIT_THRESHOLD_AUTH = 1  # Auth failures open immediately
CIRCUIT_THRESHOLD_TRANSIENT = 5  # Transient failures need 5 consecutive

# Circuit breaker recovery cooldown
CIRCUIT_COOLDOWN_INITIAL = 30  # seconds before first probe
CIRCUIT_COOLDOWN_FACTOR = 2  # multiply cooldown on each failed probe
CIRCUIT_COOLDOWN_MAX = 300  # cap at 5 minutes

# Synced days older than this are pruned from the cache
SYNCED_DAYS_MAX_AGE = 90


class SyncService:
    """Background sync service that uploads completed segments to the server."""

    def __init__(self, config: Config, client: UploadClient):
        self._config = config
        self._client = client
        self._synced_days: set[str] = set()
        self._consecutive_failures = 0
        self._last_error_type: ErrorType | None = None
        self._circuit_open = False
        self._circuit_open_permanent = False
        self._circuit_open_since: float = 0.0
        self._circuit_cooldown: float = CIRCUIT_COOLDOWN_INITIAL
        self._last_full_sync: float = 0
        self._running = True
        self._trigger = asyncio.Event()
        self.sync_status = "synced"
        self.sync_progress = ""
        self._dbus_service = None

        # Load synced days cache
        self._load_synced_days()

    def _synced_days_path(self) -> Path:
        return self._config.state_dir / "synced_days.json"

    def _load_synced_days(self) -> None:
        path = self._synced_days_path()
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._synced_days = set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, OSError):
            self._synced_days = set()

    def _save_synced_days(self) -> None:
        self._config.state_dir.mkdir(parents=True, exist_ok=True)
        path = self._synced_days_path()
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(sorted(self._synced_days), f)
                f.write("\n")
            os.rename(str(tmp), str(path))
        except OSError as e:
            logger.warning(f"Failed to save synced days: {e}")

    def _prune_synced_days(self) -> None:
        """Remove synced-days entries older than 90 days."""
        if not self._synced_days:
            return
        cutoff = (datetime.now() - timedelta(days=SYNCED_DAYS_MAX_AGE)).strftime(
            "%Y%m%d"
        )
        before = len(self._synced_days)
        self._synced_days = {d for d in self._synced_days if d >= cutoff}
        pruned = before - len(self._synced_days)
        if pruned:
            logger.info(
                f"Pruned {pruned} synced-days entries older than {SYNCED_DAYS_MAX_AGE} days"
            )
            self._save_synced_days()

    def _quarantine_segment(self, segment_dir: Path, reason: str) -> bool:
        """Rename a segment directory to .failed so it's never retried."""
        failed_path = segment_dir.with_name(segment_dir.name + ".failed")
        try:
            segment_dir.rename(failed_path)
            logger.warning(
                "Quarantined %s/%s — %s",
                segment_dir.parent.parent.name,
                segment_dir.name,
                reason,
            )
            return True
        except OSError as e:
            logger.error("Failed to quarantine %s: %s", segment_dir, e)
            return False

    async def _cleanup_synced_segments(self) -> None:
        """Delete synced segments older than cache_retention_days.

        Triple-gated safety:
        1. Day must be in _synced_days (fully synced locally)
        2. Segment must be older than retention threshold (unless retention=0)
        3. Segment must be confirmed present on server (fresh query)
        """
        retention = self._config.cache_retention_days
        if retention < 0:
            return

        captures_dir = self._config.captures_dir
        if not captures_dir.exists():
            return

        today = datetime.now().strftime("%Y%m%d")
        if retention > 0:
            cutoff = (datetime.now() - timedelta(days=retention)).strftime("%Y%m%d")
        else:
            cutoff = today  # 0 means delete immediately — all days qualify

        deleted_total = 0

        for day_dir in sorted(captures_dir.iterdir()):
            if not day_dir.is_dir():
                continue

            day = day_dir.name

            if not self._running:
                break

            # Gate 1: day must be in synced_days
            if day not in self._synced_days:
                continue

            # Gate 2: day must be old enough (unless retention=0)
            if retention > 0 and day >= cutoff:
                continue

            # Don't clean today's segments
            if day == today:
                continue

            # Gate 3: fresh server confirmation
            server_segments = await asyncio.to_thread(
                self._client.get_server_segments, day
            )
            if server_segments is None:
                logger.warning("Cleanup: skipping day %s — server unreachable", day)
                continue

            server_keys: set[str] = set()
            for seg in server_segments:
                server_keys.add(seg.get("key", ""))
                if "original_key" in seg:
                    server_keys.add(seg["original_key"])

            deleted_day = 0

            for stream_dir in day_dir.iterdir():
                if not stream_dir.is_dir():
                    continue

                for seg_dir in sorted(stream_dir.iterdir()):
                    if not seg_dir.is_dir():
                        continue

                    name = seg_dir.name
                    # Never touch incomplete segments
                    if name.endswith(".incomplete"):
                        continue

                    # Delete quarantined (.failed) segments — no server confirmation needed
                    if name.endswith(".failed"):
                        shutil.rmtree(seg_dir)
                        logger.info("Cleanup: deleted quarantined %s/%s", day, name)
                        deleted_day += 1
                        continue

                    if name not in server_keys:
                        logger.warning(
                            "Cleanup: keeping %s/%s — not confirmed on server",
                            day,
                            name,
                        )
                        continue

                    shutil.rmtree(seg_dir)
                    logger.info("Cleanup: deleted %s/%s", day, name)
                    deleted_day += 1

                # Remove empty stream dir
                if stream_dir.is_dir() and not any(stream_dir.iterdir()):
                    stream_dir.rmdir()

            # Remove empty day dir
            if day_dir.is_dir() and not any(day_dir.iterdir()):
                day_dir.rmdir()

            if deleted_day:
                deleted_total += deleted_day

        if deleted_total:
            logger.info("Cleanup: deleted %d segment(s) total", deleted_total)

    def _circuit_threshold(self) -> int:
        """Get circuit breaker threshold based on last error type."""
        if self._last_error_type == ErrorType.AUTH:
            return CIRCUIT_THRESHOLD_AUTH
        return CIRCUIT_THRESHOLD_TRANSIENT

    def trigger(self) -> None:
        """Trigger a sync pass (called by observer on segment completion)."""
        self._trigger.set()

    def stop(self) -> None:
        """Stop the sync service."""
        self._running = False
        self._trigger.set()

    def _set_sync_status(self, status: str, progress: str = "") -> None:
        """Update sync status and emit D-Bus signal if changed."""
        changed = self.sync_status != status or self.sync_progress != progress
        self.sync_status = status
        self.sync_progress = progress
        if changed and self._dbus_service:
            self._dbus_service.SyncProgressChanged(f"{status}:{progress}")

    async def run(self) -> None:
        """Main sync loop — waits for triggers, then syncs."""
        # Prune on startup
        self._prune_synced_days()

        while self._running:
            try:
                # Wait for trigger or periodic check (60s timeout)
                try:
                    await asyncio.wait_for(self._trigger.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass

                self._trigger.clear()

                if not self._running:
                    break

                if self._circuit_open:
                    if self._circuit_open_permanent:
                        self._set_sync_status("offline")
                        logger.warning(
                            "Circuit breaker open (permanent) — skipping sync"
                        )
                        continue

                    elapsed = time.monotonic() - self._circuit_open_since
                    if elapsed < self._circuit_cooldown:
                        remaining = self._circuit_cooldown - elapsed
                        self._set_sync_status(
                            "retrying", f"{remaining:.0f}s until probe"
                        )
                        logger.warning(
                            f"Circuit breaker open — {remaining:.0f}s until probe"
                        )
                        continue

                    self._set_sync_status("retrying", "probing journal...")
                    logger.info("Circuit breaker half-open — probing server")
                    today = datetime.now().strftime("%Y%m%d")
                    probe_result = await asyncio.to_thread(
                        self._client.get_server_segments, today
                    )
                    if probe_result is not None:
                        logger.info("Circuit breaker probe succeeded — closing circuit")
                        self._circuit_open = False
                        self._circuit_open_permanent = False
                        self._circuit_open_since = 0.0
                        self._circuit_cooldown = CIRCUIT_COOLDOWN_INITIAL
                        self._consecutive_failures = 0
                        self._last_error_type = None
                        self._set_sync_status("syncing")
                    else:
                        self._circuit_cooldown = min(
                            self._circuit_cooldown * CIRCUIT_COOLDOWN_FACTOR,
                            CIRCUIT_COOLDOWN_MAX,
                        )
                        self._circuit_open_since = time.monotonic()
                        self._set_sync_status(
                            "retrying",
                            f"probe failed, next in {self._circuit_cooldown:.0f}s",
                        )
                        logger.warning(
                            f"Circuit breaker probe failed — next probe in {self._circuit_cooldown:.0f}s"
                        )
                        continue

                # Force full sync daily
                now = time.time()
                force_full = (now - self._last_full_sync) > 86400

                self._set_sync_status("syncing")
                await self._sync(force_full=force_full)
                self._set_sync_status("synced")

                if force_full:
                    self._last_full_sync = now

            except Exception as e:
                logger.error(f"Sync error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _sync(self, force_full: bool = False) -> None:
        """Walk days newest-to-oldest and upload missing segments."""
        captures_dir = self._config.captures_dir
        if not captures_dir.exists():
            return

        today = datetime.now().strftime("%Y%m%d")

        # Collect segments by day
        segments_by_day = self._collect_segments(captures_dir)
        if not segments_by_day:
            return

        for day in sorted(segments_by_day.keys(), reverse=True):
            if not self._running:
                break

            if self._circuit_open:
                break

            # Skip past days already fully synced (unless forcing)
            if day != today and day in self._synced_days and not force_full:
                continue

            local_segments = segments_by_day[day]

            # Query server for existing segments
            self._set_sync_status("syncing", f"checking {day}...")
            server_segments = await asyncio.to_thread(
                self._client.get_server_segments, day
            )
            if server_segments is None:
                logger.warning(f"Failed to query server for day {day}")
                continue

            # Build lookup
            server_keys: set[str] = set()
            for seg in server_segments:
                server_keys.add(seg.get("key", ""))
                if "original_key" in seg:
                    server_keys.add(seg["original_key"])

            any_needed_upload = False

            for segment_dir in local_segments:
                if not self._running or self._circuit_open:
                    break

                segment_key = segment_dir.name
                if segment_key in server_keys:
                    continue

                # Quarantine segments where all files are zero-byte (corrupt)
                files = [f for f in segment_dir.iterdir() if f.is_file()]
                if files and all(f.stat().st_size == 0 for f in files):
                    self._quarantine_segment(segment_dir, "all files zero-byte")
                    continue

                any_needed_upload = True
                self._set_sync_status("uploading", f"uploading {segment_key}")
                success = await self._upload_segment(day, segment_dir)

                if not success:
                    if self._last_error_type == ErrorType.CLIENT:
                        # Non-retryable client error (e.g. 400) — quarantine, don't trip circuit
                        self._quarantine_segment(
                            segment_dir, "server rejected (client error)"
                        )
                        continue

                    self._consecutive_failures += 1
                    threshold = self._circuit_threshold()
                    if self._consecutive_failures >= threshold:
                        self._circuit_open = True
                        self._circuit_open_since = time.monotonic()
                        self._circuit_cooldown = CIRCUIT_COOLDOWN_INITIAL
                        logger.error(
                            f"Circuit breaker OPEN: {self._consecutive_failures} consecutive "
                            f"{self._last_error_type.value if self._last_error_type else 'unknown'} "
                            f"failures (threshold: {threshold})"
                        )
                        self._set_sync_status("retrying")
                        break
                else:
                    self._consecutive_failures = 0
                    self._last_error_type = None

            # Mark past days as synced if nothing needed upload
            if day != today and not any_needed_upload:
                self._synced_days.add(day)
                self._save_synced_days()

        # Cleanup old synced segments
        if not self._circuit_open and self._running:
            try:
                await self._cleanup_synced_segments()
            except Exception as e:
                logger.error(f"Cleanup error: {e}", exc_info=True)

    def _collect_segments(self, captures_dir: Path) -> dict[str, list[Path]]:
        """Collect completed segments grouped by day."""
        result: dict[str, list[Path]] = {}

        for day_dir in sorted(captures_dir.iterdir(), reverse=True):
            if not day_dir.is_dir():
                continue

            day = day_dir.name

            for stream_dir in day_dir.iterdir():
                if not stream_dir.is_dir():
                    continue

                segments = []
                for seg_dir in sorted(stream_dir.iterdir(), reverse=True):
                    if not seg_dir.is_dir():
                        continue
                    name = seg_dir.name
                    # Skip incomplete and failed
                    if name.endswith(".incomplete") or name.endswith(".failed"):
                        continue
                    segments.append(seg_dir)

                if segments:
                    result.setdefault(day, []).extend(segments)

        return result

    async def _upload_segment(self, day: str, segment_dir: Path) -> bool:
        """Upload a single segment with retry logic."""
        segment_key = segment_dir.name
        files = [f for f in segment_dir.iterdir() if f.is_file()]
        if not files:
            return True  # Nothing to upload

        meta: dict[str, Any] = {"stream": self._config.stream}

        result = await asyncio.to_thread(
            self._client.upload_segment, day, segment_key, files, meta
        )

        if result.success:
            logger.info(f"Uploaded: {day}/{segment_key} ({len(files)} files)")
            return True

        # Track error type for circuit breaker
        self._last_error_type = result.error_type

        # Non-retryable errors
        if self._client.is_revoked:
            logger.error("Client revoked — disabling sync")
            self._circuit_open = True
            self._circuit_open_permanent = True
            return False

        logger.error(f"Upload failed: {day}/{segment_key}")
        return False
