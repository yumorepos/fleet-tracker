"""Delta BTS daily sensitivity and destination-bank sample-selection audit.

Read-only January/July 2025 DL reporting-carrier ZIPs, verified against the
existing source/KPI and departure-bank reports. Persist aggregates only.
No confidence interval, causal adjustment, or seasonality inference.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import zipfile

from fleet_tracker.bts_atomic_output import write_json_new
from fleet_tracker.bts_bank_mix import BANKS, SEGMENTS, binary, departure_bank
from fleet_tracker.bts_delta_pilot import flight_date
from fleet_tracker.bts_driver_profile import EXPECTED_SHA

REQUIRED = ("FlightDate", "Reporting_Airline", "Origin", "Dest",
            "CRSDepTime", "Cancelled", "Diverted", "ArrDel15")
THRESHOLDS = (10, 25, 50)
FIELDS = ("scheduled", "canceled", "diverted", "valid_arrivals", "on_time")
BASELINE_MAP = {"scheduled": "dl", "canceled": "canceled",
                "diverted": "diverted", "valid_arrivals": "arr15_valid",
                "on_time": "ontime"}


def _rate(numer, denom):
    return round(numer / denom, 6) if denom else None


def _pp(a, b):
    return round(100 * (a - b), 3) if a is not None and b is not None else None


def calculate(stats, *, included_days, threshold):
    """Rebuild matching after each restriction; never reuse full-month weights."""
    if threshold not in THRESHOLDS:
        raise ValueError("Threshold is not part of the preregistered grid")
    included_days = set(included_days)
    totals = defaultdict(Counter)
    cells = defaultdict(Counter)
    for (day, group, bank, dest), counts in stats.items():
        if day not in included_days:
            continue
        totals[group].update(counts)
        cells[(group, bank, dest)].update(counts)
    atl, other = (totals[g] for g in SEGMENTS)
    a_all, b_all = atl["valid_arrivals"], other["valid_arrivals"]
    all_gap = (_pp(atl["on_time"] / a_all, other["on_time"] / b_all)
               if a_all and b_all else None)
    matched = []
    for bank, dest in sorted({(bank, dest) for _, bank, dest in cells}):
        a = cells[(SEGMENTS[0], bank, dest)]
        b = cells[(SEGMENTS[1], bank, dest)]
        if a["valid_arrivals"] >= threshold and b["valid_arrivals"] >= threshold:
            matched.append((a["valid_arrivals"], a["on_time"],
                            b["valid_arrivals"], b["on_time"]))
    na, no = sum(x[0] for x in matched), sum(x[2] for x in matched)
    oa, oo = sum(x[1] for x in matched), sum(x[3] for x in matched)
    pool = na + no
    raw_matched_gap = _pp(oa / na, oo / no) if na and no else None
    standardized_gap = (
        _pp(sum((a+b) * oa_ / a for a, oa_, b, ob_ in matched) / pool,
            sum((a+b) * ob_ / b for a, oa_, b, ob_ in matched) / pool)
        if pool else None
    )
    # Use unrounded internal values for each component to ensure the
    # decomposition is defined by one reference, not rounded rates.
    selection = (round(raw_matched_gap - all_gap, 3)
                 if raw_matched_gap is not None and all_gap is not None else None)
    reweight = (round(standardized_gap - raw_matched_gap, 3)
                if standardized_gap is not None and raw_matched_gap is not None else None)
    ca, cb = _rate(na, a_all), _rate(no, b_all)
    verdict = ("EXPLORATORY_SUBSET" if pool and ca >= 0.5 and cb >= 0.5
               else "LOW_COVERAGE_OR_NO_MATCH")
    return {
        "minimum_valid_arrivals_each_group": threshold,
        "selected_days": len(included_days), "matched_strata": len(matched),
        "atl_total_valid": a_all, "other_total_valid": b_all,
        "atl_matched_valid": na, "other_matched_valid": no,
        "atl_coverage": ca, "other_coverage": cb,
        "all_flights_unadjusted_gap_pp": all_gap,
        "matched_subset_unadjusted_gap_pp": raw_matched_gap,
        "pooled_standardized_gap_pp": standardized_gap,
        "selection_shift_pp": selection,
        "reweight_shift_pp": reweight,
        "coverage_verdict": verdict,
    }


def load_month(archive: Path, month: int, baseline: dict, previous: dict):
    """Hash-gated single pass from official BTS ZIP to daily aggregate cells."""
    if month not in EXPECTED_SHA or archive.stat().st_size > 150_000_000:
        raise ValueError("Unexpected source archive/month")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    sha = digest.hexdigest()
    if (sha != EXPECTED_SHA[month] or baseline.get("source_zip_sha256") != sha
            or previous.get("source_sha256") != sha
            or baseline.get("core_kpi_gate") != "GO"
            or baseline.get("year") != 2025 or baseline.get("month") != month
            or previous.get("year") != 2025 or previous.get("month") != month):
        raise ValueError("Source hash/scope or original quality gate mismatch")

    stats = defaultdict(Counter)
    daily = defaultdict(Counter)
    month_total = Counter()
    with zipfile.ZipFile(archive) as z:
        members = [x for x in z.infolist()
                   if x.filename.lower().endswith(".csv") and not x.is_dir()]
        if len(members) != 1 or members[0].file_size > 1_000_000_000:
            raise ValueError("Expected one bounded CSV")
        with z.open(members[0]) as raw, io.TextIOWrapper(
                raw, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not set(REQUIRED).issubset(set(reader.fieldnames or ())):
                raise ValueError("Missing required BTS daily fields")
            for row in reader:
                if (row["Reporting_Airline"] or "").strip() != "DL":
                    continue
                day = flight_date(row["FlightDate"])
                if day.year != 2025 or day.month != month:
                    raise ValueError("Unexpected flight date")
                origin = (row["Origin"] or "").strip().upper()
                dest = (row["Dest"] or "").strip().upper()
                if (len(origin) != 3 or not origin.isalpha()
                        or len(dest) != 3 or not dest.isalpha()):
                    raise ValueError("Invalid airport code")
                bank = departure_bank(row["CRSDepTime"])
                cancel = binary(row["Cancelled"])
                divert = binary(row["Diverted"])
                if cancel and divert:
                    raise ValueError("Contradictory status")
                group = SEGMENTS[0] if origin == "ATL" else SEGMENTS[1]
                for counts in (stats[(day.day, group, bank, dest)],
                               daily[(day.day, group, bank)], month_total):
                    counts["scheduled"] += 1
                    counts["canceled"] += cancel
                    counts["diverted"] += divert
                if cancel or divert:
                    continue
                arrive = binary(row["ArrDel15"])
                for counts in (stats[(day.day, group, bank, dest)],
                               daily[(day.day, group, bank)], month_total):
                    counts["valid_arrivals"] += 1
                    counts["on_time"] += 1 - arrive

    for field, original in BASELINE_MAP.items():
        if month_total[field] != baseline["counts"][original]:
            raise ValueError("Monthly source reconciliation failed: " + field)
    if (month_total["scheduled"] != month_total["canceled"] +
            month_total["diverted"] + month_total["valid_arrivals"]):
        raise ValueError("Monthly status partition failed")
    prior_bank = {(x["origin_group"], x["scheduled_local_bank"]): x
                  for x in previous["bank_rows"]}
    if len(prior_bank) != 8:
        raise ValueError("Prior bank research contract missing")
    for group in SEGMENTS:
        for bank in BANKS:
            observed = daily_group = Counter()
            for day in range(1, 32):
                observed.update(daily[(day, group, bank)])
            expected = prior_bank[(group, bank)]
            if any(observed[field] != expected[field] for field in FIELDS):
                raise ValueError(f"Prior bank count mismatch: {group}/{bank}")
    return sha, stats, daily


def summarize_month(month, sha, stats, daily, previous):
    days = set(range(1, 32))
    threshold_results = {str(t): calculate(stats, included_days=days, threshold=t)
                         for t in THRESHOLDS}
    prior = previous["shared_destination_bank"]
    current = threshold_results["25"]
    mapping = {
        "matched_strata": "matched_strata",
        "atl_valid_arrivals_in_matched": "atl_matched_valid",
        "other_valid_arrivals_in_matched": "other_matched_valid",
        "atl_coverage_of_all_valid": "atl_coverage",
        "other_coverage_of_all_valid": "other_coverage",
        "pooled_standardized_atl_minus_other_pp": "pooled_standardized_gap_pp",
    }
    for old, new in mapping.items():
        if prior[old] != current[new]:
            raise ValueError("Previously verified 25-flight match mismatch: " + old)
    for t1, t2 in ((10, 25), (25, 50)):
        lo, hi = threshold_results[str(t1)], threshold_results[str(t2)]
        if (lo["matched_strata"] < hi["matched_strata"]
                or lo["atl_matched_valid"] < hi["atl_matched_valid"]
                or lo["other_matched_valid"] < hi["other_matched_valid"]):
            raise ValueError("Threshold coverage should be monotone")
    groups = {
        "weekday": {d for d in days if date(2025, month, d).weekday() < 5},
        "weekend": {d for d in days if date(2025, month, d).weekday() >= 5},
    }
    day_type = {name: calculate(stats, included_days=ds, threshold=25)
                for name, ds in groups.items()}
    leave_one_out = []
    daily_gaps = []
    for removed in sorted(days):
        metrics = calculate(stats, included_days=days - {removed}, threshold=25)
        leave_one_out.append({
            "excluded_day": removed,
            "standardized_gap_pp": metrics["pooled_standardized_gap_pp"],
            "matched_strata": metrics["matched_strata"],
            "atl_coverage": metrics["atl_coverage"],
            "other_coverage": metrics["other_coverage"],
        })
        aa = sum(daily[(removed, SEGMENTS[0], bank)]["valid_arrivals"] for bank in BANKS)
        bb = sum(daily[(removed, SEGMENTS[1], bank)]["valid_arrivals"] for bank in BANKS)
        ao = sum(daily[(removed, SEGMENTS[0], bank)]["on_time"] for bank in BANKS)
        bo = sum(daily[(removed, SEGMENTS[1], bank)]["on_time"] for bank in BANKS)
        daily_gaps.append({"day": removed, "atl_valid": aa, "other_valid": bb,
                           "atl_on_time": ao, "other_on_time": bo,
                           "unadjusted_gap_pp": _pp(ao / aa, bo / bb) if aa and bb else None})
    vals = [x["standardized_gap_pp"] for x in leave_one_out
            if x["standardized_gap_pp"] is not None]
    full = current["pooled_standardized_gap_pp"]
    return {
        "year": 2025, "month": month, "source_sha256": sha,
        "threshold_sensitivity": threshold_results,
        "weekday_weekend": day_type,
        "daily_unadjusted": daily_gaps,
        "leave_one_day_out_25": {
            "recompute_matches_after_exclusion": True,
            "observations": leave_one_out,
            "valid_exclusions": len(vals),
            "min_gap_pp": min(vals) if vals else None,
            "max_gap_pp": max(vals) if vals else None,
            "largest_absolute_shift_from_full_pp": (
                round(max(abs(x - full) for x in vals), 3)
                if vals and full is not None else None),
            "sign_flips_vs_full": (sum(x * full < 0 for x in vals)
                                  if full is not None else None),
        },
    }


def run(january: Path, july: Path, baseline_path: Path, bank_path: Path,
        output: Path):
    pilot = json.loads(baseline_path.read_text())
    prior = json.loads(bank_path.read_text())
    if (pilot.get("both_months_core_gate") != "GO"
            or len(pilot.get("months", [])) != 2
            or len(prior.get("months", [])) != 2
            or {x["month"] for x in pilot["months"]} != {1, 7}
            or {x["month"] for x in prior["months"]} != {1, 7}):
        raise ValueError("Quality gate and prior research require January and July")
    months = []
    for month, path in ((1, january), (7, july)):
        base = next(x for x in pilot["months"] if x["month"] == month)
        past = next(x for x in prior["months"] if x["month"] == month)
        sha, cells, daily = load_month(path, month, base, past)
        months.append(summarize_month(month, sha, cells, daily, past))
    report = {
        "research_question": "How sensitive are Delta ATL-origin matched destination/local-bank gaps to the threshold, sample restriction and individual operating days?",
        "population": "Jan/Jul 2025 BTS Reporting_Airline=DL domestic reporting-carrier flights",
        "denominator": "Noncancelled, nondiverted arrivals with valid ArrDel15 flags",
        "limits": [
            "Descriptive robustness diagnostic, not a causal adjustment or confidence interval",
            "Destination/local-bank matching does not control for full origin-destination route",
            "Leave-one-calendar-day-out recomputes matching; it is not a day-cluster bootstrap",
            "Weekday and weekend reselect different subsets and cannot isolate day-type effects",
            "January and July 2025 are separate historical snapshots, not seasonal evidence",
        ],
        "months": months,
    }
    write_json_new(output, report)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--january", type=Path, required=True)
    p.add_argument("--july", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--bank-report", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    run(args.january, args.july, args.baseline, args.bank_report, args.output)
    print("Verified daily BTS sensitivity report:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
