"""Tests for the classification boundary in src/fleet_tracker/classify/__init__.py.

Covers the converter (to_retrofit_aircraft / to_retrofit_observation) and the
retired short-circuit in compute_retrofit_state. Stubs for ownership and
lifecycle classification are also asserted to raise NotImplementedError.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fleet_tracker import model
from fleet_tracker.classify import (
    compute_retrofit_state,
    lifecycle,
    ownership,
    retrofit,
    to_retrofit_aircraft,
    to_retrofit_observation,
)


def _now() -> datetime:
    return datetime(2026, 5, 5, tzinfo=timezone.utc)


def test_to_retrofit_aircraft_preserves_five_fields():
    ft = model.Aircraft(
        tail_number="C-FBOM",
        airline="Air Canada",
        aircraft_type="A220-300",
        msn="55088",                                      # dropped
        sub_fleet="33H",
        delivered=datetime(2020, 6, 12, tzinfo=timezone.utc),
        retired=None,                                     # dropped
        current_state="ORIGINAL",                         # dropped
        last_confirmed_at=datetime(2026, 4, 29, tzinfo=timezone.utc),  # dropped
    )
    rt = to_retrofit_aircraft(ft)
    assert rt.tail_number == "C-FBOM"
    assert rt.airline == "Air Canada"
    assert rt.aircraft_type == "A220-300"
    assert rt.sub_fleet == "33H"
    assert rt.delivered == datetime(2020, 6, 12, tzinfo=timezone.utc)
    # The retrofit module's Aircraft has only 5 fields total.
    assert {f for f in rt.__dataclass_fields__} == {
        "tail_number", "airline", "aircraft_type", "sub_fleet", "delivered",
    }


def test_to_retrofit_aircraft_handles_missing_sub_fleet():
    ft = model.Aircraft(tail_number="N123XX", airline="Delta", aircraft_type="A220-100")
    rt = to_retrofit_aircraft(ft)
    assert rt.sub_fleet == ""  # converter substitutes empty string


def test_to_retrofit_observation_known_source():
    row = {
        "tail_number": "C-FBOM",
        "observed_at": _now(),
        "source": "planespotters",
        "source_url": "https://planespotters.net/photo/123",
        "signal_value": "retrofit",
        "confidence": 0.9,
        "notes": "clear cabin shot",
    }
    obs = to_retrofit_observation(row)
    assert obs.source == retrofit.ObservationSource.PLANESPOTTERS
    assert obs.state_signal == retrofit.StateSignal.RETROFIT
    assert obs.confidence == 0.9
    assert obs.notes == "clear cabin shot"


def test_to_retrofit_observation_unknown_source_falls_back_to_manual():
    # opensky_live is in FleetTrackerSource but not in retrofit.ObservationSource;
    # the converter should fall back to MANUAL rather than raise.
    row = {
        "tail_number": "C-FBOM",
        "observed_at": _now(),
        "source": "opensky_live",
        "source_url": "https://opensky-network.org/...",
        "signal_value": "in_hangar",
        "confidence": 0.6,
        "notes": "",
    }
    obs = to_retrofit_observation(row)
    assert obs.source == retrofit.ObservationSource.MANUAL


def test_compute_retrofit_state_retired_short_circuit():
    """A retired tail returns (UNKNOWN, None) without invoking the retrofit module.

    This is the boundary's responsibility, not the module's, per
    docs/DESIGN.md §3 / §6. The retrofit module has no concept of retirement;
    a stale RETROFIT observation against a long-retired tail would otherwise
    classify as RETROFIT forever.
    """
    retired = model.Aircraft(
        tail_number="C-FOLD",
        airline="Air Canada",
        aircraft_type="A340-300",
        retired=datetime(2021, 3, 1, tzinfo=timezone.utc),
    )
    # Provide a recent high-confidence retrofit observation; it must be IGNORED.
    cabin_obs = [{
        "tail_number": "C-FOLD",
        "observed_at": _now() - timedelta(days=10),
        "source": "planespotters",
        "source_url": "https://planespotters.net/photo/whatever",
        "signal_value": "retrofit",
        "confidence": 0.95,
        "notes": "",
    }]
    state, last = compute_retrofit_state(retired, cabin_obs, now=_now())
    assert state == retrofit.CabinState.UNKNOWN
    assert last is None


def test_compute_retrofit_state_happy_path_delegates_to_module():
    active = model.Aircraft(
        tail_number="C-FBOM",
        airline="Air Canada",
        aircraft_type="A220-300",
        sub_fleet="33H",
    )
    cabin_obs = [{
        "tail_number": "C-FBOM",
        "observed_at": _now() - timedelta(days=10),
        "source": "planespotters",
        "source_url": "https://planespotters.net/photo/example",
        "signal_value": "retrofit",
        "confidence": 0.92,
        "notes": "",
    }]
    state, last = compute_retrofit_state(active, cabin_obs, now=_now())
    assert state == retrofit.CabinState.RETROFIT
    assert last == _now() - timedelta(days=10)


def test_compute_retrofit_state_no_observations():
    active = model.Aircraft(tail_number="C-FBOM", airline="Air Canada", aircraft_type="A220-300")
    state, last = compute_retrofit_state(active, [], now=_now())
    assert state == retrofit.CabinState.UNKNOWN
    assert last is None


def test_ownership_stub_raises():
    with pytest.raises(NotImplementedError, match="Phase 4"):
        ownership.resolve_current_owner("C-FBOM")


def test_lifecycle_stub_raises():
    with pytest.raises(NotImplementedError, match="Phase 4"):
        lifecycle.resolve_lifecycle_state("C-FBOM")
