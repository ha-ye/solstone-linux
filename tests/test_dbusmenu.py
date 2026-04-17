# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from dbus_next import Variant

from solstone_linux.dbusmenu import MenuItem


def test_default_emits_enabled_and_visible_true():
    props = MenuItem(label="foo").get_properties()

    assert props["enabled"] == Variant("b", True)
    assert props["visible"] == Variant("b", True)


def test_explicit_false_emits_false():
    props = MenuItem(label="x", enabled=False, visible=False).get_properties()

    assert props["enabled"] == Variant("b", False)
    assert props["visible"] == Variant("b", False)


def test_toggle_true_after_false_still_emits():
    item = MenuItem(label="x", enabled=False, visible=False)
    item.enabled = True
    item.visible = True

    props = item.get_properties()

    assert props["enabled"] == Variant("b", True)
    assert props["visible"] == Variant("b", True)


def test_other_keys_still_conditional():
    props = MenuItem().get_properties()

    assert "icon-name" not in props
    assert "toggle-type" not in props
    assert "children-display" not in props
