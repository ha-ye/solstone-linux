# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

import sys

import pytest

from solstone_linux import doctor


def _set_all_checks(
    monkeypatch,
    *,
    python_result=None,
    gtk_result=None,
    gstreamer_result=None,
    cairo_result=None,
    pipewire_result=None,
    portal_result=None,
    systemd_result=None,
    pipx_result=None,
    appindicator_result=None,
):
    monkeypatch.setattr(
        doctor,
        "check_python_version",
        lambda: python_result or doctor.CheckResult("python version", "ok", ""),
    )
    monkeypatch.setattr(
        doctor,
        "check_gtk4_typelib",
        lambda: gtk_result or doctor.CheckResult("gtk4 typelib", "ok", ""),
    )
    monkeypatch.setattr(
        doctor,
        "check_gstreamer",
        lambda: gstreamer_result or doctor.CheckResult("gstreamer", "ok", ""),
    )
    monkeypatch.setattr(
        doctor,
        "check_cairo",
        lambda: cairo_result or doctor.CheckResult("cairo binding", "ok", ""),
    )
    monkeypatch.setattr(
        doctor,
        "check_pipewire",
        lambda: pipewire_result or doctor.CheckResult("pipewire (pactl)", "ok", ""),
    )

    async def _portal():
        return portal_result or doctor.CheckResult("xdg-desktop-portal", "ok", "")

    monkeypatch.setattr(doctor, "check_portal", _portal)
    monkeypatch.setattr(
        doctor,
        "check_user_systemd",
        lambda: systemd_result or doctor.CheckResult("systemd --user", "ok", ""),
    )
    monkeypatch.setattr(
        doctor,
        "check_pipx",
        lambda: pipx_result or doctor.CheckResult("pipx", "ok", ""),
    )
    monkeypatch.setattr(
        doctor,
        "check_appindicator_ext",
        lambda: (
            appindicator_result
            or doctor.CheckResult("appindicator ext (soft)", "ok", "")
        ),
    )


def test_run_doctor_all_pass_returns_zero(monkeypatch, capsys):
    _set_all_checks(monkeypatch)

    assert doctor.run_doctor() == 0

    captured = capsys.readouterr()
    assert "python version" in captured.out
    assert "gtk4 typelib" in captured.out
    assert "doctor: 9 checks, 0 failed, 0 warnings" in captured.out


def test_run_doctor_any_fail_returns_one(monkeypatch):
    _set_all_checks(
        monkeypatch,
        pipx_result=doctor.CheckResult("pipx", "fail", "missing"),
    )

    assert doctor.run_doctor() == 1


def test_run_doctor_warn_only_returns_zero(monkeypatch):
    _set_all_checks(
        monkeypatch,
        appindicator_result=doctor.CheckResult(
            "appindicator ext (soft)",
            "warn",
            "install gnome-shell-extension-appindicator",
        ),
    )

    assert doctor.run_doctor() == 0


def test_check_exception_renders_as_fail(monkeypatch, capsys):
    _set_all_checks(monkeypatch)

    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "check_pipx", _boom)

    assert doctor.run_doctor() == 1

    captured = capsys.readouterr()
    assert "RuntimeError" in captured.out
    assert "boom" in captured.out


def test_python_version_old_fails(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 9, 0, "final", 0))

    result = doctor.check_python_version()

    assert result.severity == "fail"
    assert "3.10" in result.detail


def test_python_version_current_ok():
    result = doctor.check_python_version()

    assert result.severity == "ok"


def test_pipx_missing_fails(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)

    result = doctor.check_pipx()

    assert result.severity == "fail"


def test_appindicator_non_gnome_is_ok_not_applicable(monkeypatch):
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)

    result = doctor.check_appindicator_ext()

    assert result.severity == "ok"
    assert "not applicable" in result.detail


class _FakeIface:
    def __init__(self, owned=True, raises=None):
        self._owned = owned
        self._raises = raises

    async def call_name_has_owner(self, name):
        if self._raises is not None:
            raise self._raises
        return self._owned


class _FakeProxy:
    def __init__(self, iface):
        self._iface = iface

    def get_interface(self, name):
        return self._iface


class _FakeBus:
    def __init__(
        self,
        bus_type=None,
        iface=None,
        connect_exc=None,
        introspect_exc_for_portal=None,
        introspect_hang=False,
    ):
        self._iface = iface or _FakeIface()
        self._connect_exc = connect_exc
        self._introspect_exc_for_portal = introspect_exc_for_portal
        self._introspect_hang = introspect_hang
        self.introspect_calls = []
        self.disconnected = False

    async def connect(self):
        if self._connect_exc is not None:
            raise self._connect_exc
        return self

    async def introspect(self, service, path):
        self.introspect_calls.append((service, path))
        if service == "org.freedesktop.portal.Desktop":
            if self._introspect_exc_for_portal is not None:
                raise self._introspect_exc_for_portal
        if self._introspect_hang:
            import asyncio as _a

            await _a.Event().wait()
        return object()

    def get_proxy_object(self, service, path, intro):
        return _FakeProxy(self._iface)

    def disconnect(self):
        self.disconnected = True


@pytest.mark.asyncio
async def test_check_portal_registered_returns_ok(monkeypatch):
    fake_instance = _FakeBus(iface=_FakeIface(owned=True))
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda bus_type=None: fake_instance)

    result = await doctor.check_portal()

    assert result.severity == "ok"
    assert "registered" in result.detail
    assert fake_instance.disconnected is True


@pytest.mark.asyncio
async def test_check_portal_not_registered_returns_fail(monkeypatch):
    fake_instance = _FakeBus(iface=_FakeIface(owned=False))
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda bus_type=None: fake_instance)

    result = await doctor.check_portal()

    assert result.severity == "fail"
    assert "not registered" in result.detail
    assert "unreachable" not in result.detail
    assert "timed out" not in result.detail


@pytest.mark.asyncio
async def test_check_portal_bus_unreachable_returns_fail(monkeypatch):
    fake_instance = _FakeBus(connect_exc=OSError("no bus"))
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda bus_type=None: fake_instance)

    result = await doctor.check_portal()

    assert result.severity == "fail"
    assert "unreachable" in result.detail
    assert "no bus" in result.detail


@pytest.mark.asyncio
async def test_check_portal_timeout_returns_fail(monkeypatch):
    fake_instance = _FakeBus(introspect_hang=True)
    monkeypatch.setattr(doctor, "_PORTAL_CHECK_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda bus_type=None: fake_instance)

    result = await doctor.check_portal()

    assert result.severity == "fail"
    assert "timed out" in result.detail
    assert fake_instance.disconnected is True


@pytest.mark.asyncio
async def test_check_portal_tolerates_hyphenated_portal_properties(monkeypatch):
    from dbus_next.errors import InvalidMemberNameError

    fake_instance = _FakeBus(
        iface=_FakeIface(owned=True),
        introspect_exc_for_portal=InvalidMemberNameError(
            "invalid member name: power-saver-enabled"
        ),
    )
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda bus_type=None: fake_instance)

    result = await doctor.check_portal()

    assert result.severity == "ok"
    assert "registered" in result.detail
    assert all(
        service != "org.freedesktop.portal.Desktop"
        for service, _path in fake_instance.introspect_calls
    ), (
        "check_portal() should not introspect org.freedesktop.portal.Desktop; "
        f"calls were {fake_instance.introspect_calls!r}"
    )
