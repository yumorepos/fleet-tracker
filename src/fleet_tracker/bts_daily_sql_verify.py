"""Independent SQLite audit of daily Delta BTS sensitivity results.

Loads the same hashed BTS ZIPs independently, aggregates raw rows using SQL,
then rebuilds threshold, day-type and leave-one-day-out comparisons without
using the primary Python cell counters or matching calculation. No raw output.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import zipfile

from fleet_tracker.bts_atomic_output import write_json_new
from fleet_tracker.bts_bank_sql_verify import clock_group, numeric_flag
from fleet_tracker.bts_delta_pilot import flight_date
from fleet_tracker.bts_driver_profile import EXPECTED_SHA

GROUPS = ("ATL_origin", "Other_origin")
REQUIRED = ("FlightDate", "Reporting_Airline", "Origin", "Dest",
            "CRSDepTime", "Cancelled", "Diverted", "ArrDel15")
COMPARE_FIELDS = (
    "minimum_valid_arrivals_each_group", "selected_days", "matched_strata",
    "atl_total_valid", "other_total_valid", "atl_matched_valid",
    "other_matched_valid", "atl_matched_on_time", "other_matched_on_time",
    "atl_coverage", "other_coverage",
    "matched_unadjusted_atl_rate", "matched_unadjusted_other_rate",
    "pooled_standardized_atl_rate", "pooled_standardized_other_rate",
    "all_flights_unadjusted_gap_pp", "matched_subset_unadjusted_gap_pp",
    "pooled_standardized_gap_pp", "selection_shift_pp", "reweight_shift_pp",
    "coverage_verdict",
)


def create_sql(archive: Path, month: int):
    if month not in EXPECTED_SHA or archive.stat().st_size > 150_000_000:
        raise ValueError("Only bounded January/July 2025 sources")
    hasher = hashlib.sha256()
    with archive.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(part)
    digest = hasher.hexdigest()
    if digest != EXPECTED_SHA[month]:
        raise ValueError("Independent SQL source digest does not match")
    db = sqlite3.connect(":memory:")
    try:
        db.execute("""CREATE TABLE flight (
            day INTEGER NOT NULL, grp TEXT NOT NULL, bank TEXT NOT NULL,
            dest TEXT NOT NULL, cancel INTEGER NOT NULL, divert INTEGER NOT NULL,
            valid INTEGER NOT NULL, ont INTEGER NOT NULL
        )""")
        with zipfile.ZipFile(archive) as z:
            files = [f for f in z.infolist()
                     if f.filename.lower().endswith(".csv") and not f.is_dir()]
            if len(files) != 1 or files[0].file_size > 1_000_000_000:
                raise ValueError("Unexpected ZIP contents")
            with z.open(files[0]) as raw, io.TextIOWrapper(
                    raw, encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not set(REQUIRED).issubset(set(reader.fieldnames or ())):
                    raise ValueError("Missing independent SQL source fields")
                pending = []
                for r in reader:
                    if (r["Reporting_Airline"] or "").strip() != "DL":
                        continue
                    d = flight_date(r["FlightDate"])
                    if d.year != 2025 or d.month != month:
                        raise ValueError("Unexpected source date in SQL verifier")
                    origin, dest = (r["Origin"] or "").strip().upper(), (r["Dest"] or "").strip().upper()
                    if (len(origin) != 3 or not origin.isalpha()
                            or len(dest) != 3 or not dest.isalpha()):
                        raise ValueError("Invalid airport identifier")
                    c, dv = numeric_flag(r["Cancelled"]), numeric_flag(r["Diverted"])
                    if c and dv:
                        raise ValueError("Conflicting BTS status flags")
                    arrival = (numeric_flag(r["ArrDel15"]) if not (c or dv) else None)
                    pending.append((
                        d.day, GROUPS[0] if origin == "ATL" else GROUPS[1],
                        clock_group(r["CRSDepTime"]), dest, c, dv,
                        0 if c or dv else 1, 1 if arrival == 0 else 0,
                    ))
                    if len(pending) >= 5000:
                        db.executemany("INSERT INTO flight VALUES (?,?,?,?,?,?,?,?)", pending)
                        pending.clear()
                if pending:
                    db.executemany("INSERT INTO flight VALUES (?,?,?,?,?,?,?,?)", pending)
        db.execute("""CREATE TABLE cell AS
            SELECT day, grp, bank, dest,
                   COUNT(*) AS scheduled, SUM(cancel) AS canceled,
                   SUM(divert) AS diverted, SUM(valid) AS n, SUM(ont) AS o
            FROM flight GROUP BY day, grp, bank, dest""")
        db.execute("DROP TABLE flight")
        db.execute("CREATE INDEX day_idx ON cell(day,grp,bank,dest)")
        return db, digest
    except BaseException:
        db.close()
        raise


def _round_ratio(numerator, denominator):
    return round(numerator / denominator, 6) if denominator else None


def independent_comparison(db, days, threshold):
    """SQL derives flight-set cells; this method independently prices groups."""
    days = sorted(set(days))
    if not days:
        raise ValueError("No selected days")
    place = ",".join("?" for _ in days)
    totals = {g: (0, 0) for g in GROUPS}
    for group, n, o in db.execute(
        f"SELECT grp, SUM(n), SUM(o) FROM cell WHERE day IN ({place}) GROUP BY grp", days
    ):
        totals[group] = (n, o)
    a_all, a_ont = totals[GROUPS[0]]
    b_all, b_ont = totals[GROUPS[1]]
    source = db.execute(f"""
        WITH daily AS (
            SELECT grp, bank, dest, SUM(n) AS n, SUM(o) AS o
            FROM cell WHERE day IN ({place}) GROUP BY grp, bank, dest
        )
        SELECT aa.n, aa.o, bb.n, bb.o
        FROM daily aa JOIN daily bb ON aa.bank=bb.bank AND aa.dest=bb.dest
        WHERE aa.grp='ATL_origin' AND bb.grp='Other_origin'
          AND aa.n >= ? AND bb.n >= ?
        ORDER BY aa.bank, aa.dest
    """, (*days, threshold, threshold)).fetchall()
    na = sum(r[0] for r in source)
    oa = sum(r[1] for r in source)
    nb = sum(r[2] for r in source)
    ob = sum(r[3] for r in source)
    full = (100 * (a_ont / a_all - b_ont / b_all)
            if a_all and b_all else None)
    raw = 100 * (oa / na - ob / nb) if na and nb else None
    pooled = na + nb
    std_a = (sum((a+b) * ao/a for a, ao, b, bo in source) / pooled
             if pooled else None)
    std_b = (sum((a+b) * bo/b for a, ao, b, bo in source) / pooled
             if pooled else None)
    common = (100 * (std_a - std_b) if pooled else None)
    ca, cb = _round_ratio(na, a_all), _round_ratio(nb, b_all)
    return {
        "minimum_valid_arrivals_each_group": threshold,
        "selected_days": len(days), "matched_strata": len(source),
        "atl_total_valid": a_all, "other_total_valid": b_all,
        "atl_matched_valid": na, "other_matched_valid": nb,
        "atl_matched_on_time": oa, "other_matched_on_time": ob,
        "atl_coverage": ca, "other_coverage": cb,
        "matched_unadjusted_atl_rate": _round_ratio(oa, na),
        "matched_unadjusted_other_rate": _round_ratio(ob, nb),
        "pooled_standardized_atl_rate": round(std_a, 6) if pooled else None,
        "pooled_standardized_other_rate": round(std_b, 6) if pooled else None,
        "all_flights_unadjusted_gap_pp": round(full, 3) if full is not None else None,
        "matched_subset_unadjusted_gap_pp": round(raw, 3) if raw is not None else None,
        "pooled_standardized_gap_pp": round(common, 3) if common is not None else None,
        "selection_shift_pp": (round(round(raw, 3) - round(full, 3), 3)
                               if raw is not None and full is not None else None),
        "reweight_shift_pp": (round(round(common, 3) - round(raw, 3), 3)
                              if common is not None and raw is not None else None),
        "coverage_verdict": ("EXPLORATORY_SUBSET"
                             if pooled and ca >= .5 and cb >= .5
                             else "LOW_COVERAGE_OR_NO_MATCH"),
    }


def verify_month(db, month, primary):
    if primary.get("month") != month or primary.get("year") != 2025:
        raise ValueError("Incorrect research reporting month")
    days = list(range(1, 32))
    checked = 0
    for threshold in (10, 25, 50):
        expected = independent_comparison(db, days, threshold)
        actual = primary["threshold_sensitivity"][str(threshold)]
        for field in COMPARE_FIELDS:
            if expected[field] != actual[field]:
                raise AssertionError(f"Month {month} threshold {threshold}: {field}: {actual[field]} != {expected[field]}")
        checked += 1
    for name, selected in (
        ("weekday", [d for d in days if date(2025, month, d).weekday() < 5]),
        ("weekend", [d for d in days if date(2025, month, d).weekday() >= 5]),
    ):
        expected = independent_comparison(db, selected, 25)
        for field in COMPARE_FIELDS:
            if primary["weekday_weekend"][name][field] != expected[field]:
                raise AssertionError(f"Month {month} {name}: {field} disagrees")
        checked += 1
    leave = primary["leave_one_day_out_25"]
    if len(leave["observations"]) != 31 or {
            r["excluded_day"] for r in leave["observations"]} != set(days):
        raise AssertionError("Leave-one-day-out exclusion set must contain all 31 days")
    for record in leave["observations"]:
        removed = record["excluded_day"]
        expected = independent_comparison(db, [d for d in days if d != removed], 25)
        for field, key in (("standardized_gap_pp", "pooled_standardized_gap_pp"),
                           ("matched_strata", "matched_strata"),
                           ("atl_coverage", "atl_coverage"),
                           ("other_coverage", "other_coverage")):
            if record[field] != expected[key]:
                raise AssertionError(f"Month {month}, excluded {removed}: {field}")
        checked += 1
    if checked != 36:
        raise AssertionError("Expected three thresholds, two day types and 31 leave-one-out exclusions")
    found = [r["standardized_gap_pp"] for r in leave["observations"]
             if r["standardized_gap_pp"] is not None]
    full = primary["threshold_sensitivity"]["25"]["pooled_standardized_gap_pp"]
    expected_summary = {
        "valid_exclusions": len(found),
        "min_gap_pp": min(found) if found else None,
        "max_gap_pp": max(found) if found else None,
        "largest_absolute_shift_from_full_pp": (
            round(max(abs(v - full) for v in found), 3)
            if found and full is not None else None),
        "sign_flips_vs_full": (sum(v * full < 0 for v in found)
                               if full is not None else None),
        "recompute_matches_after_exclusion": True,
    }
    for key, value in expected_summary.items():
        if leave[key] != value:
            raise AssertionError(f"Month {month}: invalid leave-one-day-out summary {key}")
    if len(primary["daily_unadjusted"]) != 31 or {
            r["day"] for r in primary["daily_unadjusted"]} != set(days):
        raise AssertionError("Expected exactly 31 daily records")
    observed = db.execute("""
        SELECT day, grp, SUM(n), SUM(o)
        FROM cell GROUP BY day, grp ORDER BY day, grp
    """).fetchall()
    lookup = {(day, group): (n, o) for day, group, n, o in observed}
    for row in primary["daily_unadjusted"]:
        d = row["day"]
        an, ao = lookup.get((d, GROUPS[0]), (0, 0))
        bn, bo = lookup.get((d, GROUPS[1]), (0, 0))
        diff = round(100 * (ao / an - bo / bn), 3) if an and bn else None
        if (row["atl_valid"], row["other_valid"], row["atl_on_time"],
                row["other_on_time"], row["unadjusted_gap_pp"]) != (an, bn, ao, bo, diff):
            raise AssertionError(f"Month {month}: daily population mismatch {d}")
    return {"month": month, "checks": checked, "daily_population_checks": 31,
            "verdict": "INDEPENDENT_SQL_PARITY_PASS"}


def run(archives, report_path: Path, output: Path):
    report = json.loads(report_path.read_text())
    if len(report.get("months", [])) != 2 or {m["month"] for m in report["months"]} != {1, 7}:
        raise ValueError("Expected both source-verified months")
    outcomes = []
    for month in (1, 7):
        db, digest = create_sql(archives[month], month)
        try:
            entry = next(m for m in report["months"] if m["month"] == month)
            if entry.get("source_sha256") != digest:
                raise ValueError("Research report/source ZIP digest disagreement")
            outcomes.append(verify_month(db, month, entry))
        finally:
            db.close()
    write_json_new(output, {"status": "INDEPENDENT_SQL_PARITY_PASS",
                             "scope": "Both official 2025 months, threshold/day-type/LOO SQL aggregation",
                             "months": outcomes})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--january", type=Path, required=True)
    parser.add_argument("--july", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args(argv)
    run({1: a.january, 7: a.july}, a.report, a.output)
    print("Independent SQL parity verified for 36 comparisons and 31 days per month.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
