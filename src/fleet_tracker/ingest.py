"""Ingestion helpers: write observations from collector outputs into DuckDB.

Two writers, one per signal granularity (DESIGN §6):

  - `write_ownership_observation`: per-tail ownership signals. The source
    URL must specifically mention the tail (e.g. an OpenSky metadata
    record keyed by icao24, or an airline press release naming the
    aircraft). Stored as `signal_kind = 'ownership'`.

  - `write_fleet_membership_observation`: type-level signals. The source
    URL confirms operator-operates-type at the page level; it does not
    name a specific tail. Wikipedia's airline-fleet articles are the
    canonical case. Attached to a tail by aircraft_type match in the
    reference CSV. Stored as `signal_kind = 'fleet_membership'`.

Per DESIGN §2, ownership_history is the materialized "current owner" view
computed downstream; this layer just persists the immutable observation
log. v1.5's nightly aggregator will read these rows and produce the
ownership_history projection. fleet_membership rows do not feed
ownership_history directly — they're a sanity-check signal, not an
ownership claim.

Why a separate module instead of `aggregate.py`: aggregate is for rollups
(read-side), ingest is for writes (the path collectors actually take into
the database). Keeping them apart makes the data flow legible.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import duckdb

from fleet_tracker.model import FleetTrackerSource, OwnershipSignal


def write_ownership_observation(
    conn: duckdb.DuckDBPyConnection,
    *,
    tail_number: str,
    owner_entity: str,
    signal: OwnershipSignal,
    source: FleetTrackerSource,
    source_url: str,
    confidence: float,
    observed_at: Optional[datetime] = None,
    notes: str = "",
) -> int:
    """Write one ownership observation. Returns the observation_id.

    `owner_entity` is the human-readable owner string (e.g. "Air Canada",
    "AerCap"). The `observations` table schema doesn't carry it as a
    dedicated column — that's only on `ownership_history`, the downstream
    materialised projection (per DESIGN §2). For now the entity is stitched
    into `notes` as `owner_entity={...}` so downstream readers can recover
    it without losing the immutable-log property.
    """
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0, 1], got {confidence!r}")
    observed_at = observed_at or datetime.now(timezone.utc)
    composed_notes = f"owner_entity={owner_entity}"
    if notes:
        composed_notes = f"{composed_notes}; {notes}"

    cur = conn.execute(
        """
        INSERT INTO observations
            (tail_number, observed_at, source, source_url,
             signal_kind, signal_value, confidence, notes)
        VALUES (?, ?, ?, ?, 'ownership', ?, ?, ?)
        RETURNING observation_id
        """,
        [
            tail_number,
            observed_at,
            source.value,
            source_url,
            signal.value,
            confidence,
            composed_notes,
        ],
    )
    row = cur.fetchone()
    if row is None:  # pragma: no cover - defensive
        raise RuntimeError("INSERT ... RETURNING produced no row")
    return int(row[0])


def write_fleet_membership_observation(
    conn: duckdb.DuckDBPyConnection,
    *,
    tail_number: str,
    airline: str,
    aircraft_type: str,
    source: FleetTrackerSource,
    source_url: str,
    confidence: float,
    observed_at: Optional[datetime] = None,
    notes: str = "",
) -> int:
    """Write one type-level fleet_membership observation. Returns the observation_id.

    The source_url confirms operator-operates-type at the page level; it
    does not need to mention `tail_number` specifically. The row is
    attached to `tail_number` by aircraft_type match in the reference CSV
    (caller's responsibility — this writer trusts that the match has
    already been validated).

    Use this for type-level sources like Wikipedia airline-fleet articles.
    For per-tail ownership signals (where the source URL specifically
    mentions the tail), use `write_ownership_observation` instead.

    `signal_value` stores the confirmed `aircraft_type` so downstream
    queries can answer "what types has this source confirmed for this
    operator?" without re-reading notes. `airline` is stitched into
    notes alongside any caller-supplied annotation.
    """
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0, 1], got {confidence!r}")
    observed_at = observed_at or datetime.now(timezone.utc)
    composed_notes = f"airline={airline}; matched by aircraft_type"
    if notes:
        composed_notes = f"{composed_notes}; {notes}"

    cur = conn.execute(
        """
        INSERT INTO observations
            (tail_number, observed_at, source, source_url,
             signal_kind, signal_value, confidence, notes)
        VALUES (?, ?, ?, ?, 'fleet_membership', ?, ?, ?)
        RETURNING observation_id
        """,
        [
            tail_number,
            observed_at,
            source.value,
            source_url,
            aircraft_type,
            confidence,
            composed_notes,
        ],
    )
    row = cur.fetchone()
    if row is None:  # pragma: no cover - defensive
        raise RuntimeError("INSERT ... RETURNING produced no row")
    return int(row[0])
