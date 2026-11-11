"""Independent BTS Delta tail-pair validation using SQLite window functions.

No imports from the primary tail-sequence implementation; gate arrival UTC is
computed from actual elapsed minutes rather than the primary's ArrDelay route.
No raw flight or tail records are retained after the temporary CI job.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, time, timezone
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from statistics import median
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import zipfile

EXPECTED_SHA = {
    1: "868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf",
    7: "74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19",
}
NEEDED = (
    "FlightDate", "Reporting_Airline", "Origin", "Dest", "Tail_Number",
    "Cancelled", "Diverted", "CRSDepTime", "CRSArrTime",
    "DepTime", "ArrTime", "DepDelay", "ArrDelay",
    "CRSElapsedTime", "ActualElapsedTime",
)
PAIRS = """
WITH ordered AS (
  SELECT tail, dest, arr_epoch, arr_delay,
         LEAD(origin) OVER w AS next_origin,
         LEAD(dep_epoch) OVER w AS next_dep_epoch,
         LEAD(dep_delay) OVER w AS next_dep_delay
  FROM valid_legs
  WINDOW w AS (PARTITION BY tail ORDER BY dep_epoch, id)
),
pairs AS (
  SELECT *, next_dep_epoch - arr_epoch AS gap
  FROM ordered WHERE next_dep_epoch IS NOT NULL
)
"""

def binary(raw):
    try:
        value = Decimal(str(raw or "").strip())
    except InvalidOperation:
        return None
    return int(value) if value in (Decimal(0), Decimal(1)) else None

def scalar(raw):
    try:
        value = Decimal(str(raw or "").strip())
        return float(value) if value.is_finite() else None
    except InvalidOperation:
        return None

def hm(raw):
    value = scalar(raw)
    if value is None or not value.is_integer():
        return None
    n = int(value)
    if n == 2400:
        return 1440
    hour, minute = divmod(n, 100)
    return hour * 60 + minute if 0 <= hour < 24 and 0 <= minute < 60 else None

def flight_day(raw):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("Invalid source date")

def clock_agrees(dt, expected):
    actual = dt.hour * 60 + dt.minute
    difference = abs(actual - (expected % 1440))
    return min(difference, 1440 - difference) <= 1

def validate_gate(row, zones):
    """Return a flight tuple independently anchored by ActualElapsedTime."""
    tail = str(row.get("Tail_Number") or "").strip().upper()
    if not tail:
        return None, "missing_tail"
    o = (row.get("Origin") or "").strip().upper()
    d = (row.get("Dest") or "").strip().upper()
    if not zones.get(o) or not zones.get(d):
        return None, "missing_airport_zone"
    try:
        origin_zone = ZoneInfo(zones[o])
        destination_zone = ZoneInfo(zones[d])
    except (ZoneInfoNotFoundError, KeyError, TypeError):
        return None, "missing_airport_zone"
    times = [hm(row.get(k)) for k in ("CRSDepTime", "CRSArrTime", "DepTime", "ArrTime")]
    if any(v is None for v in times):
        return None, "invalid_or_missing_gate_clock"
    sd, sa, ad, aa = times
    numbers = [scalar(row.get(k)) for k in ("DepDelay", "ArrDelay", "CRSElapsedTime", "ActualElapsedTime")]
    if any(v is None for v in numbers):
        return None, "missing_delay_or_elapsed"
    dep_delay, arr_delay, crs_elapsed, actual_elapsed = numbers
    if not (0 < crs_elapsed <= 1200 and 0 < actual_elapsed <= 1200):
        return None, "implausible_elapsed"
    if not (-1440 <= dep_delay <= 2880 and -1440 <= arr_delay <= 2880):
        return None, "extreme_reported_delay"
    try:
        report_date = flight_day(row["FlightDate"])
    except ValueError:
        return None, "invalid_flight_date"
    local_start = datetime.combine(report_date, time.min) + timedelta(minutes=sd)
    sched_dep = local_start.replace(tzinfo=origin_zone).astimezone(timezone.utc)
    sched_arr = sched_dep + timedelta(minutes=crs_elapsed)
    if not clock_agrees(sched_arr.astimezone(destination_zone), sa):
        return None, "scheduled_arrival_local_clock_mismatch"
    actual_dep = sched_dep + timedelta(minutes=dep_delay)
    # Independent reconstruction: primary infers arrival using ArrDelay instead.
    actual_arr = actual_dep + timedelta(minutes=actual_elapsed)
    if not clock_agrees(actual_dep.astimezone(origin_zone), ad):
        return None, "actual_departure_local_clock_mismatch"
    if not clock_agrees(actual_arr.astimezone(destination_zone), aa):
        return None, "actual_arrival_local_clock_mismatch"
    if abs((actual_arr - sched_arr).total_seconds() / 60 - arr_delay) > 1:
        return None, "arrival_delay_elapsed_mismatch"
    dep_epoch = round(actual_dep.timestamp() / 60)
    arr_epoch = round(actual_arr.timestamp() / 60)
    return (tail, o, d, dep_epoch, arr_epoch, dep_delay, arr_delay), "valid"

def pair_measures(db):
    def count_value(name, expr):
        return "COALESCE(SUM(CASE WHEN " + expr + " THEN 1 ELSE 0 END),0) AS " + name
    measurements = {
        "observed_consecutive_pairs": "1=1",
        "airport_discontinuities": "next_origin != dest",
        "airport_continuity": "next_origin = dest",
        "same_tail_overlap": "next_origin = dest AND gap < 0",
        "gap_under_20_min": "next_origin = dest AND gap >= 0 AND gap < 20",
        "candidate_20_to_360_min": "next_origin = dest AND gap BETWEEN 20 AND 360",
        "gap_6_to_24h": "next_origin = dest AND gap > 360 AND gap <= 1440",
        "gap_over_24h": "next_origin = dest AND gap > 1440",
    }
    fields = ",\n".join(count_value(k, v) for k, v in measurements.items())
    row = db.execute(PAIRS + "SELECT " + fields + " FROM pairs").fetchone()
    summary = dict(zip(measurements, [int(x or 0) for x in row]))
    tail_counts = db.execute("""
        SELECT COUNT(*), COALESCE(SUM(CASE WHEN n >= 2 THEN 1 ELSE 0 END),0)
        FROM (SELECT COUNT(*) n FROM valid_legs GROUP BY tail)
    """).fetchone()
    summary["unique_valid_tails"] = int(tail_counts[0])
    summary["tails_with_2plus_valid_legs"] = int(tail_counts[1])
    candidate_filter = "next_origin = dest AND gap BETWEEN 20 AND 360"
    gap_rows = db.execute(PAIRS + """
        SELECT gap FROM pairs WHERE """ + candidate_filter + " ORDER BY gap").fetchall()
    summary["candidate_median_ground_minutes"] = round(median(x[0] for x in gap_rows), 1) if gap_rows else None
    quadrants = {
        "late_inbound": "arr_delay >= 15",
        "not_late_inbound": "arr_delay < 15",
    }
    bucket_filters = {
        "20_to_59": "gap BETWEEN 20 AND 59",
        "60_to_119": "gap BETWEEN 60 AND 119",
        "120_to_360": "gap BETWEEN 120 AND 360",
    }
    def rate(n, d):
        return round(n / d, 6) if d else None
    group_result = {}
    for group, predicate in quadrants.items():
        n, late = db.execute(PAIRS + """
          SELECT COUNT(*), COALESCE(SUM(CASE WHEN next_dep_delay >= 15 THEN 1 ELSE 0 END),0)
          FROM pairs WHERE """ + candidate_filter + " AND " + predicate).fetchone()
        group_result[group] = (int(n), int(late))
    association = {
        "previous_arrival_late_15": group_result["late_inbound"][0],
        "previous_arrival_not_late_15": group_result["not_late_inbound"][0],
        "next_departure_late_after_late_arrival": group_result["late_inbound"][1],
        "next_departure_late_after_not_late_arrival": group_result["not_late_inbound"][1],
        "next_late_rate_after_late_arrival": rate(*group_result["late_inbound"][::-1]),
        "next_late_rate_after_not_late_arrival": rate(*group_result["not_late_inbound"][::-1]),
    }
    detailed = {}
    for band, filter_sql in bucket_filters.items():
        detailed[band] = {}
        for group, predicate in quadrants.items():
            n, late = db.execute(PAIRS + """
             SELECT COUNT(*), COALESCE(SUM(CASE WHEN next_dep_delay >= 15 THEN 1 ELSE 0 END),0)
             FROM pairs WHERE """ + candidate_filter + " AND " + filter_sql + " AND " + predicate).fetchone()
            detailed[band][group] = {
                "candidate_connections": int(n),
                "next_departure_late": int(late),
                "rate": rate(int(late), int(n)),
            }
    association["actual_ground_gap_bands"] = detailed
    summary["descriptive_delay_association"] = association
    if sum(v[0] for v in group_result.values()) != summary["candidate_20_to_360_min"]:
        raise AssertionError("SQL candidates fail quadrant reconciliation")
    return summary

def read_month(path, month, zones, expected_sha):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    if h.hexdigest() != expected_sha:
        raise ValueError("Source SHA mismatch; require explicit new review")
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE valid_legs(
      id INTEGER PRIMARY KEY, tail TEXT, origin TEXT, dest TEXT,
      dep_epoch INTEGER, arr_epoch INTEGER, dep_delay REAL, arr_delay REAL)""")
    c = Counter()
    rejects = Counter()
    with zipfile.ZipFile(path) as z:
        csv_files = [f for f in z.infolist() if f.filename.lower().endswith(".csv") and not f.is_dir()]
        if len(csv_files) != 1 or csv_files[0].file_size > 1_000_000_000:
            raise ValueError("Untrusted source ZIP contents")
        with z.open(csv_files[0]) as stream, io.TextIOWrapper(stream, encoding="utf-8-sig", newline="") as wrapped:
            reader = csv.DictReader(wrapped)
            if not set(NEEDED).issubset(set(reader.fieldnames or ())):
                raise ValueError("Missing official BTS clock/delay columns")
            insert = []
            for rec in reader:
                if (rec["Reporting_Airline"] or "").strip() != "DL":
                    continue
                c["scheduled"] += 1
                ca, dv = binary(rec["Cancelled"]), binary(rec["Diverted"])
                if ca is None or dv is None:
                    c["invalid_status"] += 1
                    continue
                if ca or dv:
                    c["excluded"] += 1
                    continue
                c["eligible"] += 1
                leg, reason = validate_gate(rec, zones)
                if leg is None:
                    rejects[reason] += 1
                else:
                    c["valid"] += 1
                    insert.append(leg)
                if len(insert) >= 5000:
                    db.executemany(
                        "INSERT INTO valid_legs(tail,origin,dest,dep_epoch,arr_epoch,dep_delay,arr_delay) VALUES(?,?,?,?,?,?,?)",
                        insert,
                    )
                    insert.clear()
            if insert:
                db.executemany(
                    "INSERT INTO valid_legs(tail,origin,dest,dep_epoch,arr_epoch,dep_delay,arr_delay) VALUES(?,?,?,?,?,?,?)",
                    insert,
                )
    db.execute("CREATE INDEX idx_tail_start ON valid_legs(tail,dep_epoch)")
    pairs = pair_measures(db)
    db.close()
    return {
        "month": month, "source_sha256": h.hexdigest(),
        "scheduled_dl": c["scheduled"], "complete_nondiverted": c["eligible"],
        "valid_timestamped_legs": c["valid"],
        "invalid_status": c["invalid_status"],
        "excluded_canceled_or_diverted": c["excluded"],
        "rejection_reasons": dict(rejects), "pairs": pairs,
    }

def compare(actual, reference):
    if actual["source_sha256"] != reference["source_sha256"]:
        raise AssertionError("Source hash changed")
    for key in ("scheduled_dl", "complete_nondiverted", "valid_timestamped_legs",
                "excluded_canceled_or_diverted", "invalid_status"):
        if actual[key] != reference[key]:
            raise AssertionError(f"{key} mismatch: {actual[key]} vs {reference[key]}")
    if actual["rejection_reasons"] != reference["rejection_reasons"]:
        raise AssertionError("Timestamp reject reasons diverged: "
                             + str((actual["rejection_reasons"], reference["rejection_reasons"])))
    for key, n in actual["pairs"].items():
        ref_n = reference["pairs"].get(key)
        if n != ref_n:
            raise AssertionError(f"SQL/primary pair discrepancy in {key}: {n} vs {ref_n}")
    return True

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--january", type=Path, required=True)
    parser.add_argument("--july", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    import airportsdata
    tz_by_code = {k: v.get("tz") for k, v in airportsdata.load("IATA").items() if v.get("tz")}
    if tz_by_code.get("PBI") not in (None, "America/New_York"):
        raise ValueError("Conflicting PBI timezone, stop")
    tz_by_code["PBI"] = "America/New_York"
    ref = json.loads(args.expected.read_text())
    results = []
    for month, path in ((1, args.january), (7, args.july)):
        primary = next(x for x in ref["months"] if x["month"] == month)
        if EXPECTED_SHA[month] != primary["source_sha256"]:
            raise ValueError("Prior result is from an unapproved source archive")
        sql = read_month(path, month, tz_by_code, EXPECTED_SHA[month])
        compare(sql, primary)
        results.append({
            "month": month,
            "verdict": "INDEPENDENT_WINDOW_SQL_PAIR_PARITY_PASS",
            "source_sha256": sql["source_sha256"],
            "valid_gate_rows": sql["valid_timestamped_legs"],
            "matched_candidate_pairs": sql["pairs"]["candidate_20_to_360_min"],
            "association_quadrants": {
                k: sql["pairs"]["descriptive_delay_association"][k] for k in (
                    "previous_arrival_late_15", "previous_arrival_not_late_15",
                    "next_departure_late_after_late_arrival",
                    "next_departure_late_after_not_late_arrival"
                )
            },
        })
    summary = {
        "status": "INDEPENDENT_WINDOW_SQL_PAIR_PARITY_PASS",
        "method": "independent actual-elapsed timestamp reconstruction; SQL LEAD tail pairing; count/association source parity",
        "not_proven": "full tail rotations, coverage of unreported flights, causal delay propagation",
        "months": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
