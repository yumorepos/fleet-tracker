"""Ingestion helpers: write observations from collector outputs into DuckDB.

One small surface for now: `write_ownership_observation` takes a parsed
ownership signal (from any collector — airfleets, Planespotters, OpenSky
metadata, airline press) and writes one row to the `observations` table.

Per docs/DESIGN.md §2, ownership_history is the materialized "current owner"
view computed downstream; this layer just persists the immutable observation
log. v1.5's nightly aggregator will read these rows and produce the
ownership_history projection.

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
