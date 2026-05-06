"""DuckDB schema and read helpers for Fleet Tracker.

Implements docs/DESIGN.md §6:
  - aircraft, ownership_history, observations, media, specs in DuckDB
  - flights in Hive-partitioned Parquet, queried via read_parquet glob
  - retrofit_state is a computed view, populated by classify.compute_retrofit_state

Layered: schema setup (init_schema) is idempotent. Reads are pure. Writes happen
in collectors and the aggregator, not here.
"""

from __future__ import annotations

from glob import glob as glob_files
from pathlib import Path
from typing import Optional, Union

import duckdb

_DEFAULT_DB_PATH = "data/fleet.duckdb"


def connect(path: Union[str, Path] = _DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open or create a DuckDB database file. Parent dir is created if missing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables, sequences, and indexes if they don't exist. Idempotent."""
    conn.execute(_DDL_AIRCRAFT)
    conn.execute(_DDL_OWNERSHIP)
    conn.execute(_DDL_OBS_SEQUENCE)
    conn.execute(_DDL_OBSERVATIONS)
    conn.execute(_DDL_MEDIA)
    conn.execute(_DDL_SPECS)
    for ddl in _DDL_INDEXES:
        conn.execute(ddl)


def read_flights(
    conn: duckdb.DuckDBPyConnection,
    airline: Optional[str] = None,
    flights_root: Union[str, Path] = "data/flights",
) -> duckdb.DuckDBPyRelation:
    """Open the Parquet flights archive as a DuckDB relation.

    Returns an empty relation (matching the flights schema, including the
    Hive partition columns) if no Parquet files exist yet, so cold-start
    callers don't need to special-case missing data.
    """
    flights_root = Path(flights_root)
    # Hive partition values live in directory names, not filenames. The trailing
    # *.parquet matches whatever the writer named the file inside month=NN/.
    if airline is None:
        pattern = str(flights_root / "airline=*" / "year=*" / "month=*" / "*.parquet")
    else:
        pattern = str(flights_root / f"airline={airline}" / "year=*" / "month=*" / "*.parquet")

    if not glob_files(pattern):
        return conn.sql(_EMPTY_FLIGHTS_RELATION)

    return conn.sql(
        f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = true)"
    )


_DDL_AIRCRAFT = """
CREATE TABLE IF NOT EXISTS aircraft (
    tail_number       TEXT PRIMARY KEY,
    airline           TEXT NOT NULL,
    aircraft_type     TEXT NOT NULL,
    msn               TEXT,
    sub_fleet         TEXT,
    delivered         TIMESTAMP,
    retired           TIMESTAMP,
    current_state     TEXT,
    last_confirmed_at TIMESTAMP
)
"""

_DDL_OWNERSHIP = """
CREATE TABLE IF NOT EXISTS ownership_history (
    tail_number          TEXT NOT NULL,
    effective_from       TIMESTAMP NOT NULL,
    effective_to         TIMESTAMP,
    owner_type           TEXT NOT NULL,
    owner_entity         TEXT NOT NULL,
    source_url           TEXT NOT NULL,
    confidence           DOUBLE NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    -- acquisition_* are populated ONLY on the first ownership row for a tail
    -- at each operator; null on subsequent rows. See docs/DESIGN.md §2.
    acquisition_type     TEXT,
    acquisition_context  TEXT,
    PRIMARY KEY (tail_number, effective_from)
)
"""

_DDL_OBS_SEQUENCE = """
CREATE SEQUENCE IF NOT EXISTS seq_observation_id START 1
"""

_DDL_OBSERVATIONS = """
CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY DEFAULT nextval('seq_observation_id'),
    tail_number    TEXT NOT NULL,
    observed_at    TIMESTAMP NOT NULL,
    source         TEXT NOT NULL,
    source_url     TEXT NOT NULL,
    signal_kind    TEXT NOT NULL,
    signal_value   TEXT NOT NULL,
    confidence     DOUBLE NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    notes          TEXT
)
"""

_DDL_MEDIA = """
CREATE TABLE IF NOT EXISTS media (
    tail_number TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('exterior', 'interior')),
    image_url   TEXT NOT NULL,
    attribution TEXT NOT NULL,
    captured_at TIMESTAMP,
    ingested_at TIMESTAMP NOT NULL,
    PRIMARY KEY (tail_number, kind)
)
"""

_DDL_SPECS = """
CREATE TABLE IF NOT EXISTS specs (
    tail_number             TEXT PRIMARY KEY,
    seats_first             INTEGER,
    seats_business          INTEGER,
    seats_premium_economy   INTEGER,
    seats_economy           INTEGER,
    seat_map_url            TEXT,
    lopa_source             TEXT,
    engine_type             TEXT,
    delivered_config_notes  TEXT
)
"""

_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_aircraft_airline_state ON aircraft (airline, current_state)",
    "CREATE INDEX IF NOT EXISTS idx_ownership_tail ON ownership_history (tail_number)",
    "CREATE INDEX IF NOT EXISTS idx_obs_tail_time ON observations (tail_number, observed_at)",
    "CREATE INDEX IF NOT EXISTS idx_obs_kind_time ON observations (signal_kind, observed_at)",
]

# Empty relation matching the Parquet flights schema plus Hive partition columns.
# Returned by read_flights() when no Parquet files exist yet.
_EMPTY_FLIGHTS_RELATION = """
SELECT
    NULL::TEXT      AS flight_id,
    NULL::TEXT      AS tail_number,
    NULL::TEXT      AS flight_number,
    NULL::TEXT      AS origin_icao,
    NULL::TEXT      AS destination_icao,
    NULL::TIMESTAMP AS scheduled_off,
    NULL::TIMESTAMP AS actual_off,
    NULL::TIMESTAMP AS actual_on,
    NULL::TEXT      AS status,
    NULL::TEXT      AS source,
    NULL::TIMESTAMP AS ingested_at,
    NULL::TEXT      AS airline,
    NULL::INTEGER   AS year,
    NULL::INTEGER   AS month
WHERE FALSE
"""
