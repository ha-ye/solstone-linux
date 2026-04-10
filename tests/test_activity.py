# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Tests for cross-desktop activity detection backends."""

import logging
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from solstone_linux import activity


def _make_proxy_with_interface(interface: MagicMock) -> MagicMock:
    proxy = MagicMock()
    proxy.get_interface.return_value = interface
    return proxy


def _make_variant(value: int) -> MagicMock:
    variant = MagicMock()
    variant.value = value
    return variant


class TestIsScreenLocked:
    """Test screen lock fallback order."""

    @pytest.mark.asyncio
    async def test_fdo_backend_returns_true_without_gnome_fallback(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(return_value=object())
        iface = MagicMock()
        iface.call_get_active = AsyncMock(return_value=True)
        bus.get_proxy_object.return_value = _make_proxy_with_interface(iface)

        result = await activity.is_screen_locked(bus)

        assert result is True
        assert bus.introspect.await_count == 1
        bus.introspect.assert_awaited_once_with(
            activity.FDO_SCREENSAVER_BUS, activity.FDO_SCREENSAVER_PATH
        )

    @pytest.mark.asyncio
    async def test_fdo_backend_returns_false_without_gnome_fallback(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(return_value=object())
        iface = MagicMock()
        iface.call_get_active = AsyncMock(return_value=False)
        bus.get_proxy_object.return_value = _make_proxy_with_interface(iface)

        result = await activity.is_screen_locked(bus)

        assert result is False
        assert bus.introspect.await_count == 1
        bus.introspect.assert_awaited_once_with(
            activity.FDO_SCREENSAVER_BUS, activity.FDO_SCREENSAVER_PATH
        )

    @pytest.mark.asyncio
    async def test_fdo_failure_gnome_returns_true(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(side_effect=[Exception("fdo unavailable"), object()])
        gnome_iface = MagicMock()
        gnome_iface.call_get_active = AsyncMock(return_value=True)
        bus.get_proxy_object.return_value = _make_proxy_with_interface(gnome_iface)

        result = await activity.is_screen_locked(bus)

        assert result is True
        assert bus.introspect.await_args_list == [
            call(activity.FDO_SCREENSAVER_BUS, activity.FDO_SCREENSAVER_PATH),
            call(activity.GNOME_SCREENSAVER_BUS, activity.GNOME_SCREENSAVER_PATH),
        ]

    @pytest.mark.asyncio
    async def test_fdo_failure_gnome_returns_false(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(side_effect=[Exception("fdo unavailable"), object()])
        gnome_iface = MagicMock()
        gnome_iface.call_get_active = AsyncMock(return_value=False)
        bus.get_proxy_object.return_value = _make_proxy_with_interface(gnome_iface)

        result = await activity.is_screen_locked(bus)

        assert result is False
        assert bus.introspect.await_args_list == [
            call(activity.FDO_SCREENSAVER_BUS, activity.FDO_SCREENSAVER_PATH),
            call(activity.GNOME_SCREENSAVER_BUS, activity.GNOME_SCREENSAVER_PATH),
        ]

    @pytest.mark.asyncio
    async def test_both_backends_fail_returns_false(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(
            side_effect=[Exception("fdo unavailable"), Exception("gnome unavailable")]
        )

        result = await activity.is_screen_locked(bus)

        assert result is False
        assert bus.introspect.await_args_list == [
            call(activity.FDO_SCREENSAVER_BUS, activity.FDO_SCREENSAVER_PATH),
            call(activity.GNOME_SCREENSAVER_BUS, activity.GNOME_SCREENSAVER_PATH),
        ]


class TestIsPowerSaveActive:
    """Test power save fallback order."""

    @pytest.mark.asyncio
    async def test_gnome_backend_nonzero_mode_returns_true(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(return_value=object())
        iface = MagicMock()
        iface.call_get = AsyncMock(return_value=_make_variant(2))
        bus.get_proxy_object.return_value = _make_proxy_with_interface(iface)

        result = await activity.is_power_save_active(bus)

        assert result is True
        bus.introspect.assert_awaited_once_with(
            activity.DISPLAY_CONFIG_BUS, activity.DISPLAY_CONFIG_PATH
        )

    @pytest.mark.asyncio
    async def test_gnome_backend_zero_mode_returns_false(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(return_value=object())
        iface = MagicMock()
        iface.call_get = AsyncMock(return_value=_make_variant(0))
        bus.get_proxy_object.return_value = _make_proxy_with_interface(iface)

        result = await activity.is_power_save_active(bus)

        assert result is False
        bus.introspect.assert_awaited_once_with(
            activity.DISPLAY_CONFIG_BUS, activity.DISPLAY_CONFIG_PATH
        )

    @pytest.mark.asyncio
    async def test_gnome_failure_kde_lid_closed_returns_true(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(
            side_effect=[Exception("gnome unavailable"), object()]
        )
        kde_iface = MagicMock()
        kde_iface.call_is_lid_closed = AsyncMock(return_value=True)
        bus.get_proxy_object.return_value = _make_proxy_with_interface(kde_iface)

        result = await activity.is_power_save_active(bus)

        assert result is True
        assert bus.introspect.await_args_list == [
            call(activity.DISPLAY_CONFIG_BUS, activity.DISPLAY_CONFIG_PATH),
            call(activity.KDE_POWER_BUS, activity.KDE_POWER_PATH),
        ]

    @pytest.mark.asyncio
    async def test_gnome_failure_kde_lid_open_returns_false(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(
            side_effect=[Exception("gnome unavailable"), object()]
        )
        kde_iface = MagicMock()
        kde_iface.call_is_lid_closed = AsyncMock(return_value=False)
        bus.get_proxy_object.return_value = _make_proxy_with_interface(kde_iface)

        result = await activity.is_power_save_active(bus)

        assert result is False
        assert bus.introspect.await_args_list == [
            call(activity.DISPLAY_CONFIG_BUS, activity.DISPLAY_CONFIG_PATH),
            call(activity.KDE_POWER_BUS, activity.KDE_POWER_PATH),
        ]

    @pytest.mark.asyncio
    async def test_both_backends_fail_returns_false(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(
            side_effect=[Exception("gnome unavailable"), Exception("kde unavailable")]
        )

        result = await activity.is_power_save_active(bus)

        assert result is False
        assert bus.introspect.await_args_list == [
            call(activity.DISPLAY_CONFIG_BUS, activity.DISPLAY_CONFIG_PATH),
            call(activity.KDE_POWER_BUS, activity.KDE_POWER_PATH),
        ]


class TestProbeActivityServices:
    """Test activity backend probing and logging."""

    @pytest.mark.asyncio
    async def test_all_services_available_returns_true_results(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(return_value=object())

        results = await activity.probe_activity_services(bus)

        assert results["fdo_screensaver"] is True
        assert results["gnome_screensaver"] is True
        assert results["gnome_display_config"] is True
        assert results["kde_power"] is True
        assert results["gtk4"] is activity._HAS_GTK

    @pytest.mark.asyncio
    async def test_no_services_available_logs_warning(self, caplog):
        bus = MagicMock()
        bus.introspect = AsyncMock(side_effect=Exception("missing"))

        with caplog.at_level(logging.WARNING):
            results = await activity.probe_activity_services(bus)

        assert results["fdo_screensaver"] is False
        assert results["gnome_screensaver"] is False
        assert results["gnome_display_config"] is False
        assert results["kde_power"] is False
        assert "No activity backends available" in caplog.text

    @pytest.mark.asyncio
    async def test_mixed_service_availability_returns_correct_results(self):
        bus = MagicMock()
        bus.introspect = AsyncMock(
            side_effect=[
                object(),
                Exception("missing"),
                object(),
                Exception("missing"),
            ]
        )

        results = await activity.probe_activity_services(bus)

        assert results["fdo_screensaver"] is True
        assert results["gnome_screensaver"] is False
        assert results["gnome_display_config"] is True
        assert results["kde_power"] is False
