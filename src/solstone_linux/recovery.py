# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Crash recovery for orphaned .incomplete segment directories.

Modeled on solstone-macos's IncompleteSegmentRecovery.swift.
Runs on startup before the capture loop begins.

Improvement over tmux baseline: reads .metadata JSON file for accurate
start timestamp instead of relying on brittle filesystem timestamps.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Segments newer than this are assumed to be actively recording
MINIMUM_AGE_SECONDS = 120  # 2 minutes

METADATA_FILENAME = ".metadata"


def write_segment_metadata(segment_dir: Path, start_timestamp: float) -> None:
    """Write metadata file inside a segment directory.

    Called when creating a new .incomplete segment so recovery can
    use the actual start timestamp instead of filesystem timestamps.
    """
    meta_path = segment_dir / METADATA_FILENAME
    try:
        data = {"start_timestamp": start_timestamp}
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.write("\n")
    except OSError as e:
        logger.warning(f"Failed to write segment metadata: {e}")


def _read_segment_metadata(segment_dir: Path) -> dict | None:
    """Read metadata file from a segment directory."""
    meta_path = segment_dir / METADATA_FILENAME
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def recover_incomplete_segments(captures_dir: Path) -> int:
    """Scan captures dir for orphaned .incomplete directories and finalize them.

    For each .incomplete directory older than 2 minutes:
    - Read .metadata for start timestamp if available, else fall back to
      filesystem timestamps (mtime - ctime)
    - Rename to HHMMSS_DDD/ format
    - If recovery fails, rename to HHMMSS.failed/ to prevent infinite retry

    Returns the number of successfully recovered segments.
    """
    if not captures_dir.exists():
        return 0

    recovered = 0
    now = time.time()

    for day_dir in sorted(captures_dir.iterdir()):
        if not day_dir.is_dir():
            continue

        for stream_dir in sorted(day_dir.iterdir()):
            if not stream_dir.is_dir():
                continue

            for segment_dir in sorted(stream_dir.iterdir()):
                if not segment_dir.is_dir():
                    continue

                dir_name = segment_dir.name
                if not dir_name.endswith(".incomplete"):
                    continue

                # Check age
                try:
                    dir_stat = segment_dir.stat()
                    age = now - dir_stat.st_mtime
                    if age < MINIMUM_AGE_SECONDS:
                        logger.debug(f"Skipping recent incomplete: {dir_name}")
                        continue
                except OSError:
                    continue

                logger.info(f"Recovering incomplete segment: {dir_name}")
                if _recover_segment(segment_dir):
                    recovered += 1

    if recovered:
        logger.info(f"Recovered {recovered} incomplete segment(s)")
    return recovered


def _recover_segment(segment_dir: Path) -> bool:
    """Recover a single incomplete segment directory.

    Returns True on success.
    """
    dir_name = segment_dir.name
    time_prefix = dir_name.removesuffix(".incomplete")

    # Try .metadata first for accurate duration
    metadata = _read_segment_metadata(segment_dir)
    if metadata and "start_timestamp" in metadata:
        start_ts = metadata["start_timestamp"]
        duration = max(1, int(time.time() - start_ts))
    else:
        # Fall back to filesystem timestamps
        try:
            st = segment_dir.stat()
            duration = max(1, int(st.st_mtime - st.st_ctime))
        except OSError:
            return _mark_failed(segment_dir)

    # Check there are actual files inside (ignore .metadata)
    try:
        contents = [f for f in segment_dir.iterdir() if f.name != METADATA_FILENAME]
        if not contents:
            logger.warning(f"Empty incomplete segment: {dir_name}")
            return _mark_failed(segment_dir)
    except OSError:
        return _mark_failed(segment_dir)

    # Build final segment key with duration
    segment_key = f"{time_prefix}_{duration}"
    final_dir = segment_dir.parent / segment_key

    # Remove .metadata before finalizing (not a capture artifact)
    meta_path = segment_dir / METADATA_FILENAME
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError:
            pass

    try:
        os.rename(str(segment_dir), str(final_dir))
        logger.info(f"Recovered: {dir_name} -> {segment_key}")
        return True
    except OSError as e:
        logger.warning(f"Failed to rename {dir_name}: {e}")
        return _mark_failed(segment_dir)


def _mark_failed(segment_dir: Path) -> bool:
    """Rename from .incomplete to .failed to prevent infinite retry."""
    dir_name = segment_dir.name
    if not dir_name.endswith(".incomplete"):
        return False

    failed_name = dir_name.removesuffix(".incomplete") + ".failed"
    failed_dir = segment_dir.parent / failed_name

    try:
        os.rename(str(segment_dir), str(failed_dir))
        logger.warning(f"Marked as failed: {dir_name} -> {failed_name}")
    except OSError as e:
        logger.error(f"Failed to mark as failed: {e}")

    return False
