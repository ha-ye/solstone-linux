# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Monitor position assignment based on geometry.

Extracted from solstone's observe/utils.py — the assign_monitor_positions()
function only. Also remains in solstone core (used by server-side naming).
"""

from __future__ import annotations


def assign_monitor_positions(monitors: list[dict]) -> list[dict]:
    """
    Assign position labels to monitors based on relative positions.

    Uses pairwise comparison to determine positions. Vertical labels (top/bottom)
    are only assigned when monitors actually overlap horizontally, avoiding
    phantom relationships from offset monitors.

    Parameters
    ----------
    monitors : list[dict]
        List of monitor dicts, each with keys:
        - id: Monitor identifier (e.g., "DP-3", "HDMI-1")
        - box: [x1, y1, x2, y2] coordinates

    Returns
    -------
    list[dict]
        Same monitors with "position" key added to each:
        - "center": No monitors on both sides
        - "left"/"right": Horizontal position
        - "top"/"bottom": Vertical position (only with horizontal overlap)
        - "left-top", "right-bottom", etc.: Corner positions
    """
    if not monitors:
        return []

    if len(monitors) == 1:
        monitors[0]["position"] = "center"
        return monitors

    # Tolerance for center classification
    epsilon = 1

    for m in monitors:
        x1, y1, x2, y2 = m["box"]
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        has_left = False
        has_right = False
        has_above = False
        has_below = False

        for other in monitors:
            if other is m:
                continue

            ox1, oy1, ox2, oy2 = other["box"]
            other_center_x = (ox1 + ox2) / 2
            other_center_y = (oy1 + oy2) / 2

            # Horizontal relationship (always check)
            if other_center_x < center_x - epsilon:
                has_left = True
            elif other_center_x > center_x + epsilon:
                has_right = True

            # Vertical relationship only if horizontal overlap exists
            # Overlap means ranges intersect (not just touch)
            h_overlap = (x1 < ox2) and (x2 > ox1)
            if h_overlap:
                if other_center_y < center_y - epsilon:
                    has_above = True
                elif other_center_y > center_y + epsilon:
                    has_below = True

        # Determine horizontal label
        if has_left and has_right:
            h_pos = "center"
        elif has_left:
            h_pos = "right"
        elif has_right:
            h_pos = "left"
        else:
            h_pos = "center"

        # Determine vertical label (only if monitors above/below with overlap)
        if has_above and has_below:
            v_pos = "middle"
        elif has_above:
            v_pos = "bottom"
        elif has_below:
            v_pos = "top"
        else:
            v_pos = None

        # Combine positions
        if v_pos is None:
            position = h_pos
        elif h_pos == "center":
            position = v_pos
        else:
            position = f"{h_pos}-{v_pos}"

        m["position"] = position

    return monitors
