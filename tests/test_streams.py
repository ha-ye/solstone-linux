# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import pytest

from solstone_linux.streams import _strip_hostname, stream_name


class TestStripHostname:
    def test_simple(self):
        assert _strip_hostname("archon") == "archon"

    def test_with_domain(self):
        assert _strip_hostname("ja1r.local") == "ja1r"

    def test_ip_address(self):
        assert _strip_hostname("192.168.1.1") == "192-168-1-1"

    def test_fqdn(self):
        assert _strip_hostname("my.host.example.com") == "my"

    def test_empty(self):
        assert _strip_hostname("") == ""


class TestStreamName:
    def test_host_only(self):
        assert stream_name(host="archon") == "archon"

    def test_host_with_qualifier(self):
        assert stream_name(host="archon", qualifier="tmux") == "archon.tmux"

    def test_host_no_qualifier(self):
        # Linux observer uses host without qualifier
        assert stream_name(host="archon") == "archon"

    def test_observer(self):
        assert stream_name(observer="desktop") == "desktop"

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            stream_name()

    def test_rejects_invalid_chars(self):
        with pytest.raises(ValueError):
            stream_name(host="!invalid")
