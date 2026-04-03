# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Linux audio mute detection using PulseAudio/PipeWire.

Direct copy from solstone's observe/linux/audio.py — no solstone imports.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def is_sink_muted() -> bool:
    """
    Check if the default audio sink is muted using PulseAudio.

    Uses `pactl get-sink-mute @DEFAULT_SINK@` to query mute status.

    Returns:
        True if muted, False otherwise (including on error).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl",
            "get-sink-mute",
            "@DEFAULT_SINK@",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr.decode().strip() if stderr else ""
            logger.warning(f"pactl failed (rc={proc.returncode}): {stderr_text}")
            return False

        output = stdout.decode().strip()
        return "Mute: yes" in output

    except FileNotFoundError:
        logger.warning("pactl not found, assuming unmuted")
        return False
    except Exception as e:
        logger.warning(f"Error checking sink mute status: {e}")
        return False
