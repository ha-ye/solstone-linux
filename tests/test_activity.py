# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

"""Tests for desktop activity detection fallbacks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from solstone_linux import activity


def _make_proxy(interface_name: str, iface: object) -> MagicMock:
    proxy = MagicMock()
    proxy.get_interface.side_effect = lambda name: (
        iface if name == interface_name else None
    )
    return proxy


@pytest.mark.asyncio
async def test_is_screen_locked_prefers_fdo_true():
    bus = MagicMock()
    fdo_iface = AsyncMock()
    fdo_iface.call_get_active.return_value = True
    bus.introspect = AsyncMock(return_value="fdo-intro")
    bus.get_proxy_object.return_value = _make_proxy(
        activity.FDO_SCREENSAVER_IFACE, fdo_iface
    )

    result = await activity.is_screen_locked(bus)

    assert result is True
    bus.introspect.assert_awaited_once_with(
        activity.FDO_SCREENSAVER_BUS, activity.FDO_SCREENSAVER_PATH
    )
    fdo_iface.call_get_active.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_is_screen_locked_prefers_fdo_false():
    bus = MagicMock()
    fdo_iface = AsyncMock()
    fdo_iface.call_get_active.return_value = False
    bus.introspect = AsyncMock(return_value="fdo-intro")
    bus.get_proxy_object.return_value = _make_proxy(
        activity.FDO_SCREENSAVER_IFACE, fdo_iface
    )

    result = await activity.is_screen_locked(bus)

    assert result is False
    bus.introspect.assert_awaited_once_with(
        activity.FDO_SCREENSAVER_BUS, activity.FDO_SCREENSAVER_PATH
    )
    fdo_iface.call_get_active.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_is_screen_locked_falls_back_to_gnome():
    bus = MagicMock()
    gnome_iface = AsyncMock()
    gnome_iface.call_get_active.return_value = True
    bus.introspect = AsyncMock(
        side_effect=[Exception("fdo unavailable"), "gnome-intro"]
    )

    def get_proxy_object(bus_name: str, path: str, intro: str) -> MagicMock:
        assert (bus_name, path, intro) == (
            activity.GNOME_SCREENSAVER_BUS,
            activity.GNOME_SCREENSAVER_PATH,
            "gnome-intro",
        )
        return _make_proxy(activity.GNOME_SCREENSAVER_IFACE, gnome_iface)

    bus.get_proxy_object.side_effect = get_proxy_object

    result = await activity.is_screen_locked(bus)

    assert result is True
    assert bus.introspect.await_args_list == [
        ((activity.FDO_SCREENSAVER_BUS, activity.FDO_SCREENSAVER_PATH),),
        ((activity.GNOME_SCREENSAVER_BUS, activity.GNOME_SCREENSAVER_PATH),),
    ]
    gnome_iface.call_get_active.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_is_screen_locked_returns_false_when_all_backends_fail():
    bus = MagicMock()
    bus.introspect = AsyncMock(side_effect=Exception("unavailable"))

    result = await activity.is_screen_locked(bus)

    assert result is False
    assert bus.introspect.await_count == 2


@pytest.mark.asyncio
async def test_is_power_save_active_uses_gnome_display_config_when_nonzero():
    bus = MagicMock()
    props_iface = AsyncMock()
    props_iface.call_get.return_value = SimpleNamespace(value=2)
    bus.introspect = AsyncMock(return_value="display-intro")
    bus.get_proxy_object.return_value = _make_proxy(
        "org.freedesktop.DBus.Properties", props_iface
    )

    result = await activity.is_power_save_active(bus)

    assert result is True
    bus.introspect.assert_awaited_once_with(
        activity.DISPLAY_CONFIG_BUS, activity.DISPLAY_CONFIG_PATH
    )
    props_iface.call_get.assert_awaited_once_with(
        activity.DISPLAY_CONFIG_IFACE, "PowerSaveMode"
    )


@pytest.mark.asyncio
async def test_is_power_save_active_uses_gnome_display_config_when_zero():
    bus = MagicMock()
    props_iface = AsyncMock()
    props_iface.call_get.return_value = SimpleNamespace(value=0)
    bus.introspect = AsyncMock(return_value="display-intro")
    bus.get_proxy_object.return_value = _make_proxy(
        "org.freedesktop.DBus.Properties", props_iface
    )

    result = await activity.is_power_save_active(bus)

    assert result is False
    bus.introspect.assert_awaited_once_with(
        activity.DISPLAY_CONFIG_BUS, activity.DISPLAY_CONFIG_PATH
    )
    props_iface.call_get.assert_awaited_once_with(
        activity.DISPLAY_CONFIG_IFACE, "PowerSaveMode"
    )


@pytest.mark.asyncio
async def test_is_power_save_active_falls_back_to_kde():
    bus = MagicMock()
    kde_iface = AsyncMock()
    kde_iface.call_is_lid_closed.return_value = True
    bus.introspect = AsyncMock(
        side_effect=[Exception("gnome unavailable"), "kde-intro"]
    )

    def get_proxy_object(bus_name: str, path: str, intro: str) -> MagicMock:
        assert (bus_name, path, intro) == (
            activity.KDE_POWER_BUS,
            activity.KDE_POWER_PATH,
            "kde-intro",
        )
        return _make_proxy(activity.KDE_POWER_IFACE, kde_iface)

    bus.get_proxy_object.side_effect = get_proxy_object

    result = await activity.is_power_save_active(bus)

    assert result is True
    assert bus.introspect.await_args_list == [
        ((activity.DISPLAY_CONFIG_BUS, activity.DISPLAY_CONFIG_PATH),),
        ((activity.KDE_POWER_BUS, activity.KDE_POWER_PATH),),
    ]
    kde_iface.call_is_lid_closed.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_is_power_save_active_returns_false_when_all_backends_fail():
    bus = MagicMock()
    bus.introspect = AsyncMock(side_effect=Exception("unavailable"))

    result = await activity.is_power_save_active(bus)

    assert result is False
    assert bus.introspect.await_count == 2


@pytest.mark.asyncio
async def test_probe_activity_services_all_available():
    bus = MagicMock()
    bus.introspect = AsyncMock(return_value="intro")

    results = await activity.probe_activity_services(bus)

    assert results["fdo_screensaver"] is True
    assert results["gnome_screensaver"] is True
    assert results["gnome_display_config"] is True
    assert results["kde_power"] is True
    assert results["gtk4"] is activity._HAS_GTK


@pytest.mark.asyncio
async def test_probe_activity_services_all_unavailable():
    bus = MagicMock()
    bus.introspect = AsyncMock(side_effect=Exception("unavailable"))

    results = await activity.probe_activity_services(bus)

    assert results["fdo_screensaver"] is False
    assert results["gnome_screensaver"] is False
    assert results["gnome_display_config"] is False
    assert results["kde_power"] is False
    assert results["gtk4"] is activity._HAS_GTK


@pytest.mark.asyncio
async def test_probe_activity_services_mixed_availability():
    bus = MagicMock()

    async def introspect(bus_name: str, path: str) -> str:
        if bus_name in {activity.FDO_SCREENSAVER_BUS, activity.KDE_POWER_BUS}:
            return "intro"
        raise Exception(f"{bus_name} unavailable")

    bus.introspect = AsyncMock(side_effect=introspect)

    results = await activity.probe_activity_services(bus)

    assert results["fdo_screensaver"] is True
    assert results["gnome_screensaver"] is False
    assert results["gnome_display_config"] is False
    assert results["kde_power"] is True
    assert results["gtk4"] is activity._HAS_GTK
