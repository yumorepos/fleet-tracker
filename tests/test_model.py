"""Tests for src/fleet_tracker/model.py."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from fleet_tracker.model import (
    AcquisitionType,
    Aircraft,
    FleetTrackerSource,
    Flight,
    LifecycleSignal,
    OwnershipSignal,
)


def test_aircraft_minimal_construction():
    ac = Aircraft(
        tail_number="C-FBOM",
        airline="Air Canada",
        aircraft_type="A220-300",
    )
    assert ac.tail_number == "C-FBOM"
    assert ac.airline == "Air Canada"
    assert ac.aircraft_type == "A220-300"
    assert ac.msn is None
    assert ac.retired is None


def test_aircraft_full_construction():
    ac = Aircraft(
        tail_number="C-FBOM",
        airline="Air Canada",
        aircraft_type="A220-300",
        msn="55088",
        sub_fleet="33H",
        delivered=datetime(2020, 6, 12, tzinfo=timezone.utc),
        retired=None,
        current_state="ORIGINAL",
        last_confirmed_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
    )
    assert ac.msn == "55088"
    assert ac.sub_fleet == "33H"
    assert ac.current_state == "ORIGINAL"


def test_aircraft_is_frozen():
    ac = Aircraft(tail_number="C-FBOM", airline="Air Canada", aircraft_type="A220-300")
    with pytest.raises(FrozenInstanceError):
        ac.tail_number = "C-FXKQ"  # type: ignore[misc]


def test_flight_minimal_construction():
    now = datetime(2026, 5, 5, 14, 22, tzinfo=timezone.utc)
    f = Flight(
        flight_id="opensky:c01234:1717590120",
        tail_number="C-FBOM",
        actual_off=now,
        status="completed",
        source=FleetTrackerSource.OPENSKY_LIVE,
        ingested_at=now,
    )
    assert f.tail_number == "C-FBOM"
    assert f.status == "completed"
    assert f.flight_number is None
    assert f.actual_on is None


def test_flight_is_frozen():
    now = datetime(2026, 5, 5, tzinfo=timezone.utc)
    f = Flight(
        flight_id="x",
        tail_number="C-FBOM",
        actual_off=now,
        status="completed",
        source=FleetTrackerSource.OPENSKY_LIVE,
        ingested_at=now,
    )
    with pytest.raises(FrozenInstanceError):
        f.status = "in_flight"  # type: ignore[misc]


def test_fleet_tracker_source_values():
    expected = {
        "planespotters",
        "airline_press",
        "seatmap",
        "hangar_routing",
        "manual",
        "opensky_live",
        "airfleets",
        "aerolopa",
        "wikipedia_fleet",
    }
    assert {s.value for s in FleetTrackerSource} == expected


def test_ownership_signal_values():
    assert {s.value for s in OwnershipSignal} == {
        "owned",
        "leased_in",
        "leased_out",
        "retired",
    }


def test_lifecycle_signal_values():
    assert {s.value for s in LifecycleSignal} == {
        "in_service",
        "stored",
        "written_off",
    }


def test_acquisition_type_values():
    assert {t.value for t in AcquisitionType} == {
        "new_delivery",
        "secondhand",
        "lease",
    }


def test_str_enum_is_string():
    assert FleetTrackerSource.OPENSKY_LIVE == "opensky_live"
    assert isinstance(FleetTrackerSource.OPENSKY_LIVE, str)
