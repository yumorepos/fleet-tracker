"""Core Fleet Tracker data model.

Mirrors the schema in docs/DESIGN.md §6. Two frozen dataclasses (Aircraft,
Flight) and three StrEnums covering source provenance and the two non-cabin
signal taxonomies (ownership, lifecycle). Cabin signals live inside the
retrofit module; see docs/DESIGN.md §3 for why those types stay separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Optional


class FleetTrackerSource(StrEnum):
    PLANESPOTTERS = "planespotters"
    AIRLINE_PRESS = "airline_press"
    SEATMAP = "seatmap"
    HANGAR_ROUTING = "hangar_routing"
    MANUAL = "manual"
    OPENSKY_LIVE = "opensky_live"
    AIRFLEETS = "airfleets"
    AEROLOPA = "aerolopa"
    WIKIPEDIA_FLEET = "wikipedia_fleet"


class OwnershipSignal(StrEnum):
    OWNED = "owned"
    LEASED_IN = "leased_in"
    LEASED_OUT = "leased_out"
    RETIRED = "retired"


class LifecycleSignal(StrEnum):
    IN_SERVICE = "in_service"
    STORED = "stored"
    WRITTEN_OFF = "written_off"


class AcquisitionType(StrEnum):
    """How an operator first acquired a tail.

    Populated only on the first ownership row for a tail at each operator
    (the row whose effective_from matches the operator's acquisition date).
    Subsequent ownership rows for the same operator leave acquisition fields
    null. Merger-acquired aircraft are SECONDHAND with a free-text context
    annotation; see docs/DESIGN.md §2 for the design rationale.
    """
    NEW_DELIVERY = "new_delivery"   # direct from manufacturer
    SECONDHAND = "secondhand"       # acquired from another operator (incl. via merger)
    LEASE = "lease"                 # leased in (lease sub-type lives in owner_type)


@dataclass(frozen=True)
class Aircraft:
    tail_number: str
    airline: str
    aircraft_type: str
    msn: Optional[str] = None
    sub_fleet: Optional[str] = None
    delivered: Optional[datetime] = None
    retired: Optional[datetime] = None
    current_state: Optional[str] = None
    last_confirmed_at: Optional[datetime] = None


@dataclass(frozen=True)
class Flight:
    flight_id: str
    tail_number: str
    actual_off: datetime
    status: str
    source: str
    ingested_at: datetime
    flight_number: Optional[str] = None
    origin_icao: Optional[str] = None
    destination_icao: Optional[str] = None
    scheduled_off: Optional[datetime] = None
    actual_on: Optional[datetime] = None
