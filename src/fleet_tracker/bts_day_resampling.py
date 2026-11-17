"""Day-level resampling stability diagnostics for the fixed BTS Delta pilot.

Whole-day paired draws (ATL and other origins together) from the same
source-verified January/July 2025 archives. This is NOT a formal confidence
interval, a causal estimate, an annual trend or a predictive model.

Resampling uses only in-memory daily aggregated destination/bank cells.
The official source ZIPs are never persisted into the research artifact.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from math import ceil
from pathlib import Path
import random

from fleet_tracker.bts_atomic_output import write_json_new
from fleet_tracker.bts_daily_robustness import load_month

METHODS = ("iid_day", "moving_block3")
SEED = 20261116
REPLICATES = 300
DAY_COUNT = 31
THRESHOLD = 25
DESIGN = "delta-2025-paired-day-resampling-v1"


def draws(month: int, method: str, index: int, *, seed: int = SEED) -> list[int]:
    """Return 31 deterministic, common-across-origin date labels.

    iid_day: sample individual dates with replacement.
    moving_block3: sample overlapping *noncircular* consecutive 3-day
    blocks, with replacement; concatenate and truncate to 31 positions.
    """
    if month not in (1, 7) or method not in METHODS or not 0 <= index < 10000:
        raise ValueError("Unsupported month, sampling method, or replicate")
    if type(seed) is not int or seed < 0:
        raise ValueError("Seed must be a nonnegative integer")
    key = f"{DESIGN}|{seed}|{month}|{method}|{index}"
    generator = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    if method == "iid_day":
        return [generator.randrange(1, DAY_COUNT + 1) for _ in range(DAY_COUNT)]
    days = []
    while len(days) < DAY_COUNT:
        start = generator.randrange(1, DAY_COUNT - 3 + 2)  # inclusive 1..29
        days.extend(range(start, start + 3))
    return days[:DAY_COUNT]


def fingerprint(sample: list[int]) -> str:
    return hashlib.sha256(json.dumps(sample, separators=(",", ":")).encode()).hexdigest()


def weighted_estimate(cells: dict, sample: list[int], *, threshold: int = THRESHOLD) -> dict:
    """Rebuild every matched cell after multiplicity-weighted day resampling.

    The original leave-one-day-out function uses set membership; this new
    function must instead preserve replacement multiplicity.
    """
    if not sample or len(sample) != DAY_COUNT or any(
            type(day) is not int or not 1 <= day <= DAY_COUNT for day in sample):
        raise ValueError("Resample must contain 31 valid operating-date labels")
    if threshold != THRESHOLD:
        raise ValueError("Only the predeclared 25-per-origin match is supported")
    weights = Counter(sample)
    totals = defaultdict(lambda: [0, 0])
    grouped = defaultdict(lambda: [0, 0])
    for (day, group, bank, dest), count in cells.items():
        w = weights.get(day, 0)
        if w == 0:
            continue
        n = count["valid_arrivals"] * w
        on = count["on_time"] * w
        total = totals[group]
        total[0] += n
        total[1] += on
        value = grouped[(group, bank, dest)]
        value[0] += n
        value[1] += on
    a_n, a_on = totals["ATL_origin"]
    b_n, b_on = totals["Other_origin"]
    raw = round(100 * (a_on / a_n - b_on / b_n), 3) if a_n and b_n else None

    pairs = []
    for bank, dest in sorted({(bank, dest) for _, bank, dest in grouped}):
        aa, ao = grouped[("ATL_origin", bank, dest)]
        bb, bo = grouped[("Other_origin", bank, dest)]
        if aa >= threshold and bb >= threshold:
            pairs.append((aa, ao, bb, bo))
    ma, mb = sum(x[0] for x in pairs), sum(x[2] for x in pairs)
    pooled = ma + mb
    gap = (round(100 * sum((aa + bb) * (ao / aa - bo / bb)
                            for aa, ao, bb, bo in pairs) / pooled, 3)
           if pooled else None)
    cover_a = round(ma / a_n, 6) if a_n else None
    cover_b = round(mb / b_n, 6) if b_n else None
    pass_coverage = (pooled > 0 and cover_a is not None and
                     cover_b is not None and cover_a >= 0.5 and cover_b >= 0.5)
    return {
        "unadjusted_gap_pp": raw, "standardized_gap_pp": gap,
        "matched_strata": len(pairs), "atl_total_valid": a_n,
        "other_total_valid": b_n, "atl_matched_valid": ma,
        "other_matched_valid": mb,
        "atl_coverage": cover_a, "other_coverage": cover_b,
        "coverage_gate_passed": bool(pass_coverage),
    }


def nearest_rank(values, percent: int):
    """Nearest-rank empirical percentile, explicitly not a confidence limit."""
    if percent not in (5, 50, 95):
        raise ValueError("Only fixed percentile grid")
    data = sorted(v for v in values if v is not None)
    return data[max(0, ceil(percent * len(data) / 100) - 1)] if data else None


def summarize_replicates(rows: list[dict], reference: float | None) -> dict:
    valid = [r["standardized_gap_pp"] for r in rows
             if r["standardized_gap_pp"] is not None]
    raw = [r["unadjusted_gap_pp"] for r in rows
           if r["unadjusted_gap_pp"] is not None]
    cover_a = [r["atl_coverage"] for r in rows if r["atl_coverage"] is not None]
    cover_b = [r["other_coverage"] for r in rows if r["other_coverage"] is not None]
    return {
        "replicates": len(rows),
        "defined_standardized_replicates": len(valid),
        "undefined_standardized_replicates": len(rows) - len(valid),
        "reference_standardized_gap_pp": reference,
        "standardized_gap_p05_pp": nearest_rank(valid, 5),
        "standardized_gap_median_pp": nearest_rank(valid, 50),
        "standardized_gap_p95_pp": nearest_rank(valid, 95),
        "unadjusted_gap_p05_pp": nearest_rank(raw, 5),
        "unadjusted_gap_median_pp": nearest_rank(raw, 50),
        "unadjusted_gap_p95_pp": nearest_rank(raw, 95),
        "atl_coverage_p05": nearest_rank(cover_a, 5),
        "other_coverage_p05": nearest_rank(cover_b, 5),
        "matched_strata_median": nearest_rank(
            [r["matched_strata"] for r in rows], 50),
        "coverage_gate_failure_count": sum(not r["coverage_gate_passed"] for r in rows),
        "positive_standardized_count": sum(v > 0 for v in valid),
        "negative_standardized_count": sum(v < 0 for v in valid),
        "exact_zero_standardized_count": sum(v == 0 for v in valid),
        "opposite_sign_count": (
            sum(v * reference < 0 for v in valid)
            if reference is not None else None),
    }


def influential_dates(old: dict, top: int = 3) -> list[dict]:
    """Report *descriptive* leave-one-date-out influence; no cause attribution."""
    reference = old["threshold_sensitivity"]["25"]["pooled_standardized_gap_pp"]
    records = old["leave_one_day_out_25"]["observations"]
    daily = {x["day"]: x for x in old["daily_unadjusted"]}
    if (len(records) != DAY_COUNT or set(daily) != set(range(1, DAY_COUNT + 1))
            or {x["excluded_day"] for x in records} != set(daily)):
        raise ValueError("Original daily leave-one-out evidence incomplete")
    evidence = []
    for row in records:
        day = row["excluded_day"]
        observed = row["standardized_gap_pp"]
        if observed is None or reference is None:
            raise ValueError("Missing influential-date reference result")
        original = daily[day]
        evidence.append({
            "day": day,
            "leave_one_out_gap_pp": observed,
            "shift_from_full_pp": round(observed - reference, 3),
            "atl_valid_arrivals_that_day": original["atl_valid"],
            "other_valid_arrivals_that_day": original["other_valid"],
            "daily_unadjusted_gap_pp": original["unadjusted_gap_pp"],
            "matched_strata_after_omission": row["matched_strata"],
        })
    return sorted(evidence, key=lambda x: (-abs(x["shift_from_full_pp"]), x["day"]))[:top]


def month_report(month: int, sha: str, cells: dict, old: dict,
                 *, replicates: int = REPLICATES, seed: int = SEED) -> dict:
    if not 1 <= replicates <= 1000:
        raise ValueError("Replicate count outside bounded range")
    reference = weighted_estimate(cells, list(range(1, DAY_COUNT + 1)))
    prior = old["threshold_sensitivity"]["25"]
    for field, key in (
        ("standardized_gap_pp", "pooled_standardized_gap_pp"),
        ("matched_strata", "matched_strata"),
        ("atl_matched_valid", "atl_matched_valid"),
        ("other_matched_valid", "other_matched_valid"),
        ("atl_coverage", "atl_coverage"),
        ("other_coverage", "other_coverage"),
        ("unadjusted_gap_pp", "all_flights_unadjusted_gap_pp"),
    ):
        if reference[field] != prior[key]:
            raise ValueError(f"Daily benchmark reconciliation failed: {field}")
    result = {"year": 2025, "month": month, "source_sha256": sha,
              "reference": reference, "influential_days": influential_dates(old),
              "methods": {}}
    for method in METHODS:
        rows = []
        for replicate in range(replicates):
            sample = draws(month, method, replicate, seed=seed)
            estimate = weighted_estimate(cells, sample)
            rows.append({
                "replicate": replicate, "draw": sample,
                "draw_sha256": fingerprint(sample),
                **estimate,
            })
        result["methods"][method] = {
            "summary": summarize_replicates(rows, reference["standardized_gap_pp"]),
            "replicates": rows,
        }
    return result


def run(january: Path, july: Path, baseline: Path, bank_report: Path,
        daily_report: Path, output: Path, *, replicates: int = REPLICATES,
        seed: int = SEED) -> None:
    pilot = json.loads(baseline.read_text())
    prior_banks = json.loads(bank_report.read_text())
    prior_daily = json.loads(daily_report.read_text())
    sources = (pilot, prior_banks, prior_daily)
    if any(len(src.get("months", [])) != 2
           or {x["month"] for x in src["months"]} != {1, 7} for src in sources):
        raise ValueError("Source and research reports must contain Jan and July")
    if pilot.get("both_months_core_gate") != "GO":
        raise ValueError("Official monthly quality gate not passed")
    result = []
    for month, archive in ((1, january), (7, july)):
        base, bank, old = (next(x for x in src["months"] if x["month"] == month)
                           for src in sources)
        sha, cells, _ = load_month(archive, month, base, bank)
        if old.get("year") != 2025 or old.get("source_sha256") != sha:
            raise ValueError("Original daily report provenance mismatch")
        result.append(month_report(month, sha, cells, old, replicates=replicates, seed=seed))
    write_json_new(output, {
        "design": DESIGN, "seed": seed, "replicates_per_method_per_month": replicates,
        "source": "Official 2025 BTS Reporting_Airline=DL Jan/Jul ZIP SHA-256 gated",
        "unit": "paired calendar FlightDate label; 31 draws with replacement",
        "methods": {
            "iid_day": "independent calendar-date labels; preserve within-day co-fluctuation",
            "moving_block3": "noncircular length-3 contiguous date blocks; sampling with replacement and truncation",
        },
        "interpretation": (
            "Empirical 5th/95th percentile sensitivity bands, NOT formal 90% confidence "
            "intervals: only two purposively selected months, 31 days each, serial and "
            "shared-flight dependence, nonstationarity, fixed nonoptimized block length."
        ),
        "warnings": [
            "Matching and pooled standardization recomputed in every replicate",
            "Resampling date labels with multiplicity does not synthesize additional independent flights",
            "Noncircular moving blocks underweight end-of-month dates; report sensitivity to method",
            "No causal effect, prediction accuracy, real operating savings or full network coverage",
        ],
        "months": result,
    })


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--january", type=Path, required=True)
    p.add_argument("--july", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--bank-report", type=Path, required=True)
    p.add_argument("--daily-report", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--replicates", type=int, default=REPLICATES)
    args = p.parse_args(argv)
    run(args.january, args.july, args.baseline, args.bank_report,
        args.daily_report, args.output, replicates=args.replicates)
    print("Wrote aggregate paired-day resampling diagnostics:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
