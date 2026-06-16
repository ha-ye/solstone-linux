# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 sol pbc

from solstone_linux.config import DEFAULT_SYNC_STALE_THRESHOLD
from solstone_linux.sync_health import (
    SURFACE_BY_STATE,
    ErrorType,
    HealthState,
    SyncFacts,
    derive_health,
    load_facts,
    save_facts,
)


def test_empty_facts_derive_unknown():
    health = derive_health(SyncFacts(), now=1000.0)

    assert health.state == HealthState.UNKNOWN
    assert health.sni_status == "Active"
    assert health.pending_display == "pending unconfirmed"


def test_error_precedence_states():
    assert (
        derive_health(SyncFacts(last_error_class=ErrorType.AUTH), now=1000.0).state
        == HealthState.REVOKED
    )
    assert (
        derive_health(
            SyncFacts(last_error_class=ErrorType.INCOMPATIBLE), now=1000.0
        ).state
        == HealthState.UPDATE_NEEDED
    )
    assert (
        derive_health(SyncFacts(last_error_class=ErrorType.TRANSIENT), now=1000.0).state
        == HealthState.OFFLINE
    )


def test_stale_uses_last_successful_contact():
    health = derive_health(
        SyncFacts(
            last_successful_sync=900.0,
            last_successful_contact=100.0,
            in_progress=True,
        ),
        now=1000.0,
        stale_threshold=DEFAULT_SYNC_STALE_THRESHOLD,
    )

    assert health.state == HealthState.STALE
    assert health.sni_status == "NeedsAttention"
    assert "last contact" in health.tooltip


def test_pending_confirmed_zero_is_only_connected_gate():
    connected = derive_health(SyncFacts(pending_confirmed=0), now=1000.0)
    unknown = derive_health(SyncFacts(pending_confirmed=None), now=1000.0)

    assert connected.state == HealthState.CONNECTED
    assert connected.pending_display == "0 pending"
    assert unknown.state == HealthState.UNKNOWN
    assert unknown.pending_display == "pending unconfirmed"


def test_fresh_contact_prevents_stale_when_sync_timestamp_is_old():
    health = derive_health(
        SyncFacts(
            last_successful_sync=100.0,
            last_successful_contact=990.0,
            in_progress=True,
        ),
        now=1000.0,
        stale_threshold=DEFAULT_SYNC_STALE_THRESHOLD,
    )

    assert health.state == HealthState.SYNCING


def test_save_and_load_facts_round_trip(tmp_path):
    facts = SyncFacts(
        last_successful_sync=100.5,
        last_successful_contact=200.5,
        last_error_class=ErrorType.INCOMPATIBLE,
        last_error_code=404,
        pending_confirmed=None,
        in_progress=True,
        progress="uploading 120000_300",
    )

    save_facts(tmp_path, facts)
    loaded = load_facts(tmp_path)

    assert loaded == facts


def test_load_facts_missing_or_invalid_returns_empty(tmp_path):
    assert load_facts(tmp_path) == SyncFacts()

    path = tmp_path / "sync_health.json"
    path.write_text("{not-json", encoding="utf-8")

    assert load_facts(tmp_path) == SyncFacts()


def test_every_health_state_has_complete_surface():
    assert set(SURFACE_BY_STATE) == set(HealthState)
    for surface in SURFACE_BY_STATE.values():
        assert surface.header_recording
        assert surface.header_idle
        assert surface.sync_line
        assert surface.tooltip
        assert surface.accessible_recording
        assert surface.accessible_idle
        assert surface.icon
        assert surface.sni
        assert surface.cli
        assert surface.doctor_severity
        assert surface.doctor_detail
        assert surface.dbus
