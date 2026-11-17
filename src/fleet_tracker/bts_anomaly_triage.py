"""Bounded BTS 2025 gate-time and observed-tail overlap triage.

Reads only the two previously source-verified archives. Emits aggregate anomaly
categories, never the original flight/tail rows or potential record identifiers.
This is not a correction, causal attribution, or complete rotation analysis.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, time, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import zipfile
from zoneinfo import ZoneInfo

from fleet_tracker.bts_atomic_output import write_json_new
from fleet_tracker.bts_delta_pilot import flag, flight_date
from fleet_tracker.bts_tail_sequence import (
    FIELDS, HASHES, apply_2025_airport_zone_aliases, clock, count_pairs,
    numeric, timestamped,
)
from fleet_tracker.bts_tail_sql_verify import PAIRS, pair_measures, validate_gate

# Frozen published source study, not a target to tune or silently repair.
EXPECTED = {
    1: {"scheduled_dl": 76306, "completed": 74025, "valid": 74022,
        "scheduled_clock_conflicts": 3, "overlaps": 0,
        "candidate_pairs": 53047},
    7: {"scheduled_dl": 94066, "completed": 92245, "valid": 92245,
        "scheduled_clock_conflicts": 0, "overlaps": 2,
        "candidate_pairs": 71881},
}


def magnitude_band(minutes: float) -> str:
    """Coarse, non-identifying time difference category."""
    size = abs(minutes)
    if size <= 1:
        return "0_to_1_min"
    if size <= 5:
        return "over_1_to_5_min"
    if size <= 15:
        return "over_5_to_15_min"
    if size <= 60:
        return "over_15_to_60_min"
    return "over_60_min"


def scheduled_clock_residual(row: dict, zones: dict) -> int:
    """Circular reported-minus-derived local scheduled arrival minute residual.

    The day/date is anchored at the origin; modulo 24 hours is intentional.
    A residual is a data inconsistency, not evidence of its cause.
    """
    day = flight_date(row["FlightDate"])
    depart = datetime.combine(day, time.min) + timedelta(
        minutes=clock(row["CRSDepTime"])
    )
    utc_dep = depart.replace(tzinfo=ZoneInfo(zones[row["Origin"]])).astimezone(
        timezone.utc
    )
    local_arr = (utc_dep + timedelta(
        minutes=numeric(row["CRSElapsedTime"])
    )).astimezone(ZoneInfo(zones[row["Dest"]]))
    expected_minute = local_arr.hour * 60 + local_arr.minute
    reported_minute = clock(row["CRSArrTime"]) % 1440
    return (reported_minute - expected_minute + 720) % 1440 - 720


def triage_rows(rows, zones: dict, month: int, expected: dict) -> dict:
    """Compare independent timestamp paths and classify only aggregate anomalies."""
    count = Counter()
    rejects = Counter()
    clock_bands = Counter()
    legs = []
    db = sqlite3.connect(":memory:")
    try:
        db.execute("""CREATE TABLE valid_legs (
            id INTEGER PRIMARY KEY, tail TEXT, origin TEXT, dest TEXT,
            dep_epoch INTEGER, arr_epoch INTEGER, dep_delay REAL, arr_delay REAL
        )""")
        pending = []
        for row in rows:
            if (row.get("Reporting_Airline") or "").strip() != "DL":
                continue
            day = flight_date(row["FlightDate"])
            if day.year != 2025 or day.month != month:
                raise ValueError("Unexpected source flight date")
            count["scheduled_dl"] += 1
            canceled, diverted = flag(row["Cancelled"]), flag(row["Diverted"])
            if canceled is None or diverted is None or (canceled and diverted):
                raise ValueError("Invalid official source status flags")
            if canceled or diverted:
                count["excluded"] += 1
                continue
            count["completed"] += 1

            leg, reason = timestamped(row, zones)
            independent, independent_reason = validate_gate(row, zones)
            if reason != independent_reason or ((leg is None) != (independent is None)):
                raise AssertionError("Primary/independent clock classification differs")
            if leg is None:
                rejects[reason] += 1
                if reason == "scheduled_arrival_local_clock_mismatch":
                    delta = scheduled_clock_residual(row, zones)
                    if abs(delta) <= 1:
                        raise AssertionError("Claimed mismatch is within clock tolerance")
                    clock_bands[magnitude_band(delta)] += 1
                continue

            if (leg.tail, leg.origin, leg.dest) != independent[:3] or (
                round(leg.dep.timestamp() / 60),
                round(leg.arr.timestamp() / 60),
            ) != independent[3:5]:
                raise AssertionError("Independent actual gate epochs disagree")
            legs.append(leg)
            pending.append(independent)
            count["valid"] += 1
            if len(pending) >= 5000:
                db.executemany("""INSERT INTO valid_legs
                    (tail,origin,dest,dep_epoch,arr_epoch,dep_delay,arr_delay)
                    VALUES(?,?,?,?,?,?,?)""", pending)
                pending.clear()
        if pending:
            db.executemany("""INSERT INTO valid_legs
                (tail,origin,dest,dep_epoch,arr_epoch,dep_delay,arr_delay)
                VALUES(?,?,?,?,?,?,?)""", pending)
        db.execute("CREATE INDEX idx_tail_epoch ON valid_legs(tail, dep_epoch)")

        primary_pairs = count_pairs(legs)
        sql_pairs = pair_measures(db)
        if primary_pairs != sql_pairs:
            raise AssertionError("Independent SQL/primary pair summaries diverge")
        overlap_bands = Counter()
        for (gap,) in db.execute(
            PAIRS + "SELECT gap FROM pairs WHERE next_origin = dest AND gap < 0"
        ):
            overlap_bands[magnitude_band(gap)] += 1

        out = {
            "month": month,
            "scheduled_dl": count["scheduled_dl"],
            "completed": count["completed"],
            "valid": count["valid"],
            "timestamp_rejections": dict(sorted(rejects.items())),
            "scheduled_clock_conflicts": rejects["scheduled_arrival_local_clock_mismatch"],
            "scheduled_clock_residual_magnitude": dict(sorted(clock_bands.items())),
            "overlaps": primary_pairs["same_tail_overlap"],
            "overlap_magnitude": dict(sorted(overlap_bands.items())),
            "candidate_pairs": primary_pairs["candidate_20_to_360_min"],
            "comparison": "Primary local-to-UTC timestamps and independent actual-elapsed SQL source reconstruction agree",
            "assessment": "Unresolved source timing anomalies, not validated fixes or operational causes",
        }
        if sum(overlap_bands.values()) != out["overlaps"]:
            raise AssertionError("Overlapping-pair magnitude groups do not reconcile")
        for name, original in expected.items():
            if out[name] != original:
                raise AssertionError("Frozen historical " + name + " count differs")
        if count["completed"] + count["excluded"] != count["scheduled_dl"]:
            raise AssertionError("Source status groups do not partition scheduled DL")
        return out
    finally:
        db.close()


def triage_archive(archive: Path, month: int, zones: dict) -> dict:
    if month not in EXPECTED or archive.stat().st_size > 150_000_000:
        raise ValueError("Only bounded Jan/Jul 2025 official archives are allowed")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    if digest.hexdigest() != HASHES[month]:
        raise ValueError("Original official BTS ZIP SHA-256 does not match")
    with zipfile.ZipFile(archive) as z:
        members = [m for m in z.infolist()
                   if m.filename.lower().endswith(".csv") and not m.is_dir()]
        if len(members) != 1 or members[0].file_size > 1_000_000_000:
            raise ValueError("Expected one bounded source CSV")
        with z.open(members[0]) as raw, io.TextIOWrapper(
            raw, encoding="utf-8-sig", newline=""
        ) as stream:
            reader = csv.DictReader(stream)
            if not set(FIELDS).issubset(reader.fieldnames or []):
                raise ValueError("Missing official BTS timestamp columns")
            summary = triage_rows(reader, zones, month, EXPECTED[month])
    summary["source_zip_sha256"] = digest.hexdigest()
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--january", required=True, type=Path)
    parser.add_argument("--july", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    import airportsdata
    zones = apply_2025_airport_zone_aliases({
        name: meta["tz"] for name, meta in airportsdata.load("IATA").items()
        if meta.get("tz")
    })
    result = {
        "scope": "Official Jan/Jul 2025 Reporting_Airline=DL domestic source snapshots",
        "source_validated_against_frozen_study": True,
        "privacy": "Only aggregate counts and coarse magnitude categories; no flight/tail identifiers",
        "interpretation": "Clock contradictions and same-tail overlaps are unresolved records, not evidence of cause, repair, utilization or causal propagation",
        "months": [triage_archive(args.january, 1, zones),
                   triage_archive(args.july, 7, zones)],
    }
    write_json_new(args.output, result)
    print("PASS: source hashes, historical counts and independent gate/pair parity")
    for month in result["months"]:
        print("Month", month["month"], "clock conflicts",
              month["scheduled_clock_conflicts"], "same-tail overlaps", month["overlaps"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
