# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Tests for portal screencast stream matching."""

from solstone_linux.screencast import _match_streams_to_monitors


class TestMatchStreamsToMonitors:
    """Test matching portal streams to monitor metadata."""

    def test_position_based_matching(self):
        streams = [
            {
                "idx": 0,
                "node_id": 10,
                "props": {"position": (0, 0), "size": (1920, 1080)},
            },
            {
                "idx": 1,
                "node_id": 11,
                "props": {"position": (1920, 0), "size": (2560, 1440)},
            },
        ]
        monitors = [
            {"id": "DP-1", "box": [0, 0, 1920, 1080], "position": "left"},
            {"id": "DP-2", "box": [1920, 0, 4480, 1440], "position": "right"},
        ]

        result = _match_streams_to_monitors(streams, monitors)

        assert result[0]["connector"] == "DP-1"
        assert result[0]["position_label"] == "left"
        assert result[0]["x"] == 0
        assert result[0]["y"] == 0
        assert result[0]["width"] == 1920
        assert result[0]["height"] == 1080
        assert result[1]["connector"] == "DP-2"
        assert result[1]["position_label"] == "right"
        assert result[1]["x"] == 1920
        assert result[1]["y"] == 0
        assert result[1]["width"] == 2560
        assert result[1]["height"] == 1440

    def test_size_based_fallback_when_no_position(self):
        streams = [
            {
                "idx": 0,
                "node_id": 10,
                "props": {"position": (0, 0), "size": (1920, 1080)},
            },
            {
                "idx": 1,
                "node_id": 11,
                "props": {"position": (0, 0), "size": (2560, 1440)},
            },
        ]
        monitors = [
            {"id": "DP-1", "box": [20, 0, 1940, 1080], "position": "left"},
            {"id": "DP-2", "box": [1940, 0, 4500, 1440], "position": "right"},
        ]

        result = _match_streams_to_monitors(streams, monitors)

        assert result[0]["connector"] == "DP-1"
        assert result[0]["position_label"] == "left"
        assert result[0]["x"] == 20
        assert result[0]["width"] == 1920
        assert result[1]["connector"] == "DP-2"
        assert result[1]["position_label"] == "right"
        assert result[1]["x"] == 1940
        assert result[1]["width"] == 2560

    def test_position_match_skipped_when_all_zero(self):
        streams = [
            {
                "idx": 0,
                "node_id": 10,
                "props": {"position": (0, 0), "size": (2560, 1440)},
            },
            {
                "idx": 1,
                "node_id": 11,
                "props": {"position": (0, 0), "size": (1920, 1080)},
            },
        ]
        monitors = [
            {"id": "DP-1", "box": [0, 0, 1920, 1080], "position": "left"},
            {"id": "DP-2", "box": [1920, 0, 4480, 1440], "position": "right"},
        ]

        result = _match_streams_to_monitors(streams, monitors)

        assert result[0]["connector"] == "DP-2"
        assert result[0]["position_label"] == "right"
        assert result[0]["x"] == 1920
        assert result[0]["width"] == 2560
        assert result[1]["connector"] == "DP-1"
        assert result[1]["position_label"] == "left"
        assert result[1]["x"] == 0
        assert result[1]["width"] == 1920

    def test_ambiguous_size_assigns_in_order(self):
        streams = [
            {
                "idx": 0,
                "node_id": 10,
                "props": {"position": (0, 0), "size": (1920, 1080)},
            },
            {
                "idx": 1,
                "node_id": 11,
                "props": {"position": (0, 0), "size": (1920, 1080)},
            },
        ]
        monitors = [
            {"id": "DP-1", "box": [20, 0, 1940, 1080], "position": "left"},
            {"id": "DP-2", "box": [1940, 0, 3860, 1080], "position": "right"},
        ]

        result = _match_streams_to_monitors(streams, monitors)

        assert result[0]["connector"] == "DP-1"
        assert result[1]["connector"] == "DP-2"

    def test_no_monitors_falls_back_to_monitor_idx(self):
        streams = [
            {
                "idx": 0,
                "node_id": 10,
                "props": {"position": (0, 0), "size": (1920, 1080)},
            },
            {
                "idx": 1,
                "node_id": 11,
                "props": {"position": (1920, 0), "size": (2560, 1440)},
            },
        ]

        result = _match_streams_to_monitors(streams, [])

        assert result[0]["connector"] == "monitor-0"
        assert result[0]["position_label"] == "unknown"
        assert result[1]["connector"] == "monitor-1"
        assert result[1]["position_label"] == "unknown"

    def test_mixed_position_and_size_matching(self):
        streams = [
            {
                "idx": 0,
                "node_id": 10,
                "props": {"position": (0, 0), "size": (1920, 1080)},
            },
            {
                "idx": 1,
                "node_id": 11,
                "props": {"position": (0, 0), "size": (2560, 1440)},
            },
        ]
        monitors = [
            {"id": "DP-1", "box": [0, 0, 1920, 1080], "position": "left"},
            {"id": "DP-2", "box": [1920, 0, 4480, 1440], "position": "right"},
        ]

        result = _match_streams_to_monitors(streams, monitors)

        assert result[0]["connector"] == "DP-1"
        assert result[0]["position_label"] == "left"
        assert result[1]["connector"] == "DP-2"
        assert result[1]["position_label"] == "right"
