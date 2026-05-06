"""OpenSky Network collector for live flight observations.

Real implementation. Fetches /flights/aircraft for one tail, caches the raw
response for 24 hours per docs/DESIGN.md §1 (filename-date governance), and
parses records into Fleet Tracker Flight objects.

Per CHECKPOINT 1 follow-up, the OpenSky /flights/aircraft endpoint:
  - requires icao24 (24-bit transponder address, lowercase hex)
  - accepts begin and end (Unix seconds), maximum window 2 days
  - returns only flights from the previous day or earlier (batch processed
    overnight); same-day flights are not yet available

If the slice returns 0 flights for an actively-flying tail, the most likely
cause is the overnight-batch lag — try a wider --hours window or wait until
tomorrow.

The __main__ block runs the full vertical slice (fetch -> cache -> Parquet
write -> DuckDB aggregate -> print). v1 expedient; v1.5 will split the
slice harness into its own module.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

from fleet_tracker import db
from fleet_tracker.model import FleetTrackerSource, Flight

logger = logging.getLogger(__name__)

OPENSKY_BASE_URL = "https://opensky-network.org/api"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
OPENSKY_MAX_WINDOW_HOURS = 48  # 2-day endpoint cap, with one-hour safety margin
DEFAULT_CACHE_ROOT = Path("data/cache/flights")
DEFAULT_FLIGHTS_ROOT = Path("data/flights")
DEFAULT_REFERENCE_ROOT = Path("data/reference")


# ---------------------------------------------------------------------------
# Pure collector surface
# ---------------------------------------------------------------------------

def fetch_flights(
    icao24: str,
    hours: int = 24,
    tail_number: Optional[str] = None,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    now: Optional[datetime] = None,
) -> list[Flight]:
    """Fetch recent flights for one aircraft from OpenSky, cached for the day.

    Args:
        icao24: 24-bit transponder address, lowercase hex (e.g., "c01234").
        hours: How many hours back from `now` to query. Capped at 48 to
               respect OpenSky's 2-day window with a safety margin.
        tail_number: Optional registration. Used as the cache filename and
                     as the tail_number on returned Flight objects. Falls
                     back to icao24 if not provided.
        cache_root: Where the JSON cache lives.
        now: Defaults to UTC now. Test seam.

    Returns:
        List of Flight objects, possibly empty.
    """
    now = now or datetime.now(timezone.utc)
    capped_hours = min(hours, OPENSKY_MAX_WINDOW_HOURS)
    if capped_hours != hours:
        logger.warning(
            "opensky: requested %dh exceeds OpenSky 2-day cap, using %dh",
            hours, capped_hours,
        )
    cache_key = (tail_number or icao24).upper()

    raw = _read_or_fetch(
        icao24=icao24,
        hours=capped_hours,
        now=now,
        cache_key=cache_key,
        cache_root=cache_root,
    )
    flights = [
        _to_flight(item, tail_number=tail_number or icao24, now=now)
        for item in raw
    ]
    _log_null_rates(raw, cache_key)
    return flights


def _read_or_fetch(
    icao24: str,
    hours: int,
    now: datetime,
    cache_key: str,
    cache_root: Path,
) -> list[dict]:
    """Cache-first read. Filename-date governance per DESIGN §1."""
    cache_root.mkdir(parents=True, exist_ok=True)
    today = now.strftime("%Y%m%d")
    cache_path = cache_root / f"{cache_key}_{today}.json"

    if cache_path.exists():
        logger.info("opensky: cache hit %s", cache_path.name)
        return json.loads(cache_path.read_text())

    # Evict stale dated files for this key (lazy eviction).
    for stale in cache_root.glob(f"{cache_key}_*.json"):
        if stale != cache_path:
            stale.unlink()

    raw = _http_fetch(icao24, hours, now)
    cache_path.write_text(json.dumps(raw))
    logger.info("opensky: wrote cache %s (%d records)", cache_path.name, len(raw))
    return raw


def _http_fetch(icao24: str, hours: int, now: datetime) -> list[dict]:
    """Single HTTP call to OpenSky /flights/aircraft.

    Supports both OpenSky auth styles: the new OAuth client-credentials flow
    (preferred; OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET) and the legacy
    HTTP Basic auth (OPENSKY_USERNAME + OPENSKY_PASSWORD). OAuth is tried
    first when the env vars are set.
    """
    load_dotenv()

    auth = None
    headers: dict[str, str] = {}
    client_id = os.environ.get("OPENSKY_CLIENT_ID")
    client_secret = os.environ.get("OPENSKY_CLIENT_SECRET")
    if client_id and client_secret:
        token = _fetch_oauth_token(client_id, client_secret)
        headers["Authorization"] = f"Bearer {token}"
    else:
        user = os.environ.get("OPENSKY_USERNAME")
        password = os.environ.get("OPENSKY_PASSWORD")
        if not user or not password:
            raise RuntimeError(
                "No OpenSky credentials. Set OPENSKY_CLIENT_ID + "
                "OPENSKY_CLIENT_SECRET (preferred OAuth flow) or "
                "OPENSKY_USERNAME + OPENSKY_PASSWORD (legacy basic auth)."
            )
        auth = (user, password)

    # OpenSky /flights/aircraft has two constraints that interact:
    #   1. Only flights from yesterday (UTC) or earlier; today is not batched yet.
    #   2. The query window must touch at most 2 UTC calendar days.
    # End is clamped to yesterday 23:59:59 UTC. Begin is clamped to no earlier
    # than the start of day-before-yesterday so the window never spills into
    # a 3rd calendar day. A naive `end=now, begin=now-Nh` would commonly span
    # 3 days near midnight UTC.
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = today_midnight - timedelta(seconds=1)
    earliest_begin = today_midnight - timedelta(days=2)
    requested_begin = end_dt - timedelta(hours=hours)
    begin_dt = max(requested_begin, earliest_begin)

    end = int(end_dt.timestamp())
    begin = int(begin_dt.timestamp())
    url = f"{OPENSKY_BASE_URL}/flights/aircraft"
    params = {"icao24": icao24.lower(), "begin": begin, "end": end}
    logger.info(
        "opensky: GET /flights/aircraft icao24=%s window=[%s, %s] auth=%s",
        icao24,
        datetime.fromtimestamp(begin, tz=timezone.utc).isoformat(),
        datetime.fromtimestamp(end, tz=timezone.utc).isoformat(),
        "oauth" if headers else "basic",
    )

    resp = requests.get(url, params=params, auth=auth, headers=headers, timeout=30)
    if resp.status_code == 404:
        # OpenSky returns 404 when no flights match. Treat as empty.
        return []
    resp.raise_for_status()
    return resp.json()


def _fetch_oauth_token(client_id: str, client_secret: str) -> str:
    """Exchange client credentials for an OAuth bearer token.

    OpenSky's token endpoint is the standard Keycloak client-credentials
    grant; the response includes access_token, expires_in (~30 min), token_type.
    No token caching: one slice run is one fetch, well under the token TTL.
    """
    resp = requests.post(
        OPENSKY_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _to_flight(item: dict, tail_number: str, now: datetime) -> Flight:
    """Convert one OpenSky /flights/aircraft record to a Fleet Tracker Flight."""
    first_seen = item["firstSeen"]
    last_seen = item.get("lastSeen")
    callsign = (item.get("callsign") or "").strip() or None
    actual_off = datetime.fromtimestamp(first_seen, tz=timezone.utc)
    actual_on = (
        datetime.fromtimestamp(last_seen, tz=timezone.utc) if last_seen else None
    )
    return Flight(
        flight_id=f"opensky:{item['icao24']}:{first_seen}",
        tail_number=tail_number,
        flight_number=callsign,
        # OpenSky natively returns ICAO airport codes (4-letter, e.g. CYUL).
        # Stored as origin_icao/destination_icao; conversion to IATA happens
        # at display time in Phase 4 via a static airport-code lookup
        # (OurAirports.com public-domain dataset).
        origin_icao=item.get("estDepartureAirport"),
        destination_icao=item.get("estArrivalAirport"),
        scheduled_off=None,
        actual_off=actual_off,
        actual_on=actual_on,
        status="completed" if actual_on else "in_flight",
        source=FleetTrackerSource.OPENSKY_LIVE,
        ingested_at=now,
    )


def _log_null_rates(raw: list[dict], cache_key: str) -> None:
    """Log null rates for departure/arrival airport per DESIGN §1 instrumentation."""
    n = len(raw)
    if n == 0:
        logger.info("opensky[%s]: 0 flights returned, no null-rate stats", cache_key)
        return
    null_dep = sum(1 for r in raw if not r.get("estDepartureAirport"))
    null_arr = sum(1 for r in raw if not r.get("estArrivalAirport"))
    pct_dep = (null_dep / n) * 100
    pct_arr = (null_arr / n) * 100
    msg = (
        f"opensky[{cache_key}]: {n} flights, "
        f"null estDepartureAirport={null_dep} ({pct_dep:.1f}%), "
        f"null estArrivalAirport={null_arr} ({pct_arr:.1f}%)"
    )
    if pct_dep > 5 or pct_arr > 5:
        logger.warning("%s — exceeds 5%% threshold from DESIGN §1", msg)
    else:
        logger.info(msg)


# ---------------------------------------------------------------------------
# Reference CSV lookup (icao24 + airline, keyed by tail_number)
# ---------------------------------------------------------------------------

def lookup_tail(
    tail_number: str,
    reference_root: Path = DEFAULT_REFERENCE_ROOT,
) -> Optional[dict]:
    """Find a tail's reference row across `data/reference/{airline}-mainline.csv`.

    Returns a dict with at minimum {tail_number, airline, icao24, aircraft_type}
    or None if not found. The airline is derived from the CSV filename
    (`ac-mainline.csv` -> "ac", `dl-mainline.csv` -> "dl"). icao24 may be
    empty/placeholder; callers should validate.
    """
    target = tail_number.upper().strip()
    for csv_path in sorted(reference_root.glob("*-mainline.csv")):
        airline = csv_path.stem.split("-")[0]  # 'ac-mainline' -> 'ac'
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("tail_number", "").upper().strip() == target:
                    row["airline"] = airline
                    return row
    return None


# ---------------------------------------------------------------------------
# Vertical slice harness (v1 lives here; will move to its own module in v1.5)
# ---------------------------------------------------------------------------

def _persist_flights_parquet(
    flights: list[Flight],
    airline: str,
    flights_root: Path,
    conn,
) -> Optional[Path]:
    """Write the fetched flights to a Hive-partitioned Parquet file.

    Partitions by airline/year/month derived from each flight's actual_off.
    For the v1 vertical slice, all flights typically land in the same
    month so a single output file is created.
    """
    if not flights:
        return None
    # The slice fetches a short window so all flights land in one or two
    # months. Pick the first; if a flight crosses a month boundary, it goes
    # in the same partition as the slice's start time.
    first = flights[0].actual_off
    year, month = first.year, first.month
    out_dir = flights_root / f"airline={airline}" / f"year={year}" / f"month={month:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "flights.parquet"

    # Build a temporary in-memory DuckDB table from the Flight list, then
    # COPY to Parquet. Cleaner than hand-rolling a Parquet writer.
    conn.execute("DROP TABLE IF EXISTS _slice_flights")
    conn.execute("""
        CREATE TEMP TABLE _slice_flights (
            flight_id TEXT, tail_number TEXT, flight_number TEXT,
            origin_icao TEXT, destination_icao TEXT,
            scheduled_off TIMESTAMP, actual_off TIMESTAMP, actual_on TIMESTAMP,
            status TEXT, source TEXT, ingested_at TIMESTAMP
        )
    """)
    rows = [
        (f.flight_id, f.tail_number, f.flight_number,
         f.origin_icao, f.destination_icao,
         f.scheduled_off, f.actual_off, f.actual_on,
         f.status, f.source, f.ingested_at)
        for f in flights
    ]
    conn.executemany(
        "INSERT INTO _slice_flights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute(f"COPY _slice_flights TO '{out_path}' (FORMAT PARQUET)")
    return out_path


def _run_aggregate_query(
    conn, tail_number: str, flights_root: Path
) -> list[tuple]:
    """Run the slice's aggregate query: distinct origin counts for one tail."""
    pattern = str(
        flights_root / "airline=*" / "year=*" / "month=*" / "*.parquet"
    )
    return conn.execute(
        f"""
        SELECT origin_icao AS origin, COUNT(*) AS n
        FROM read_parquet('{pattern}', hive_partitioning = true)
        WHERE tail_number = ?
        GROUP BY origin_icao
        ORDER BY n DESC
        """,
        [tail_number],
    ).fetchall()


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Runs the v1 vertical slice end-to-end."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="python -m fleet_tracker.collectors.opensky",
        description="Pull recent flights for one tail and run the v1 vertical slice.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tail", help="Aircraft registration; icao24 looked up from seed CSV.")
    group.add_argument("--icao24", help="24-bit transponder address (lowercase hex).")
    parser.add_argument(
        "--hours", type=int, default=48,
        help="History window in hours. Defaults to 48; OpenSky's 2-day cap is enforced.",
    )
    parser.add_argument(
        "--airline", default=None,
        help="Airline code for Parquet partitioning (ac, dl). Required when "
             "using --icao24 (ignored when using --tail, which derives airline "
             "from the seed CSV).",
    )
    parser.add_argument(
        "--no-persist", action="store_true",
        help="Skip the Parquet write + DuckDB query (fetch and print only).",
    )
    args = parser.parse_args(argv)

    # Resolve tail/icao24/airline from CLI + seed CSV.
    if args.tail:
        tail_number = args.tail.upper()
        ref = lookup_tail(tail_number)
        if ref is None:
            logger.error(
                "Tail %s not found in any data/reference/*-mainline.csv. "
                "Add it to the seed CSV or pass --icao24 directly.",
                tail_number,
            )
            return 2
        icao24 = (ref.get("icao24") or "").strip().lower()
        if not icao24 or icao24 == "todo_lookup":
            logger.error(
                "icao24 not set for %s in data/reference/%s-mainline.csv. "
                "Look up the icao24 (see docs/data-sources.md) and update the CSV, "
                "or pass --icao24 directly.",
                tail_number, ref["airline"],
            )
            return 2
        airline = ref["airline"]
    else:
        icao24 = args.icao24.lower()
        tail_number = icao24.upper()
        airline = (args.airline or "unknown").lower()

    # Fetch.
    flights = fetch_flights(icao24=icao24, hours=args.hours, tail_number=tail_number)
    print(
        f"\n{len(flights)} flights for {tail_number} (icao24={icao24}) over last {args.hours}h:"
    )
    for f in flights[:20]:
        print(
            f"  {f.actual_off:%Y-%m-%d %H:%M}  "
            f"{(f.origin_icao or '???'):>4} -> {(f.destination_icao or '???'):<4}  "
            f"({f.flight_number or '-'})"
        )
    if len(flights) > 20:
        print(f"  ... and {len(flights) - 20} more")

    if not flights:
        logger.warning(
            "No flights returned for %s. OpenSky's overnight-batch lag may be the cause; "
            "try a wider --hours window or fall back to another tail.",
            tail_number,
        )
        return 3  # non-zero so vertical slice harness can fall back per Risk #3

    if args.no_persist:
        return 0

    # Persist + aggregate.
    conn = db.connect()
    db.init_schema(conn)
    out_path = _persist_flights_parquet(
        flights=flights, airline=airline, flights_root=DEFAULT_FLIGHTS_ROOT, conn=conn,
    )
    print(f"\nWrote {out_path}")

    print(f"\nAggregate: distinct origin airports for {tail_number}:")
    rows = _run_aggregate_query(conn, tail_number=tail_number, flights_root=DEFAULT_FLIGHTS_ROOT)
    for origin, n in rows:
        print(f"  {origin or '???':>6}  {n}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
