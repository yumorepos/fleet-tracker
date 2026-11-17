"""Independent SQLite check of *every* paired day-resampling replicate.

Re-reads and SHA-verifies both official BTS sources through the pre-existing
independent SQLite ingestion. Per-replicate matching uses SQL weighted daily
cells, not the primary Python Counter routine. Rebuilds all summary quantiles.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from math import ceil
from pathlib import Path
import random

from fleet_tracker.bts_atomic_output import write_json_new
from fleet_tracker.bts_daily_sql_verify import create_sql

DESIGN = "delta-2025-paired-day-resampling-v1"
METHODS = ("iid_day", "moving_block3")
FIELDS = (
    "unadjusted_gap_pp", "standardized_gap_pp", "matched_strata",
    "atl_total_valid", "other_total_valid", "atl_matched_valid",
    "other_matched_valid", "atl_coverage", "other_coverage",
    "coverage_gate_passed",
)
SUMMARY_FIELDS = (
    "replicates", "defined_standardized_replicates",
    "undefined_standardized_replicates", "reference_standardized_gap_pp",
    "standardized_gap_p05_pp", "standardized_gap_median_pp",
    "standardized_gap_p95_pp", "unadjusted_gap_p05_pp",
    "unadjusted_gap_median_pp", "unadjusted_gap_p95_pp",
    "atl_coverage_p05", "other_coverage_p05", "matched_strata_median",
    "coverage_gate_failure_count", "positive_standardized_count",
    "negative_standardized_count", "exact_zero_standardized_count",
    "opposite_sign_count",
)


def make_draw(seed: int, month: int, method: str, index: int):
    """Independent implementation of fixed SHA-derived sample selection."""
    digest = hashlib.sha256(
        f"{DESIGN}|{seed}|{month}|{method}|{index}".encode("ascii")
    ).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    selected = []
    if method == "iid_day":
        for _ in range(31):
            selected.append(rng.randint(1, 31))
    elif method == "moving_block3":
        while len(selected) < 31:
            start = rng.randint(1, 29)
            for d in (start, start + 1, start + 2):
                if len(selected) < 31:
                    selected.append(d)
    else:
        raise ValueError("Unexpected resampling scheme")
    return selected


def from_sql(db, day_draw):
    """SQL multiplies each source day by its bootstrap multiplicity."""
    if len(day_draw) != 31 or any(type(d) is not int or not 1 <= d <= 31
                                  for d in day_draw):
        raise ValueError("Invalid resampled date sequence")
    weight = Counter(day_draw)
    query_values = ",".join("(?, ?)" for _ in weight)
    args = tuple(x for day, w in sorted(weight.items()) for x in (day, w))
    cells = db.execute(f"""
        WITH sampled(day, k) AS (VALUES {query_values})
        SELECT c.grp,c.bank,c.dest, SUM(c.n * sampled.k), SUM(c.o * sampled.k)
        FROM cell c JOIN sampled ON c.day=sampled.day
        GROUP BY c.grp,c.bank,c.dest ORDER BY c.bank,c.dest,c.grp
    """, args).fetchall()
    overall = {"ATL_origin": [0, 0], "Other_origin": [0, 0]}
    group = {}
    for origin, bank, dest, n, on in cells:
        overall[origin][0] += int(n)
        overall[origin][1] += int(on)
        group[(origin, bank, dest)] = (int(n), int(on))
    a_total, a_ont = overall["ATL_origin"]
    b_total, b_ont = overall["Other_origin"]
    raw = (round(100 * (a_ont/a_total - b_ont/b_total), 3)
           if a_total and b_total else None)
    match = []
    for bank, dest in sorted({(bank, dest) for _, bank, dest in group}):
        a_n, a_on = group.get(("ATL_origin", bank, dest), (0, 0))
        b_n, b_on = group.get(("Other_origin", bank, dest), (0, 0))
        if min(a_n, b_n) >= 25:
            match.append((a_n, a_on, b_n, b_on))
    a_matched = sum(row[0] for row in match)
    b_matched = sum(row[2] for row in match)
    pooled = a_matched + b_matched
    gap = (
        round(100 * sum(
            (a + b) * (a_on / a - b_on / b)
            for a, a_on, b, b_on in match
        ) / pooled, 3) if pooled else None
    )
    a_cov = round(a_matched / a_total, 6) if a_total else None
    b_cov = round(b_matched / b_total, 6) if b_total else None
    gate = bool(pooled and a_cov is not None and b_cov is not None
                and min(a_cov, b_cov) >= 0.5)
    return {
        "unadjusted_gap_pp": raw,
        "standardized_gap_pp": gap,
        "matched_strata": len(match),
        "atl_total_valid": a_total, "other_total_valid": b_total,
        "atl_matched_valid": a_matched, "other_matched_valid": b_matched,
        "atl_coverage": a_cov, "other_coverage": b_cov,
        "coverage_gate_passed": gate,
    }


def quantile(values, level):
    vals = sorted(v for v in values if v is not None)
    return vals[max(0, ceil(len(vals) * level / 100) - 1)] if vals else None


def independent_summary(rows, reference):
    gap = [r["standardized_gap_pp"] for r in rows
           if r["standardized_gap_pp"] is not None]
    raw = [r["unadjusted_gap_pp"] for r in rows
           if r["unadjusted_gap_pp"] is not None]
    coverage_a = [r["atl_coverage"] for r in rows if r["atl_coverage"] is not None]
    coverage_b = [r["other_coverage"] for r in rows if r["other_coverage"] is not None]
    return {
        "replicates": len(rows),
        "defined_standardized_replicates": len(gap),
        "undefined_standardized_replicates": len(rows) - len(gap),
        "reference_standardized_gap_pp": reference,
        "standardized_gap_p05_pp": quantile(gap, 5),
        "standardized_gap_median_pp": quantile(gap, 50),
        "standardized_gap_p95_pp": quantile(gap, 95),
        "unadjusted_gap_p05_pp": quantile(raw, 5),
        "unadjusted_gap_median_pp": quantile(raw, 50),
        "unadjusted_gap_p95_pp": quantile(raw, 95),
        "atl_coverage_p05": quantile(coverage_a, 5),
        "other_coverage_p05": quantile(coverage_b, 5),
        "matched_strata_median": quantile(
            [r["matched_strata"] for r in rows], 50),
        "coverage_gate_failure_count": sum(
            not r["coverage_gate_passed"] for r in rows),
        "positive_standardized_count": sum(v > 0 for v in gap),
        "negative_standardized_count": sum(v < 0 for v in gap),
        "exact_zero_standardized_count": sum(v == 0 for v in gap),
        "opposite_sign_count": (
            sum(v * reference < 0 for v in gap) if reference is not None else None),
    }


def verify_month(db, month, report_month, prior_daily, seed, count):
    ref = from_sql(db, list(range(1, 32)))
    for field in FIELDS:
        if ref[field] != report_month["reference"][field]:
            raise AssertionError(f"{month} source reference mismatch: {field}")
    orig = prior_daily["threshold_sensitivity"]["25"]
    if (ref["standardized_gap_pp"] != orig["pooled_standardized_gap_pp"]
            or ref["matched_strata"] != orig["matched_strata"]):
        raise AssertionError("Previous daily source research changed")
    # The influence ranking is a deterministic consequence of the already
    # independently verified 31 leave-one-calendar-day-out comparisons.
    old = prior_daily["leave_one_day_out_25"]["observations"]
    day_lookup = {r["day"]: r for r in prior_daily["daily_unadjusted"]}
    reference = orig["pooled_standardized_gap_pp"]
    expected_rank = sorted(
        ({"day": r["excluded_day"],
          "leave_one_out_gap_pp": r["standardized_gap_pp"],
          "shift_from_full_pp": round(r["standardized_gap_pp"] - reference, 3),
          "atl_valid_arrivals_that_day": day_lookup[r["excluded_day"]]["atl_valid"],
          "other_valid_arrivals_that_day": day_lookup[r["excluded_day"]]["other_valid"],
          "daily_unadjusted_gap_pp": day_lookup[r["excluded_day"]]["unadjusted_gap_pp"],
          "matched_strata_after_omission": r["matched_strata"]}
         for r in old),
        key=lambda x: (-abs(x["shift_from_full_pp"]), x["day"]),
    )[:3]
    if report_month["influential_days"] != expected_rank:
        raise AssertionError("Top influenced dates not reproducible")

    for method in METHODS:
        content = report_month["methods"][method]
        rows = content["replicates"]
        if len(rows) != count or [r["replicate"] for r in rows] != list(range(count)):
            raise AssertionError("Incomplete or unordered resampling results")
        checked = []
        for index, observed in enumerate(rows):
            selected = make_draw(seed, month, method, index)
            if selected != observed["draw"]:
                raise AssertionError(f"{month}/{method}/{index}: seed/draw mismatch")
            if hashlib.sha256(
                json.dumps(selected, separators=(",", ":")).encode()
            ).hexdigest() != observed["draw_sha256"]:
                raise AssertionError("Resample fingerprint mismatch")
            actual = from_sql(db, selected)
            for field in FIELDS:
                if observed[field] != actual[field]:
                    raise AssertionError(
                        f"Independent SQL mismatch {month}/{method}/{index}/{field}: "
                        f"{observed[field]} vs {actual[field]}")
            checked.append(actual)
        actual_summary = independent_summary(
            checked, report_month["reference"]["standardized_gap_pp"])
        for field in SUMMARY_FIELDS:
            if content["summary"][field] != actual_summary[field]:
                raise AssertionError(f"{month}/{method}: summary mismatch {field}")
    return {
        "month": month, "reference_status": "VERIFIED",
        "replicates_per_method": count,
        "full_sql_rechecks": count * len(METHODS),
        "influential_dates_status": "VERIFIED",
    }


def run(archives, report_path: Path, old_daily_path: Path, output: Path):
    report = json.loads(report_path.read_text())
    previous = json.loads(old_daily_path.read_text())
    if (report.get("design") != DESIGN
            or report.get("replicates_per_method_per_month", 0) not in range(1, 1001)
            or report.get("seed") != 20261116
            or {m["month"] for m in report.get("months", [])} != {1, 7}
            or len(report["months"]) != 2
            or len(previous.get("months", [])) != 2):
        raise ValueError("Unsupported resampling design and source provenance")
    outcomes = []
    for month in (1, 7):
        db, digest = create_sql(archives[month], month)
        try:
            this = next(m for m in report["months"] if m["month"] == month)
            old = next(m for m in previous["months"] if m["month"] == month)
            if (this.get("year") != 2025 or this["source_sha256"] != digest
                    or old["source_sha256"] != digest):
                raise ValueError("Original and resampling source hashes differ")
            outcomes.append(verify_month(
                db, month, this, old, report["seed"],
                report["replicates_per_method_per_month"]))
        finally:
            db.close()
    write_json_new(output, {
        "status": "INDEPENDENT_SQL_PARITY_PASS",
        "design": DESIGN, "seed": report["seed"], "months": outcomes,
        "total_reaggregated_bootstrap_replicates": sum(
            m["full_sql_rechecks"] for m in outcomes),
        "scope": "All resampled draws, paired raw and matched metrics, all quantiles and influential-date ranking",
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--january", type=Path, required=True)
    parser.add_argument("--july", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--daily-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    run({1: args.january, 7: args.july}, args.report, args.daily_report, args.output)
    print("All Delta day-resampling outcomes independently verified with SQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
