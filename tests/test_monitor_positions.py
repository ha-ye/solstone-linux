# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from solstone_linux.monitor_positions import assign_monitor_positions


class TestAssignMonitorPositions:
    def test_single_monitor(self):
        monitors = [{"id": "DP-1", "box": [0, 0, 1920, 1080]}]
        result = assign_monitor_positions(monitors)
        assert result[0]["position"] == "center"

    def test_two_horizontal(self):
        monitors = [
            {"id": "DP-1", "box": [0, 0, 1920, 1080]},
            {"id": "DP-2", "box": [1920, 0, 3840, 1080]},
        ]
        result = assign_monitor_positions(monitors)
        positions = {m["id"]: m["position"] for m in result}
        assert positions["DP-1"] == "left"
        assert positions["DP-2"] == "right"

    def test_three_horizontal(self):
        monitors = [
            {"id": "DP-1", "box": [0, 0, 1920, 1080]},
            {"id": "DP-2", "box": [1920, 0, 3840, 1080]},
            {"id": "DP-3", "box": [3840, 0, 5760, 1080]},
        ]
        result = assign_monitor_positions(monitors)
        positions = {m["id"]: m["position"] for m in result}
        assert positions["DP-1"] == "left"
        assert positions["DP-2"] == "center"
        assert positions["DP-3"] == "right"

    def test_stacked_vertical(self):
        monitors = [
            {"id": "DP-1", "box": [0, 0, 1920, 1080]},
            {"id": "DP-2", "box": [0, 1080, 1920, 2160]},
        ]
        result = assign_monitor_positions(monitors)
        positions = {m["id"]: m["position"] for m in result}
        assert positions["DP-1"] == "top"
        assert positions["DP-2"] == "bottom"

    def test_empty(self):
        assert assign_monitor_positions([]) == []

    def test_offset_monitors_no_phantom_vertical(self):
        # Two side-by-side monitors that don't overlap horizontally
        # should NOT get vertical labels
        monitors = [
            {"id": "DP-1", "box": [0, 0, 1920, 1080]},
            {"id": "DP-2", "box": [1920, 200, 3840, 1280]},
        ]
        result = assign_monitor_positions(monitors)
        positions = {m["id"]: m["position"] for m in result}
        assert positions["DP-1"] == "left"
        assert positions["DP-2"] == "right"
