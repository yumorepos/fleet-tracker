"""Materialize a bounded, aggregate-only BTS reliability reporting layer.

Inputs are outputs of the existing validated Delta pilot and driver-profile
scripts, NOT raw flights. This transforms their aggregates; it does not
independently revalidate official source data or infer causal effects.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from fleet_tracker.bts_driver_profile import EXPECTED_SHA

SEGMENTS = ("ATL_origin", "Other_origin")
COUNT_FIELDS = (
    "scheduled", "canceled", "diverted", "completed",
    "valid_arrival_flags", "on_time", "late_arrival_15",
)


def count(row: dict, key: str) -> int:
    value = row[key]
    if type(value) is not int or value < 0:
        raise ValueError(f"{key} must be a nonnegative integer")
    return value


def by_month(items: list, source: str) -> dict:
    if len(items) != 2:
        raise ValueError(f"{source}: expected precisely January and July 2025")
    indexed = {item["month"]: item for item in items}
    if set(indexed) != {1, 7} or len(indexed) != len(items):
        raise ValueError(f"{source}: duplicate or unexpected months")
    return indexed


def validate(pilot: dict, profile: dict) -> tuple[list[tuple], list[tuple]]:
    """Fail closed on provenance, grains, and integer-denominator parity."""
    if pilot.get("both_months_core_gate") != "GO":
        raise ValueError("Pilot quality gate has not passed")
    original = by_month(pilot["months"], "pilot")
    causes = by_month(profile["months"], "profile")
    months, segments = [], []

    for month in (1, 7):
        base, detail = original[month], causes[month]
        sha = EXPECTED_SHA[month]
        if (base.get("year") != 2025 or detail.get("year") != 2025
                or base.get("reporting_carrier_filter") != "Reporting_Airline=DL"
                or base.get("source_zip_sha256") != sha
                or detail.get("source_sha256") != sha
                or base.get("core_kpi_gate") != "GO"
                or detail.get("verdict") != "GO_FOR_DESCRIPTIVE_CAUSE_AUDIT"):
            raise ValueError(f"Month {month}: study scope or source validation mismatch")

        baseline = base["counts"]
        all_group = detail["groups"]["ALL_DL"]
        expected = {
            "scheduled": count(baseline, "dl"),
            "canceled": count(baseline, "canceled"),
            "diverted": count(baseline, "diverted"),
            "completed": count(baseline, "eligible"),
            "valid_arrival_flags": count(baseline, "arr15_valid"),
            "on_time": count(baseline, "ontime"),
            "late_arrival_15": count(all_group, "late_arrival_15"),
        }
        for key in COUNT_FIELDS:
            if count(all_group, key) != expected[key]:
                raise ValueError(f"Month {month}: pilot/profile mismatch in {key}")
        if (expected["scheduled"] != expected["canceled"] +
                expected["diverted"] + expected["completed"]
                or expected["on_time"] + expected["late_arrival_15"]
                != expected["valid_arrival_flags"]
                or expected["valid_arrival_flags"] > expected["completed"]):
            raise ValueError(f"Month {month}: incompatible KPI denominators")

        origin_counts = {key: 0 for key in COUNT_FIELDS}
        for group in SEGMENTS:
            row = detail["groups"][group]
            numbers = [count(row, key) for key in COUNT_FIELDS]
            for key, value in zip(COUNT_FIELDS, numbers):
                origin_counts[key] += value
            complete = count(row, "late_arrivals_with_complete_cause_detail")
            missing = count(row, "late_arrivals_missing_cause_detail")
            positive = count(row["reported_positive_cause_flight_count"],
                             "LateAircraftDelay")
            minutes = row["reported_cause_minutes"]["LateAircraftDelay"]
            if (type(minutes) not in (int, float) or not (0 <= minutes < 1e12)
                    or complete + missing != count(row, "late_arrival_15")
                    or positive > complete
                    or numbers[5] + numbers[6] != numbers[4]
                    or numbers[4] > numbers[3]
                    or numbers[0] != numbers[1] + numbers[2] + numbers[3]):
                raise ValueError(f"Month {month}, {group}: invalid cause or KPI grain")
            segments.append((month, group, *numbers, complete, missing,
                             positive, float(minutes)))

        if origin_counts != expected:
            raise ValueError(f"Month {month}: origin segments do not reconcile")
        for category in ("late_arrivals_with_complete_cause_detail",
                         "late_arrivals_missing_cause_detail"):
            if sum(count(detail["groups"][group], category)
                   for group in SEGMENTS) != count(all_group, category):
                raise ValueError(f"Month {month}: cause coverage segments disagree")
        source_positive = count(all_group["reported_positive_cause_flight_count"],
                                "LateAircraftDelay")
        if sum(row[-2] for row in segments[-2:]) != source_positive:
            raise ValueError(f"Month {month}: positive late-aircraft counts disagree")
        source_minutes = all_group["reported_cause_minutes"]["LateAircraftDelay"]
        if abs(sum(row[-1] for row in segments[-2:]) - source_minutes) > .011:
            raise ValueError(f"Month {month}: reported cause minutes disagree")
        months.append((month, sha, *(expected[key] for key in COUNT_FIELDS)))

    return months, segments


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE month_kpi (
    month INTEGER PRIMARY KEY CHECK (month IN (1,7)),
    source_sha256 TEXT NOT NULL,
    scheduled INTEGER NOT NULL, canceled INTEGER NOT NULL,
    diverted INTEGER NOT NULL, completed INTEGER NOT NULL,
    valid_arrival_flags INTEGER NOT NULL, on_time INTEGER NOT NULL,
    late_arrival_15 INTEGER NOT NULL
);
CREATE TABLE origin_kpi (
    month INTEGER NOT NULL REFERENCES month_kpi(month),
    origin_group TEXT NOT NULL CHECK (origin_group IN ('ATL_origin','Other_origin')),
    scheduled INTEGER NOT NULL, canceled INTEGER NOT NULL,
    diverted INTEGER NOT NULL, completed INTEGER NOT NULL,
    valid_arrival_flags INTEGER NOT NULL, on_time INTEGER NOT NULL,
    late_arrival_15 INTEGER NOT NULL, complete_cause_late INTEGER NOT NULL,
    missing_cause_late INTEGER NOT NULL, positive_lateaircraft INTEGER NOT NULL,
    reported_lateaircraft_minutes REAL NOT NULL,
    PRIMARY KEY (month, origin_group)
);
CREATE VIEW v_month_reliability AS
SELECT month, scheduled, completed, valid_arrival_flags, on_time,
       canceled, diverted,
       ROUND(1.0 * on_time / NULLIF(valid_arrival_flags, 0), 6) AS arrival_ontime_rate,
       ROUND(1.0 * canceled / NULLIF(scheduled, 0), 6) AS cancellation_rate,
       ROUND(1.0 * diverted / NULLIF(scheduled, 0), 6) AS diversion_rate
FROM month_kpi;
CREATE VIEW v_origin_reliability AS
SELECT month, origin_group, scheduled, completed, valid_arrival_flags, on_time,
       late_arrival_15, complete_cause_late, missing_cause_late,
       positive_lateaircraft, reported_lateaircraft_minutes,
       ROUND(1.0 * on_time / NULLIF(valid_arrival_flags, 0), 6) AS arrival_ontime_rate,
       ROUND(1.0 * canceled / NULLIF(scheduled, 0), 6) AS cancellation_rate,
       ROUND(1.0 * diverted / NULLIF(scheduled, 0), 6) AS diversion_rate,
       ROUND(1.0 * positive_lateaircraft / NULLIF(complete_cause_late, 0), 6)
           AS reported_lateaircraft_positive_share_of_complete_late
FROM origin_kpi;
"""


def build(pilot: dict, profile: dict, output: Path) -> None:
    """Write a new SQLite file; never overwrite an existing result."""
    months, segments = validate(pilot, profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    fd, temporary = tempfile.mkstemp(prefix=".bts-report-", suffix=".sqlite",
                                    dir=output.parent)
    os.close(fd)
    try:
        with sqlite3.connect(temporary) as db:
            db.executescript(SCHEMA)
            db.executemany("INSERT INTO month_kpi VALUES (?,?,?,?,?,?,?,?,?)",
                           months)
            db.executemany("INSERT INTO origin_kpi VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           segments)
            db.commit()
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    build(json.loads(args.pilot.read_text()),
          json.loads(args.profile.read_text()), args.output)
    print(f"Created aggregate-only SQLite reporting layer: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
