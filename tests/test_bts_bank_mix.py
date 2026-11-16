"""Offline tests for the bounded BTS departure-bank and destination-mix study."""
from collections import Counter, defaultdict
import csv
from io import StringIO
import hashlib
import json
import zipfile

import pytest

from fleet_tracker import bts_bank_mix as primary
from fleet_tracker import bts_bank_sql_verify as independent


@pytest.mark.parametrize(("clock", "expected"), [
    ("0", "00-05"), ("0001", "00-05"), ("559", "00-05"),
    ("600", "06-11"), ("1159", "06-11"), ("1200", "12-17"),
    ("1759", "12-17"), ("1800", "18-23"), ("2359", "18-23"),
    ("2400", "00-05"), ("2400.00", "00-05"),
])
def test_both_clock_implementations_agree_at_boundaries(clock, expected):
    assert primary.departure_bank(clock) == expected
    assert independent.clock_group(clock) == expected


@pytest.mark.parametrize("clock", ["", "-100", "2360", "2460", "2500", "9999", "8.5", "NaN"])
def test_invalid_local_clocks_are_rejected(clock):
    with pytest.raises(ValueError):
        primary.departure_bank(clock)
    with pytest.raises(ValueError):
        independent.clock_group(clock)


def example_archive(tmp_path, month):
    headers = list(primary.NEEDED)
    rows = []
    # Two 25-record destination-bank cells meet the predeclared matching rule.
    for i in range(25):
        rows.append({
            "FlightDate": f"2025-{month:02d}-10", "Reporting_Airline": "DL",
            "Origin": "ATL", "Dest": "JFK", "CRSDepTime": "0800",
            "Cancelled": "0.00", "Diverted": "0.00",
            "ArrDel15": "0.00" if i < 20 else "1.00",
        })
        rows.append({
            "FlightDate": f"2025-{month:02d}-10", "Reporting_Airline": "DL",
            "Origin": "BOS", "Dest": "JFK", "CRSDepTime": "0900",
            "Cancelled": "0.00", "Diverted": "0.00",
            "ArrDel15": "0.00" if i < 15 else "1.00",
        })
    rows.extend([
        {"FlightDate": f"2025-{month:02d}-10", "Reporting_Airline": "DL",
         "Origin": "ATL", "Dest": "MIA", "CRSDepTime": "1200",
         "Cancelled": "1.00", "Diverted": "0.00", "ArrDel15": ""},
        {"FlightDate": f"2025-{month:02d}-10", "Reporting_Airline": "DL",
         "Origin": "BOS", "Dest": "SFO", "CRSDepTime": "2400",
         "Cancelled": "0.00", "Diverted": "1.00", "ArrDel15": ""},
        # Must not count a second carrier:
        {"FlightDate": f"2025-{month:02d}-10", "Reporting_Airline": "UA",
         "Origin": "ATL", "Dest": "JFK", "CRSDepTime": "0800",
         "Cancelled": "0.00", "Diverted": "0.00", "ArrDel15": "0.00"},
    ])
    csv_data = StringIO()
    writer = csv.DictWriter(csv_data, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    path = tmp_path / f"bts_{month}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("official.csv", csv_data.getvalue())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    baseline = {
        "month": month, "year": 2025,
        "source_zip_sha256": sha, "core_kpi_gate": "GO",
        "counts": {
            "dl": 52, "canceled": 1, "diverted": 1,
            "eligible": 50, "arr15_valid": 50, "ontime": 35,
        },
    }
    return path, sha, baseline


def test_offline_real_zip_processing_and_independent_sql_parity(tmp_path, monkeypatch):
    sources = {}
    bases = []
    for month in (1, 7):
        archive, sha, baseline = example_archive(tmp_path, month)
        sources[month] = archive
        bases.append(baseline)
        monkeypatch.setitem(primary.EXPECTED_SHA, month, sha)
        monkeypatch.setitem(independent.EXPECTED_SHA, month, sha)
    outputs = [primary.analyze(sources[m], m, next(x for x in bases if x["month"] == m))
               for m in (1, 7)]
    for result in outputs:
        comparison = result["shared_destination_bank"]
        assert result["population"]["scheduled"] == 52
        assert comparison["matched_strata"] == 1
        assert comparison["atl_valid_arrivals_in_matched"] == 25
        assert comparison["other_valid_arrivals_in_matched"] == 25
        assert comparison["pooled_standardized_atl_rate"] == 0.8
        assert comparison["pooled_standardized_other_rate"] == 0.6
        assert comparison["pooled_standardized_atl_minus_other_pp"] == 20.0
        assert comparison["coverage_verdict"] == "EXPLORATORY_SUBSET"
        assert len(result["bank_rows"]) == 8
    assert independent.verify(sources, {"months": outputs})["verdict"] == "INDEPENDENT_SQL_PARITY_PASS"


def test_source_hash_drift_fails_closed(tmp_path, monkeypatch):
    archive, sha, baseline = example_archive(tmp_path, 1)
    monkeypatch.setitem(primary.EXPECTED_SHA, 1, sha)
    baseline["source_zip_sha256"] = "tampered"
    with pytest.raises(ValueError, match="hash"):
        primary.analyze(archive, 1, baseline)


def test_source_baseline_population_disagreement_fails(tmp_path, monkeypatch):
    archive, sha, baseline = example_archive(tmp_path, 1)
    monkeypatch.setitem(primary.EXPECTED_SHA, 1, sha)
    baseline["counts"]["ontime"] += 1
    with pytest.raises(ValueError, match="on_time"):
        primary.analyze(archive, 1, baseline)


def test_missing_matched_cells_cannot_generate_fake_standardization():
    banks = defaultdict(Counter)
    strata = defaultdict(Counter)
    banks[("ATL_origin", "00-05")].update(valid_arrivals=3, on_time=2)
    banks[("Other_origin", "00-05")].update(valid_arrivals=3, on_time=1)
    strata[("ATL_origin", "00-05", "JFK")].update(valid_arrivals=3, on_time=2)
    strata[("Other_origin", "00-05", "JFK")].update(valid_arrivals=3, on_time=1)
    out = primary.summarize({"banks": banks, "strata": strata}, 1, "test")
    assert out["shared_destination_bank"]["matched_strata"] == 0
    assert out["shared_destination_bank"]["pooled_standardized_atl_rate"] is None
    assert out["shared_destination_bank"]["coverage_verdict"] == "LOW_COVERAGE_OR_NO_MATCH"
