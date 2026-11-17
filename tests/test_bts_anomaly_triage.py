"""Synthetic, credential-free contracts for bounded BTS anomaly triage."""
from copy import deepcopy
import json
import zipfile

import pytest

from fleet_tracker import bts_anomaly_triage as triage
from fleet_tracker.bts_atomic_output import write_json_new

ZONES = {"ATL": "America/New_York", "JFK": "America/New_York"}


def operation(**changes):
    row = {
        "FlightDate": "2025-01-01", "Reporting_Airline": "DL",
        "Tail_Number": "PRIVATE_TEST_TAIL", "Origin": "ATL", "Dest": "JFK",
        "CRSDepTime": "0800", "CRSArrTime": "1000",
        "DepTime": "0800", "ArrTime": "1000",
        "DepDelay": "0.00", "ArrDelay": "0.00",
        "CRSElapsedTime": "120", "ActualElapsedTime": "120",
        "Cancelled": "0.00", "Diverted": "0.00",
    }
    row.update(changes)
    return row


def sample():
    return [
        operation(),
        operation(Origin="JFK", Dest="ATL", CRSDepTime="0930",
                  CRSArrTime="1130", DepTime="0930", ArrTime="1130"),
        operation(Tail_Number="ANOTHER_TEST_TAIL",
                  CRSDepTime="1200", CRSArrTime="1500",
                  DepTime="1200", ArrTime="1400"),
    ]


def expected():
    return {"scheduled_dl": 3, "completed": 3, "valid": 2,
            "scheduled_clock_conflicts": 1, "overlaps": 1,
            "candidate_pairs": 0}


def test_independent_clock_and_overlap_triage_matches_synthetic_oracle():
    report = triage.triage_rows(sample(), ZONES, 1, expected())
    assert report["timestamp_rejections"] == {
        "scheduled_arrival_local_clock_mismatch": 1}
    assert report["scheduled_clock_residual_magnitude"] == {
        "over_15_to_60_min": 1}
    assert report["overlap_magnitude"] == {"over_15_to_60_min": 1}
    assert report["overlaps"] == 1
    assert "PRIVATE_TEST_TAIL" not in json.dumps(report)
    assert "ANOTHER_TEST_TAIL" not in json.dumps(report)


def test_different_tail_and_unreported_carrier_not_an_overlap():
    rows = [operation(), operation(
        Tail_Number="UNRELATED", Origin="JFK", Dest="ATL",
        CRSDepTime="0930", CRSArrTime="1130",
        DepTime="0930", ArrTime="1130"
    ), operation(Reporting_Airline="UA")]
    exp = {"scheduled_dl": 2, "completed": 2, "valid": 2,
           "scheduled_clock_conflicts": 0, "overlaps": 0,
           "candidate_pairs": 0}
    result = triage.triage_rows(rows, ZONES, 1, exp)
    assert result["overlap_magnitude"] == {}
    assert result["timestamp_rejections"] == {}


def test_completed_and_canceled_denominators_are_separate():
    rows = [operation(), operation(Cancelled="1.00", ArrTime="",
                                   ArrDelay="", ActualElapsedTime="")]
    exp = {"scheduled_dl": 2, "completed": 1, "valid": 1,
           "scheduled_clock_conflicts": 0, "overlaps": 0,
           "candidate_pairs": 0}
    report = triage.triage_rows(rows, ZONES, 1, exp)
    assert report["scheduled_dl"] == 2 and report["completed"] == 1


def test_invalid_double_status_fails_closed():
    rows = [operation(Cancelled="1.00", Diverted="1.00")]
    with pytest.raises(ValueError, match="status"):
        triage.triage_rows(rows, ZONES, 1, {})


def test_frozen_reconciliation_fails_closed():
    corrupted = expected()
    corrupted["overlaps"] = 0
    with pytest.raises(AssertionError, match="Frozen historical"):
        triage.triage_rows(sample(), ZONES, 1, corrupted)


def test_independent_validation_disagreement_stops(monkeypatch):
    def disagree(row, zones):
        return None, "different_classification"
    monkeypatch.setattr(triage, "validate_gate", disagree)
    with pytest.raises(AssertionError, match="classification differs"):
        triage.triage_rows([operation()], ZONES, 1, {})


@pytest.mark.parametrize(("gap", "expected_band"), [
    (-1, "0_to_1_min"), (-5, "over_1_to_5_min"),
    (15, "over_5_to_15_min"), (-30, "over_15_to_60_min"),
    (120, "over_60_min"),
])
def test_coarse_magnitude_band_boundaries(gap, expected_band):
    assert triage.magnitude_band(gap) == expected_band


def test_wrong_source_checksum_fails_before_reading_rows(tmp_path):
    archive = tmp_path / "other.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("other.csv", "not official BTS records")
    with pytest.raises(ValueError, match="SHA-256"):
        triage.triage_archive(archive, 1, ZONES)


def test_atomic_report_output_refuses_overwrite(tmp_path):
    path = tmp_path / "safe-aggregate.json"
    write_json_new(path, {"safe": True})
    with pytest.raises(FileExistsError):
        write_json_new(path, {"safe": False})
    assert json.loads(path.read_text()) == {"safe": True}


def test_source_row_cannot_be_silently_used_in_other_month():
    rows = [operation(FlightDate="2025-07-01")]
    with pytest.raises(ValueError, match="flight date"):
        triage.triage_rows(rows, ZONES, 1, {})
