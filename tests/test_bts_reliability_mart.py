"""Aggregate reporting mart: synthetic contracts, computed ratios, and fail-closed tests."""
from copy import deepcopy
import sqlite3

import pytest

from fleet_tracker.bts_driver_profile import EXPECTED_SHA
from fleet_tracker.bts_reliability_mart import build, validate


def sample():
    pilots, profiles = [], []
    for month in (1, 7):
        pilots.append({
            "month": month, "year": 2025, "reporting_carrier_filter": "Reporting_Airline=DL",
            "source_zip_sha256": EXPECTED_SHA[month], "core_kpi_gate": "GO",
            "counts": {"dl": 10, "canceled": 1, "diverted": 1,
                       "eligible": 8, "arr15_valid": 8, "ontime": 5},
        })
        groups = {}
        for name, scheduled, completed, on_time, late, canceled, diverted, complete, pos in [
            ("ATL_origin", 6, 5, 3, 2, 1, 0, 2, 1),
            ("Other_origin", 4, 3, 2, 1, 0, 1, 1, 0),
            ("ALL_DL", 10, 8, 5, 3, 1, 1, 3, 1),
        ]:
            groups[name] = {
                "scheduled": scheduled, "canceled": canceled, "diverted": diverted,
                "completed": completed, "valid_arrival_flags": completed,
                "on_time": on_time, "late_arrival_15": late,
                "late_arrivals_with_complete_cause_detail": complete,
                "late_arrivals_missing_cause_detail": 0,
                "reported_positive_cause_flight_count": {"LateAircraftDelay": pos},
                "reported_cause_minutes": {"LateAircraftDelay": float(pos * 15)},
            }
        profiles.append({"month": month, "year": 2025, "source_sha256": EXPECTED_SHA[month],
                         "verdict": "GO_FOR_DESCRIPTIVE_CAUSE_AUDIT", "groups": groups})
    return {"both_months_core_gate": "GO", "months": pilots}, {"months": profiles}


def test_sqlite_month_and_origin_views_retain_denominators(tmp_path):
    pilot, profile = sample()
    dest = tmp_path / "mart.sqlite"
    build(pilot, profile, dest)
    with sqlite3.connect(dest) as db:
        rows = db.execute(
            "SELECT month, scheduled, valid_arrival_flags, arrival_ontime_rate,"
            " cancellation_rate FROM v_month_reliability ORDER BY month"
        ).fetchall()
        assert rows == [(1, 10, 8, 0.625, 0.1), (7, 10, 8, 0.625, 0.1)]
        origins = db.execute(
            "SELECT month, origin_group, arrival_ontime_rate,"
            " reported_lateaircraft_positive_share_of_complete_late"
            " FROM v_origin_reliability ORDER BY month, origin_group"
        ).fetchall()
        assert origins == [
            (1, "ATL_origin", 0.6, 0.5),
            (1, "Other_origin", 0.666667, 0.0),
            (7, "ATL_origin", 0.6, 0.5),
            (7, "Other_origin", 0.666667, 0.0),
        ]


def test_refuses_to_overwrite_existing_output(tmp_path):
    pilot, profile = sample()
    dest = tmp_path / "mart.sqlite"
    dest.write_text("keep me")
    with pytest.raises(FileExistsError):
        build(pilot, profile, dest)
    assert dest.read_text() == "keep me"


@pytest.mark.parametrize("change", [
    lambda p, r: p.update(both_months_core_gate="REVISE"),
    lambda p, r: p["months"][0].update(source_zip_sha256="wrong"),
    lambda p, r: r["months"][0].update(verdict="REVISE"),
    lambda p, r: r["months"][0]["groups"]["ATL_origin"].update(on_time=4),
    lambda p, r: r["months"][0]["groups"]["ATL_origin"].update(canceled=0),
    lambda p, r: r["months"][0]["groups"]["ALL_DL"][
        "reported_positive_cause_flight_count"].update(LateAircraftDelay=0),
    lambda p, r: r["months"][0]["groups"]["ATL_origin"].update(
        late_arrivals_missing_cause_detail=1),
    lambda p, r: r["months"][0]["groups"]["Other_origin"][
        "reported_positive_cause_flight_count"].update(LateAircraftDelay=5),
    lambda p, r: p["months"][1].update(month=1),
])
def test_rejects_mismatched_or_unverified_inputs(change):
    pilot, profile = sample()
    change(pilot, profile)
    with pytest.raises((ValueError, KeyError)):
        validate(pilot, profile)


def test_rejects_boolean_instead_of_integer_count():
    pilot, profile = sample()
    profile["months"][0]["groups"]["ATL_origin"]["scheduled"] = True
    with pytest.raises(ValueError):
        validate(pilot, profile)


def test_validates_both_months_without_writing_files():
    pilot, profile = sample()
    months, segments = validate(deepcopy(pilot), deepcopy(profile))
    assert len(months) == 2 and len(segments) == 4
