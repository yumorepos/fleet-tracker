"""Offline contracts for source-gated Delta daily robustness and SQL parity."""
from __future__ import annotations

import csv
from datetime import date
from io import StringIO
import hashlib
import json
import zipfile

import pytest

from fleet_tracker import bts_bank_mix as old
from fleet_tracker import bts_daily_robustness as study
from fleet_tracker import bts_daily_sql_verify as verifier


def _fixture(tmp_path, month, monkeypatch):
    rows = []
    for d in range(1, 32):
        clock = "0800" if d % 2 else "1400"
        day = f"2025-{month:02d}-{d:02d}"

        def add(origin, dest, n, late):
            for i in range(n):
                rows.append({
                    "FlightDate": day, "Reporting_Airline": "DL",
                    "Origin": origin, "Dest": dest, "CRSDepTime": clock,
                    "Cancelled": "0.00", "Diverted": "0.00",
                    "ArrDel15": "1.00" if i < late else "0.00",
                })
        add("ATL", "JFK", 3, 1)
        add("BOS", "JFK", 4, 2)
        add("ATL", "MIA", 1, 0)
        add("BOS", "MIA", 1, 0)
        add("ATL", "SFO", 1, 1)  # unmatched
        add("BOS", "LAX", 2, 0)  # unmatched
        if d <= 25:
            add("ATL", "SEA", 1, 0)
            add("BOS", "SEA", 1, 1)
    rows.extend([
        {"FlightDate": f"2025-{month:02d}-05", "Reporting_Airline": "DL",
         "Origin": "ATL", "Dest": "ORD", "CRSDepTime": "2400",
         "Cancelled": "1", "Diverted": "0", "ArrDel15": ""},
        {"FlightDate": f"2025-{month:02d}-15", "Reporting_Airline": "DL",
         "Origin": "BOS", "Dest": "LAX", "CRSDepTime": "1759",
         "Cancelled": "0", "Diverted": "1", "ArrDel15": ""},
        {"FlightDate": f"2025-{month:02d}-01", "Reporting_Airline": "UA",
         "Origin": "ATL", "Dest": "MIA", "CRSDepTime": "600",
         "Cancelled": "0", "Diverted": "0", "ArrDel15": "0"},
    ])
    data = StringIO()
    writer = csv.DictWriter(data, fieldnames=list(old.NEEDED))
    writer.writeheader()
    writer.writerows(rows)
    path = tmp_path / f"sample_{month}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("on_time.csv", data.getvalue())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(study.EXPECTED_SHA, month, sha)
    monkeypatch.setitem(verifier.EXPECTED_SHA, month, sha)
    baseline = {
        "month": month, "year": 2025,
        "source_zip_sha256": sha, "core_kpi_gate": "GO",
        "counts": {
            "dl": len(rows) - 1, "canceled": 1, "diverted": 1,
            "arr15_valid": len(rows) - 3,
            "eligible": len(rows) - 3,
            "ontime": sum(1 for r in rows if r["Reporting_Airline"] == "DL"
                         and r["ArrDel15"] == "0.00"),
        },
    }
    previous = old.analyze(path, month, baseline)
    return path, baseline, previous


def test_full_source_round_trip_independent_sql_and_contracts(tmp_path, monkeypatch):
    paths = {}
    bases, past = [], []
    for month in (1, 7):
        archive, baseline, previous = _fixture(tmp_path, month, monkeypatch)
        paths[month] = archive
        bases.append(baseline)
        past.append(previous)
    baseline_file, bank_file = tmp_path / "baseline.json", tmp_path / "bank.json"
    baseline_file.write_text(json.dumps({
        "both_months_core_gate": "GO", "months": bases}))
    bank_file.write_text(json.dumps({"months": past}))

    output, independent = tmp_path / "daily.json", tmp_path / "sql.json"
    study.run(paths[1], paths[7], baseline_file, bank_file, output)
    verifier.run(paths, output, independent)
    report = json.loads(output.read_text())
    assert json.loads(independent.read_text())["status"] == "INDEPENDENT_SQL_PARITY_PASS"
    assert len(report["months"]) == 2
    for period in report["months"]:
        thresholds = period["threshold_sensitivity"]
        assert thresholds["10"]["matched_strata"] >= thresholds["25"]["matched_strata"]
        assert thresholds["25"]["matched_strata"] >= thresholds["50"]["matched_strata"]
        assert thresholds["25"]["atl_coverage"] >= thresholds["50"]["atl_coverage"]
        assert len(period["daily_unadjusted"]) == 31
        assert period["leave_one_day_out_25"]["valid_exclusions"] == 31
        assert sum(period["weekday_weekend"][x]["selected_days"]
                   for x in ("weekday", "weekend")) == 31
    assert not list(tmp_path.glob(".bts-report-*"))


def test_recompute_matching_when_day_elimination_removes_borderline_cell():
    from collections import Counter, defaultdict
    cells = defaultdict(Counter)
    for d in range(1, 32):
        for g in study.SEGMENTS:
            x = cells[(d, g, "06-11", "JFK")]
            x["valid_arrivals"] = 3
            x["on_time"] = 2 if g == "ATL_origin" else 1
            if d <= 25:
                y = cells[(d, g, "06-11", "SEA")]
                y["valid_arrivals"] = 1
                y["on_time"] = 1 if g == "ATL_origin" else 0
    full = study.calculate(cells, included_days=range(1, 32), threshold=25)
    reduced = study.calculate(cells, included_days=range(2, 32), threshold=25)
    assert full["matched_strata"] == 2
    assert reduced["matched_strata"] == 1
    assert full["pooled_standardized_gap_pp"] != reduced["pooled_standardized_gap_pp"]


def test_sample_selection_and_reweighting_decompose_observed_change():
    from collections import Counter, defaultdict
    cells = defaultdict(Counter)
    for g in study.SEGMENTS:
        for d in range(1, 32):
            x = cells[(d, g, "06-11", "JFK")]
            x["valid_arrivals"] = 3 if g == "ATL_origin" else 4
            x["on_time"] = 2 if g == "ATL_origin" else 3
            y = cells[(d, g, "18-23", "MIA")]
            y["valid_arrivals"] = 1
            y["on_time"] = 0 if g == "ATL_origin" else 1
    out = study.calculate(cells, included_days=range(1, 32), threshold=25)
    assert out["matched_strata"] == 2
    assert out["all_flights_unadjusted_gap_pp"] is not None
    assert abs(out["all_flights_unadjusted_gap_pp"] + out["selection_shift_pp"]
               + out["reweight_shift_pp"] - out["pooled_standardized_gap_pp"]) <= .002


def test_missing_matches_are_null_not_zero():
    from collections import Counter, defaultdict
    cells = defaultdict(Counter)
    cells[(1, "ATL_origin", "00-05", "JFK")].update(valid_arrivals=5, on_time=4)
    cells[(1, "Other_origin", "00-05", "JFK")].update(valid_arrivals=5, on_time=3)
    out = study.calculate(cells, included_days=(1,), threshold=25)
    assert out["matched_strata"] == 0
    assert out["pooled_standardized_gap_pp"] is None
    assert out["coverage_verdict"] == "LOW_COVERAGE_OR_NO_MATCH"


def test_tampered_source_hash_or_bad_reference_rejected(tmp_path, monkeypatch):
    path, base, previous = _fixture(tmp_path, 1, monkeypatch)
    bad = {**base, "source_zip_sha256": "tampered"}
    with pytest.raises(ValueError, match="Source hash"):
        study.load_month(path, 1, bad, previous)
    previous["bank_rows"][0]["valid_arrivals"] += 1
    with pytest.raises(ValueError, match="Prior bank count mismatch"):
        study.load_month(path, 1, base, previous)


def test_atomic_output_refuses_replacing_existing_report(tmp_path, monkeypatch):
    paths, bases, prior = {}, [], []
    for month in (1, 7):
        path, base, prev = _fixture(tmp_path, month, monkeypatch)
        paths[month] = path
        bases.append(base)
        prior.append(prev)
    pilot, bank = tmp_path / "baseline.json", tmp_path / "bank.json"
    pilot.write_text(json.dumps({"both_months_core_gate": "GO", "months": bases}))
    bank.write_text(json.dumps({"months": prior}))
    output = tmp_path / "robustness.json"
    output.write_bytes(b"other writer")
    with pytest.raises(FileExistsError):
        study.run(paths[1], paths[7], pilot, bank, output)
    assert output.read_bytes() == b"other writer"
