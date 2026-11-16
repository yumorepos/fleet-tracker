"""Fixed-scope BTS Delta departure-bank and shared-destination descriptive audit.

January/July 2025 Reporting_Airline=DL only. Does not identify causal
airport effects, schedule-bank effects, or weather/propagation mechanisms.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import zipfile

from fleet_tracker.bts_delta_pilot import flight_date
from fleet_tracker.bts_atomic_output import write_json_new
from fleet_tracker.bts_driver_profile import EXPECTED_SHA

NEEDED = (
    "FlightDate", "Reporting_Airline", "Origin", "Dest",
    "CRSDepTime", "Cancelled", "Diverted", "ArrDel15",
)
BANKS = ("00-05", "06-11", "12-17", "18-23")
SEGMENTS = ("ATL_origin", "Other_origin")
MIN_STRATUM = 25


def binary(raw: str) -> int:
    try:
        value = Decimal(str(raw or "").strip())
    except InvalidOperation as exc:
        raise ValueError("Missing/invalid binary field") from exc
    if value not in (0, 1):
        raise ValueError("Binary field must be 0 or 1")
    return int(value)


def departure_bank(raw: str) -> str:
    """BTS scheduled clock is origin-local HHMM; 2400 is midnight."""
    try:
        d = Decimal(str(raw or "").strip())
    except InvalidOperation as exc:
        raise ValueError("Missing scheduled local departure clock") from exc
    if not d.is_finite() or d != d.to_integral_value():
        raise ValueError("Scheduled departure clock must be integral HHMM")
    t = int(d)
    if t == 2400:
        return BANKS[0]
    hour, minute = divmod(t, 100)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("Scheduled local departure clock out of range")
    return BANKS[hour // 6]


def summarize(rows: dict, month: int, sha: str, threshold: int = MIN_STRATUM) -> dict:
    """Compute sample-composition standardization without causal interpretation."""
    bank_rows, strata = rows["banks"], rows["strata"]
    allbanks = []
    for group in SEGMENTS:
        for bank in BANKS:
            counts = bank_rows[(group, bank)]
            allbanks.append({
                "origin_group": group, "scheduled_local_bank": bank,
                **{key: int(counts[key]) for key in ("scheduled", "canceled", "diverted", "valid_arrivals", "on_time")},
            })

    selected = []
    for bank, dest in sorted({(bank, dest) for _, bank, dest in strata}):
        a = strata[("ATL_origin", bank, dest)]
        b = strata[("Other_origin", bank, dest)]
        if a["valid_arrivals"] >= threshold and b["valid_arrivals"] >= threshold:
            selected.append((a["valid_arrivals"], a["on_time"],
                             b["valid_arrivals"], b["on_time"]))
    atl_n = sum(row[0] for row in selected)
    other_n = sum(row[2] for row in selected)
    atl_on = sum(row[1] for row in selected)
    other_on = sum(row[3] for row in selected)
    weight = sum(row[0] + row[2] for row in selected)
    atl_standard = (sum((a_n + b_n) * a_on / a_n
                        for a_n, a_on, b_n, b_on in selected) / weight
                    if weight else None)
    other_standard = (sum((a_n + b_n) * b_on / b_n
                          for a_n, a_on, b_n, b_on in selected) / weight
                      if weight else None)
    atl_total = sum(bank_rows[("ATL_origin", bank)]["valid_arrivals"] for bank in BANKS)
    other_total = sum(bank_rows[("Other_origin", bank)]["valid_arrivals"] for bank in BANKS)

    return {
        "year": 2025, "month": month, "source_sha256": sha,
        "source_scope": "BTS Reporting_Airline=DL domestic reportable flights",
        "local_bank_definition": "CRSDepTime at origin in 4 fixed 6-hour local-clock bins; 2400 assigned 00-05",
        "bank_rows": allbanks,
        "shared_destination_bank": {
            "minimum_valid_arrivals_per_origin_per_stratum": threshold,
            "matched_strata": len(selected),
            "atl_valid_arrivals_in_matched": atl_n,
            "other_valid_arrivals_in_matched": other_n,
            "atl_coverage_of_all_valid": round(atl_n / atl_total, 6) if atl_total else None,
            "other_coverage_of_all_valid": round(other_n / other_total, 6) if other_total else None,
            "matched_unadjusted_atl_rate": round(atl_on / atl_n, 6) if atl_n else None,
            "matched_unadjusted_other_rate": round(other_on / other_n, 6) if other_n else None,
            "pooled_standardized_atl_rate": round(atl_standard, 6) if weight else None,
            "pooled_standardized_other_rate": round(other_standard, 6) if weight else None,
            "pooled_standardized_atl_minus_other_pp": round(
                100 * (atl_standard - other_standard), 3) if weight else None,
            "coverage_verdict": (
                "EXPLORATORY_SUBSET" if weight and atl_n / atl_total >= .5
                and other_n / other_total >= .5 else "LOW_COVERAGE_OR_NO_MATCH"
            ),
        },
    }


def analyze(archive: Path, month: int, baseline_month: dict) -> dict:
    if month not in EXPECTED_SHA:
        raise ValueError("Only 2025 Jan and July")
    if archive.stat().st_size > 150_000_000:
        raise ValueError("ZIP exceeds bounded-source limit")
    h = hashlib.sha256()
    with archive.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    sha = h.hexdigest()
    if sha != EXPECTED_SHA[month] or baseline_month.get("source_zip_sha256") != sha:
        raise ValueError("Source archive hash disagrees with verified baseline")
    if baseline_month.get("core_kpi_gate") != "GO" or baseline_month.get("year") != 2025:
        raise ValueError("Baseline quality gate/scope did not pass")

    banks: dict = defaultdict(Counter)
    strata: dict = defaultdict(Counter)
    overall = Counter()
    with zipfile.ZipFile(archive) as z:
        members = [i for i in z.infolist()
                   if i.filename.lower().endswith(".csv") and not i.is_dir()]
        if len(members) != 1 or members[0].file_size > 1_000_000_000:
            raise ValueError("Expected one bounded source CSV")
        with z.open(members[0]) as raw, io.TextIOWrapper(
                raw, encoding="utf-8-sig", newline="") as stream:
            source = csv.DictReader(stream)
            if not set(NEEDED).issubset(set(source.fieldnames or ())):
                raise ValueError("BTS source missing required departure bank fields")
            for row in source:
                if (row["Reporting_Airline"] or "").strip() != "DL":
                    continue
                d = flight_date(row["FlightDate"])
                if d.year != 2025 or d.month != month:
                    raise ValueError("DL row has unexpected flight date")
                origin = (row["Origin"] or "").strip().upper()
                dest = (row["Dest"] or "").strip().upper()
                if len(origin) != 3 or len(dest) != 3 or not origin.isalpha() or not dest.isalpha():
                    raise ValueError("Missing or invalid route code")
                bank = departure_bank(row["CRSDepTime"])
                canceled, diverted = binary(row["Cancelled"]), binary(row["Diverted"])
                if canceled and diverted:
                    raise ValueError("Contradictory canceled+diverted status")
                group = "ATL_origin" if origin == "ATL" else "Other_origin"
                for target in (overall, banks[(group, bank)], strata[(group, bank, dest)]):
                    target["scheduled"] += 1
                    target["canceled"] += canceled
                    target["diverted"] += diverted
                if canceled or diverted:
                    continue
                arrival = binary(row["ArrDel15"])
                for target in (overall, banks[(group, bank)], strata[(group, bank, dest)]):
                    target["valid_arrivals"] += 1
                    target["on_time"] += 1 - arrival

    expected = baseline_month["counts"]
    for field, baseline_field in (
        ("scheduled", "dl"), ("canceled", "canceled"),
        ("diverted", "diverted"), ("valid_arrivals", "arr15_valid"),
        ("on_time", "ontime"),
    ):
        if overall[field] != expected[baseline_field]:
            raise ValueError(f"Source reconciliation failed: {field}")
    if (overall["scheduled"] != overall["canceled"] + overall["diverted"] + overall["valid_arrivals"]
            or overall["valid_arrivals"] != expected["eligible"]):
        raise ValueError("Invalid source KPI denominators")
    out = summarize({"banks": banks, "strata": strata}, month, sha)
    out["population"] = {key: int(overall[key]) for key in (
        "scheduled", "canceled", "diverted", "valid_arrivals", "on_time")}
    return out


def run(january: Path, july: Path, baseline: Path, output: Path) -> None:
    reference = json.loads(baseline.read_text())
    if reference.get("both_months_core_gate") != "GO":
        raise ValueError("Baseline does not contain passing source quality gates")
    periods = reference["months"]
    if len(periods) != 2 or {x["month"] for x in periods} != {1, 7}:
        raise ValueError("Baseline month contract mismatch")
    months = [analyze(path, month, next(x for x in periods if x["month"] == month))
              for month, path in ((1, january), (7, july))]
    report = {
        "research_question": "How do observed ATL-origin punctuality gaps vary by origin-local scheduled departure bank and shared destination-bank mix?",
        "limitations": [
            "Descriptive association; no causal airport, flight schedule, or intervention effect",
            "Different origin routes serve the same destination; destination matching does not equal matching an identical route",
            "Matched destination-bank comparison uses only strata with >=25 eligible flights in each group; coverage must be reported",
            "January and July are separate selected 2025 months, not a seasonal test",
            "Local departure clocks reflect different time zones and scheduled banks, not shared absolute UTC windows",
        ],
        "months": months,
    }
    write_json_new(output, report)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--january", type=Path, required=True)
    p.add_argument("--july", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    run(args.january, args.july, args.baseline, args.output)
    print("Produced aggregate-only descriptive report:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
