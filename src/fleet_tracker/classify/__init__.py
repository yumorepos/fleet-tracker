"""Classification surface for Fleet Tracker.

The retrofit module (`retrofit.py`) is copied verbatim from the upstream
`fleet-retrofit-tracker` desktop snapshot and must not be edited; see
docs/DESIGN.md §3 and tests/test_retrofit_pristine.py.

The boundary helpers (`to_retrofit_aircraft`, `to_retrofit_observation`,
`compute_retrofit_state`) live in this file. They translate between Fleet
Tracker's richer types and the retrofit module's narrower ones, and apply
the retired short-circuit per docs/DESIGN.md §3 / §6.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fleet_tracker import model

from . import retrofit


def to_retrofit_aircraft(ac: model.Aircraft) -> retrofit.Aircraft:
    """Project Fleet Tracker's Aircraft into the retrofit module's narrower one.

    Drops msn, retired, current_state, last_confirmed_at: the retrofit module
    has no use for them. retired is consulted by the boundary itself, not by
    the retrofit module (see compute_retrofit_state).
    """
    # The retrofit module's Aircraft declares sub_fleet: str (not Optional),
    # but Fleet Tracker's Aircraft allows sub_fleet=None for tails where the
    # airline-internal code isn't known yet. Substitute "" so the boundary
    # never raises on incomplete data. See test_to_retrofit_aircraft_handles_missing_sub_fleet.
    return retrofit.Aircraft(
        tail_number=ac.tail_number,
        airline=ac.airline,
        aircraft_type=ac.aircraft_type,
        sub_fleet=ac.sub_fleet or "",
        delivered=ac.delivered,
    )


def to_retrofit_observation(row: dict[str, Any]) -> retrofit.Observation:
    """Translate one observations-table row into a retrofit.Observation.

    Caller is responsible for filtering rows where signal_kind == 'cabin'.
    Maps the FleetTrackerSource string back into ObservationSource where
    possible; falls back to MANUAL for sources not in the retrofit module's
    enum (e.g. opensky_live, airfleets).
    """
    src = row["source"]
    try:
        source = retrofit.ObservationSource(src)
    except ValueError:
        source = retrofit.ObservationSource.MANUAL

    return retrofit.Observation(
        tail_number=row["tail_number"],
        observed_at=row["observed_at"],
        source=source,
        source_url=row["source_url"],
        state_signal=retrofit.StateSignal(row["signal_value"]),
        confidence=row["confidence"],
        notes=row.get("notes", "") or "",
    )


def compute_retrofit_state(
    aircraft: model.Aircraft,
    cabin_observations: list[dict[str, Any]],
    now: Optional[datetime] = None,
) -> tuple[retrofit.CabinState, Optional[datetime]]:
    """Compute the current cabin retrofit state for one aircraft.

    Includes the retired short-circuit per docs/DESIGN.md §3 / §6: if the
    aircraft is retired, return (UNKNOWN, None) without invoking the
    retrofit module. The retrofit classifier has no concept of retirement;
    a long-retired tail with a stale RETROFIT observation would otherwise
    classify as RETROFIT forever. That responsibility lives at the boundary,
    not inside the (pristine) module.
    """
    if aircraft.retired is not None:
        return retrofit.CabinState.UNKNOWN, None

    rt_aircraft = to_retrofit_aircraft(aircraft)
    obs = [to_retrofit_observation(row) for row in cabin_observations]
    state = retrofit.classify(rt_aircraft, obs, now=now)
    last = max((o.observed_at for o in obs), default=None)
    return state, last
