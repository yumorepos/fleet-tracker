"""Offline regression and source-backed synthetic ZIP tests for paired-day resampling."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
from io import StringIO
import json
import zipfile

import pytest

from fleet_tracker import bts_bank_mix as bank
from fleet_tracker import bts_daily_robustness as history
from fleet_tracker import bts_day_resampling as primary
from fleet_tracker import bts_day_resampling_sql_verify as verifier


def synthetic_zip(tmp_path, month, monkeypatch):
    """31-day ZIP: cross-origin matched cells, two sparse cells and excluded rows."""
    rows = []
    for d in range(1, 32):
        dated = f"2025-{month:02d}-{d:02d}"
        for origin, n, late in (("ATL", 3, d % 3), ("BOS", 4, d % 2)):
            for i in range(n):
                rows.append({
                    "FlightDate": dated, "Reporting_Airline": "DL",
                    "Origin": origin, "Dest": "JFK", "CRSDepTime": "800",
                    "Cancelled": "0.00", "Diverted": "0.00",
                    "ArrDel15": "1.00" if i < late else "0.00",
                })
        if d <= 25:
            for origin in ("ATL", "BOS"):
                rows.append({
                    "FlightDate": dated, "Reporting_Airline": "DL",
                    "Origin": origin, "Dest": "SEA", "CRSDepTime": "1400",
                    "Cancelled": "0", "Diverted": "0",
                    "ArrDel15": "0" if origin == "ATL" else "1",
                })
    rows.extend([
        {"FlightDate": f"2025-{month:02d}-05", "Reporting_Airline": "DL",
         "Origin": "ATL", "Dest": "ORD", "CRSDepTime": "2400",
         "Cancelled": "1", "Diverted": "0", "ArrDel15": ""},
        {"FlightDate": f"2025-{month:02d}-15", "Reporting_Airline": "DL",
         "Origin": "BOS", "Dest": "LAX", "CRSDepTime": "1800",
         "Cancelled": "0", "Diverted": "1", "ArrDel15": ""},
        {"FlightDate": f"2025-{month:02d}-01", "Reporting_Airline": "UA",
         "Origin": "ATL", "Dest": "JFK", "CRSDepTime": "0800",
         "Cancelled": "0", "Diverted": "0", "ArrDel15": "0"},
    ])
    csv_stream = StringIO()
    writer = csv.DictWriter(csv_stream, fieldnames=list(bank.NEEDED))
    writer.writeheader()
    writer.writerows(rows)
    zipped = tmp_path / f"mini_{month}.zip"
    with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("source.csv", csv_stream.getvalue())
    sha = hashlib.sha256(zipped.read_bytes()).hexdigest()
    monkeypatch.setitem(history.EXPECTED_SHA, month, sha)
    # Single source checksum mapping is shared with both source readers.
    n_valid = sum(r["Reporting_Airline"] == "DL" and r["ArrDel15"] != ""
                  for r in rows)
    on_time = sum(r["Reporting_Airline"] == "DL" and
                  r["ArrDel15"] in ("0", "0.00") for r in rows)
    base = {
        "year": 2025, "month": month,
        "source_zip_sha256": sha, "core_kpi_gate": "GO",
        "counts": {
            "dl": len(rows) - 1, "canceled": 1, "diverted": 1,
            "arr15_valid": n_valid, "eligible": n_valid, "ontime": on_time,
        },
    }
    bank_month = bank.analyze(zipped, month, base)
    digest, cells, by_day = history.load_month(zipped, month, base, bank_month)
    assert digest == sha
    old = history.summarize_month(month, digest, cells, by_day, bank_month)
    return zipped, base, bank_month, old, cells


def input_files(tmp_path, monkeypatch):
    all_zip = {}
    baselines, banks, daily = [], [], []
    for m in (1, 7):
        z, b, k, r, cells = synthetic_zip(tmp_path, m, monkeypatch)
        all_zip[m] = z
        baselines.append(b)
        banks.append(k)
        daily.append(r)
    pilot = tmp_path / "baseline.json"
    pilot.write_text(json.dumps({"both_months_core_gate": "GO", "months": baselines}))
    previous_bank = tmp_path / "bank.json"
    previous_bank.write_text(json.dumps({"months": banks}))
    previous_daily = tmp_path / "daily.json"
    previous_daily.write_text(json.dumps({"months": daily}))
    return all_zip, pilot, previous_bank, previous_daily


@pytest.mark.parametrize("month,method", [(1, "iid_day"), (1, "moving_block3"),
                                           (7, "iid_day"), (7, "moving_block3")])
def test_draws_are_deterministic_valid_and_cover_both_origins_together(month, method):
    first = primary.draws(month, method, 13)
    assert first == primary.draws(month, method, 13)
    assert first == verifier.make_draw(primary.SEED, month, method, 13)
    assert len(first) == 31 and all(1 <= d <= 31 for d in first)
    assert len(primary.fingerprint(first)) == 64
    if method == "moving_block3":
        for pos in range(0, 30, 3):
            assert first[pos+1] == first[pos] + 1
            assert first[pos+2] == first[pos] + 2


def test_weighted_duplicate_days_change_denominator_not_unique_day_count():
    cells = defaultdict(Counter)
    for d in range(1, 32):
        cells[(d, "ATL_origin", "06-11", "JFK")].update(valid_arrivals=1,
                                                      on_time=1 if d <= 15 else 0)
        cells[(d, "Other_origin", "06-11", "JFK")].update(valid_arrivals=1,
                                                        on_time=0 if d <= 15 else 1)
    original = primary.weighted_estimate(cells, list(range(1, 32)))
    all_one = primary.weighted_estimate(cells, [1]*31)
    assert original["matched_strata"] == 1
    assert original["atl_total_valid"] == 31
    assert all_one["atl_total_valid"] == 31
    assert original["standardized_gap_pp"] != all_one["standardized_gap_pp"]
    assert all_one["standardized_gap_pp"] == 100.0


def test_reselects_matched_cells_in_each_draw():
    cells = defaultdict(Counter)
    for d in range(1, 32):
        for group in ("ATL_origin", "Other_origin"):
            cells[(d, group, "06-11", "JFK")].update(valid_arrivals=2, on_time=1)
            if d <= 25:
                cells[(d, group, "12-17", "SEA")].update(
                    valid_arrivals=1, on_time=1 if group == "ATL_origin" else 0)
    full = primary.weighted_estimate(cells, list(range(1, 32)))
    late_only = primary.weighted_estimate(cells, [31]*31)
    assert full["matched_strata"] == 2
    assert late_only["matched_strata"] == 1


def test_nearest_rank_is_explicit_and_no_matches_remain_undefined():
    assert primary.nearest_rank(list(range(1, 101)), 5) == 5
    assert primary.nearest_rank(list(range(1, 101)), 50) == 50
    assert primary.nearest_rank(list(range(1, 101)), 95) == 95
    assert primary.nearest_rank([], 5) is None
    rows = [{"standardized_gap_pp": None, "unadjusted_gap_pp": -5.0,
             "atl_coverage": 0, "other_coverage": 0, "matched_strata": 0,
             "coverage_gate_passed": False}]
    summary = primary.summarize_replicates(rows, None)
    assert summary["defined_standardized_replicates"] == 0
    assert summary["undefined_standardized_replicates"] == 1
    assert summary["standardized_gap_p05_pp"] is None
    assert summary["coverage_gate_failure_count"] == 1


def test_full_synthetic_source_pipeline_and_all_sql_replicates(tmp_path, monkeypatch):
    archives, pilot, bank_path, daily_path = input_files(tmp_path, monkeypatch)
    out, sql = tmp_path / "resample.json", tmp_path / "resample_sql.json"
    primary.run(archives[1], archives[7], pilot, bank_path,
                daily_path, out, replicates=8)
    verifier.run(archives, out, daily_path, sql)
    report, independent = json.loads(out.read_text()), json.loads(sql.read_text())
    assert independent["status"] == "INDEPENDENT_SQL_PARITY_PASS"
    assert independent["total_reaggregated_bootstrap_replicates"] == 32
    for month in report["months"]:
        for method in primary.METHODS:
            assert len(month["methods"][method]["replicates"]) == 8
            assert month["methods"][method]["summary"]["replicates"] == 8
        assert len(month["influential_days"]) == 3
    assert not list(tmp_path.glob(".bts-report-*"))


def test_mutating_resampling_count_or_draw_fails_verification(tmp_path, monkeypatch):
    archives, pilot, bank_path, daily_path = input_files(tmp_path, monkeypatch)
    output = tmp_path / "resampling.json"
    primary.run(archives[1], archives[7], pilot, bank_path,
                daily_path, output, replicates=3)
    body = json.loads(output.read_text())
    body["months"][0]["methods"]["iid_day"]["replicates"][0]["draw"][0] = 99
    changed = tmp_path / "tampered.json"
    changed.write_text(json.dumps(body))
    with pytest.raises(AssertionError, match="seed/draw mismatch"):
        verifier.run(archives, changed, daily_path, tmp_path / "rejected.json")


def test_strict_scope_no_clobber_and_input_validation(tmp_path, monkeypatch):
    archives, pilot, bank_path, daily_path = input_files(tmp_path, monkeypatch)
    output = tmp_path / "protected.json"
    output.write_bytes(b"other writer")
    with pytest.raises(FileExistsError):
        primary.run(archives[1], archives[7], pilot, bank_path,
                    daily_path, output, replicates=1)
    assert output.read_bytes() == b"other writer"
    assert not list(tmp_path.glob(".bts-report-*"))
    for method in ("random_month", ""):
        with pytest.raises(ValueError):
            primary.draws(1, method, 0)
    with pytest.raises(ValueError):
        primary.weighted_estimate({}, [0]*31)
    with pytest.raises(ValueError):
        primary.weighted_estimate({}, [1]*30)
    with pytest.raises(ValueError):
        primary.nearest_rank([], 20)
