"""Tests for src/fleet_tracker/db.py."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from fleet_tracker import db


@pytest.fixture
def conn(tmp_path):
    """Fresh DuckDB in a temp dir, schema initialised."""
    db_path = tmp_path / "fleet.duckdb"
    c = db.connect(db_path)
    db.init_schema(c)
    yield c
    c.close()


def _table_names(conn) -> set[str]:
    rows = conn.sql(
        "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
    ).fetchall()
    return {r[0] for r in rows}


def test_connect_creates_parent_dir(tmp_path):
    db_path = tmp_path / "nested" / "subdir" / "fleet.duckdb"
    c = db.connect(db_path)
    assert db_path.parent.exists()
    c.close()


def test_init_schema_creates_all_tables(conn):
    expected = {"aircraft", "ownership_history", "observations", "media", "specs"}
    actual = _table_names(conn)
    assert expected.issubset(actual), f"missing tables: {expected - actual}"


def test_init_schema_is_idempotent(conn):
    # Calling again must not raise.
    db.init_schema(conn)
    assert {"aircraft", "ownership_history"}.issubset(_table_names(conn))


def test_aircraft_insert_and_query(conn):
    conn.execute(
        "INSERT INTO aircraft (tail_number, airline, aircraft_type) VALUES (?, ?, ?)",
        ["C-FBOM", "Air Canada", "A220-300"],
    )
    rows = conn.sql("SELECT tail_number, airline FROM aircraft").fetchall()
    assert rows == [("C-FBOM", "Air Canada")]


def test_observations_sequence_auto_assigns_id(conn):
    conn.execute(
        """
        INSERT INTO observations (tail_number, observed_at, source, source_url,
                                  signal_kind, signal_value, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ["C-FBOM", datetime(2026, 5, 5, tzinfo=timezone.utc), "opensky_live",
         "https://opensky-network.org/x", "flight", "completed", 0.95],
    )
    rows = conn.sql("SELECT observation_id, tail_number FROM observations").fetchall()
    assert len(rows) == 1
    assert rows[0][0] is not None  # auto-assigned ID
    assert rows[0][1] == "C-FBOM"


def test_confidence_check_constraint_rejects_out_of_range(conn):
    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO observations (tail_number, observed_at, source, source_url,
                                      signal_kind, signal_value, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ["C-FBOM", datetime(2026, 5, 5, tzinfo=timezone.utc), "manual",
             "https://example", "cabin", "retrofit", 1.5],
        )


def test_media_kind_check_constraint_rejects_unknown(conn):
    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            "INSERT INTO media (tail_number, kind, image_url, attribution, ingested_at) VALUES (?, ?, ?, ?, ?)",
            ["C-FBOM", "engine", "http://x", "© y", datetime(2026, 5, 5, tzinfo=timezone.utc)],
        )


def test_aircraft_pk_unique(conn):
    conn.execute("INSERT INTO aircraft (tail_number, airline, aircraft_type) VALUES ('C-FBOM', 'AC', 'A220-300')")
    with pytest.raises(duckdb.ConstraintException):
        conn.execute("INSERT INTO aircraft (tail_number, airline, aircraft_type) VALUES ('C-FBOM', 'AC', 'A220-300')")


def test_ownership_history_accepts_acquisition_columns(conn):
    """First-row acquisition annotation per DESIGN §2."""
    conn.execute(
        """
        INSERT INTO ownership_history
            (tail_number, effective_from, owner_type, owner_entity,
             source_url, confidence, acquisition_type, acquisition_context)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ["C-FBOM", datetime(2020, 6, 12, tzinfo=timezone.utc), "owned",
         "Air Canada", "https://airfleets.net/x", 0.9,
         "new_delivery", "First A220-300 delivered to Air Canada"],
    )
    rows = conn.sql(
        "SELECT acquisition_type, acquisition_context FROM ownership_history"
    ).fetchall()
    assert rows == [("new_delivery", "First A220-300 delivered to Air Canada")]


def test_ownership_history_acquisition_columns_nullable(conn):
    """Subsequent ownership rows for the same operator leave acquisition fields NULL."""
    conn.execute(
        """
        INSERT INTO ownership_history
            (tail_number, effective_from, owner_type, owner_entity,
             source_url, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ["C-FBOM", datetime(2024, 1, 1, tzinfo=timezone.utc), "owned",
         "Air Canada", "https://airfleets.net/x", 0.9],
    )
    rows = conn.sql(
        "SELECT acquisition_type, acquisition_context FROM ownership_history"
    ).fetchall()
    assert rows == [(None, None)]


def test_indexes_exist(conn):
    rows = conn.sql("SELECT index_name FROM duckdb_indexes()").fetchall()
    names = {r[0] for r in rows}
    assert "idx_aircraft_airline_state" in names
    assert "idx_ownership_tail" in names
    assert "idx_obs_tail_time" in names
    assert "idx_obs_kind_time" in names


def test_read_flights_returns_empty_when_root_missing(conn, tmp_path):
    """Root directory does not exist at all (pre-cold-start)."""
    rel = db.read_flights(conn, flights_root=tmp_path / "no_files_here")
    rows = rel.fetchall()
    assert rows == []
    cols = [d[0] for d in rel.description]
    assert "tail_number" in cols
    assert "actual_off" in cols
    assert "airline" in cols  # Hive partition column


def test_read_flights_returns_empty_when_airline_dir_exists_but_empty(conn, tmp_path):
    """Day-1 state: data/flights/ and data/flights/airline=ac/ exist, but no Parquet inside.

    This is what the dashboard sees on its first render before any nightly
    collection has run. The helper must return an empty relation, not raise.
    """
    flights_root = tmp_path / "flights"
    (flights_root / "airline=ac").mkdir(parents=True)
    (flights_root / "airline=dl").mkdir(parents=True)

    rel = db.read_flights(conn, flights_root=flights_root)
    rows = rel.fetchall()
    assert rows == []
    cols = [d[0] for d in rel.description]
    assert "tail_number" in cols

    # Same for an airline-scoped read.
    rel2 = db.read_flights(conn, airline="ac", flights_root=flights_root)
    assert rel2.fetchall() == []


def test_read_flights_reads_partitioned_parquet(conn, tmp_path):
    """End-to-end: write a Hive-partitioned Parquet file, read it back via the helper.

    This is the storage shape that the v1 vertical slice exercises and that
    v1.5's nightly job will append to.
    """
    flights_root = tmp_path / "flights"
    partition_dir = flights_root / "airline=ac" / "year=2026" / "month=05"
    partition_dir.mkdir(parents=True)
    pq_path = partition_dir / "flights.parquet"

    conn.execute(f"""
        COPY (
            SELECT
                'opensky:c01234:1717590120' AS flight_id,
                'C-FBOM' AS tail_number,
                'AC456' AS flight_number,
                'YUL' AS origin_icao,
                'YYZ' AS destination_icao,
                NULL::TIMESTAMP AS scheduled_off,
                TIMESTAMP '2026-05-05 14:22:00' AS actual_off,
                TIMESTAMP '2026-05-05 16:08:00' AS actual_on,
                'completed' AS status,
                'opensky_live' AS source,
                TIMESTAMP '2026-05-05 16:30:00' AS ingested_at
        ) TO '{pq_path}' (FORMAT PARQUET)
    """)

    rel = db.read_flights(conn, flights_root=flights_root)
    rows = rel.fetchall()
    assert len(rows) == 1

    cols = {d[0] for d in rel.description}
    assert "airline" in cols
    assert "year" in cols
    assert "month" in cols

    rel2 = db.read_flights(conn, airline="ac", flights_root=flights_root)
    rows2 = rel2.fetchall()
    assert len(rows2) == 1
