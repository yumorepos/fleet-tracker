"""Tests for src/fleet_tracker/ingest.py."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import pytest

from fleet_tracker import db
from fleet_tracker.ingest import write_ownership_observation
from fleet_tracker.model import FleetTrackerSource, OwnershipSignal


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "fleet.duckdb")
    db.init_schema(c)
    yield c
    c.close()


def test_write_ownership_observation_writes_one_row(conn):
    obs_id = write_ownership_observation(
        conn,
        tail_number="C-FNOG",
        owner_entity="Air Canada",
        signal=OwnershipSignal.OWNED,
        source=FleetTrackerSource.OPENSKY_LIVE,
        source_url="https://opensky-network.org/api/metadata/aircraft/icao/c023c7",
        confidence=0.70,
        observed_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
    )
    assert isinstance(obs_id, int) and obs_id > 0

    rows = conn.sql(
        "SELECT tail_number, signal_kind, signal_value, source, "
        "       confidence, source_url, notes "
        "FROM observations WHERE observation_id = ?",
        params=[obs_id],
    ).fetchall()
    assert len(rows) == 1
    tail, kind, value, source, conf, url, notes = rows[0]
    assert tail == "C-FNOG"
    assert kind == "ownership"
    assert value == "owned"
    assert source == "opensky_live"
    assert conf == pytest.approx(0.70)
    assert url.startswith("https://opensky-network.org/")
    assert "owner_entity=Air Canada" in notes


def test_write_ownership_observation_rejects_bad_confidence(conn):
    with pytest.raises(ValueError, match="confidence must be in"):
        write_ownership_observation(
            conn,
            tail_number="C-FNOG",
            owner_entity="Air Canada",
            signal=OwnershipSignal.OWNED,
            source=FleetTrackerSource.OPENSKY_LIVE,
            source_url="https://example.com",
            confidence=1.5,
        )


def test_write_ownership_observation_appends_caller_notes(conn):
    """Caller-supplied notes get appended after the owner_entity tag."""
    obs_id = write_ownership_observation(
        conn,
        tail_number="N301DU",
        owner_entity="Delta Air Lines",
        signal=OwnershipSignal.OWNED,
        source=FleetTrackerSource.OPENSKY_LIVE,
        source_url="https://opensky-network.org/api/metadata/aircraft/icao/a32367",
        confidence=0.70,
        notes="OpenSky metadata cross-check 2026-05-05",
    )
    notes = conn.sql(
        "SELECT notes FROM observations WHERE observation_id = ?",
        params=[obs_id],
    ).fetchone()[0]
    assert notes.startswith("owner_entity=Delta Air Lines")
    assert "OpenSky metadata cross-check 2026-05-05" in notes


def test_write_ownership_observation_default_observed_at_populated(conn):
    """When observed_at is omitted, the column is still populated (non-null).

    The exact value depends on DuckDB's tz-aware-binding behaviour (which can
    convert to local time), so we don't compare to wall-clock; we just confirm
    a value was written.
    """
    obs_id = write_ownership_observation(
        conn,
        tail_number="C-FIVK",
        owner_entity="Air Canada",
        signal=OwnershipSignal.OWNED,
        source=FleetTrackerSource.OPENSKY_LIVE,
        source_url="https://opensky-network.org/api/metadata/aircraft/icao/c0174d",
        confidence=0.70,
    )
    observed = conn.sql(
        "SELECT observed_at FROM observations WHERE observation_id = ?",
        params=[obs_id],
    ).fetchone()[0]
    assert observed is not None
