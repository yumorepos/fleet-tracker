"""Smoke tests for the retrofit classification module.

Ported from the upstream fleet-retrofit-tracker desktop snapshot's
test_model.py; only the import path has changed (`src.model` ->
`fleet_tracker.classify.retrofit`). When the upstream module ships as an
installable package, this file gets re-pointed at it; the test bodies
remain identical because the module surface remains identical.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fleet_tracker.classify.retrofit import (
    Aircraft,
    CabinState,
    Observation,
    ObservationSource,
    StateSignal,
    classify,
    install_rate,
    project_completion,
)


def _now() -> datetime:
    return datetime(2026, 5, 5, tzinfo=timezone.utc)


def _ac() -> Aircraft:
    return Aircraft(
        tail_number="C-FBOM",
        airline="Air Canada",
        aircraft_type="A220-300",
        sub_fleet="A220",
        delivered=datetime(2020, 6, 1, tzinfo=timezone.utc),
    )


def test_no_observations_is_unknown():
    assert classify(_ac(), [], now=_now()) == CabinState.UNKNOWN


def test_recent_high_confidence_retrofit():
    obs = [Observation(
        tail_number="C-FBOM",
        observed_at=_now() - timedelta(days=10),
        source=ObservationSource.PLANESPOTTERS,
        source_url="https://planespotters.net/photo/example",
        state_signal=StateSignal.RETROFIT,
        confidence=0.92,
    )]
    assert classify(_ac(), obs, now=_now()) == CabinState.RETROFIT


def test_old_retrofit_signal_falls_through():
    # 200 days old -> outside the 90-day freshness window
    obs = [Observation(
        tail_number="C-FBOM",
        observed_at=_now() - timedelta(days=200),
        source=ObservationSource.PLANESPOTTERS,
        source_url="https://planespotters.net/photo/old",
        state_signal=StateSignal.RETROFIT,
        confidence=0.92,
    )]
    assert classify(_ac(), obs, now=_now()) == CabinState.UNKNOWN


def test_hangar_dwell_marks_in_progress():
    obs = [
        Observation("C-FBOM", _now() - timedelta(days=3),
                    ObservationSource.HANGAR_ROUTING,
                    "https://flightradar24.com/data/aircraft/c-fbom",
                    StateSignal.IN_HANGAR, 0.7),
        Observation("C-FBOM", _now() - timedelta(days=8),
                    ObservationSource.HANGAR_ROUTING,
                    "https://flightradar24.com/data/aircraft/c-fbom",
                    StateSignal.IN_HANGAR, 0.7),
    ]
    assert classify(_ac(), obs, now=_now()) == CabinState.IN_PROGRESS


def test_install_rate_and_projection():
    retrofits = [
        _now() - timedelta(days=d) for d in [5, 12, 25, 40, 55]
    ]
    rate = install_rate(retrofits, now=_now())
    # 5 retrofits in 60 days = ~2.5 per month
    assert 2.0 < rate < 3.0
    eta = project_completion(completed=18, total=167, rate_per_month=rate, now=_now())
    assert eta is not None
    # 149 remaining at 2.5/month is ~60 months out, into 2031
    assert eta.year >= 2030
