"""Regression against published, previously independently verified BTS aggregates.

These are GitHub Actions source-derived aggregate artifacts, not raw flight data.
This checks transformation/reporting parity, not independent raw-data validity.
"""
import json
from pathlib import Path
import sqlite3

import pytest

from fleet_tracker.bts_reliability_mart import build, validate

REFERENCE = Path(__file__).parent / "fixtures" / "bts_dl_2025_verified_aggregates.json"


def reference_reports():
    data = json.loads(REFERENCE.read_text())
    return data["pilot"], data["profile"]


def test_published_2025_month_and_origin_aggregates_in_sqlite(tmp_path):
    pilot, profile = reference_reports()
    dest = tmp_path / "delta.sqlite"
    build(pilot, profile, dest)

    with sqlite3.connect(dest) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        months = db.execute("""
            SELECT report_year, month, scheduled, completed, on_time, canceled,
                   diverted, valid_arrival_flags, arrival_ontime_rate
            FROM v_month_reliability ORDER BY report_year, month
        """).fetchall()
        assert months == [
            (2025, 1, 76306, 74025, 59723, 2137, 144, 74025, 0.806795),
            (2025, 7, 94066, 92245, 69327, 1320, 501, 92245, 0.751553),
        ]
        origins = db.execute("""
            SELECT report_year, month, origin_group, scheduled, completed,
                   on_time, positive_lateaircraft, complete_cause_late,
                   arrival_ontime_rate, reported_lateaircraft_positive_share_of_complete_late
            FROM v_origin_reliability ORDER BY report_year, month, origin_group
        """).fetchall()
        assert origins == [
            (2025, 1, "ATL_origin", 17468, 16598, 12777, 1172, 3821, 0.769792, 0.306726),
            (2025, 1, "Other_origin", 58838, 57427, 46946, 4454, 10481, 0.81749, 0.424959),
            (2025, 7, "ATL_origin", 21855, 21492, 14993, 2419, 6499, 0.697608, 0.372211),
            (2025, 7, "Other_origin", 72211, 70753, 54334, 8184, 16419, 0.767939, 0.498447),
        ]
        assert db.execute("SELECT COUNT(*) FROM month_kpi").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM origin_kpi").fetchone()[0] == 4


def test_atomic_no_clobber_when_concurrent_writer_creates_output(tmp_path, monkeypatch):
    pilot, profile = reference_reports()
    destination = tmp_path / "race.sqlite"
    from fleet_tracker import bts_reliability_mart as mart
    real_link = mart.os.link

    def concurrent_create(source, dest):
        destination.write_bytes(b"other writer\n")
        return real_link(source, dest)

    monkeypatch.setattr(mart.os, "link", concurrent_create)
    with pytest.raises(FileExistsError):
        build(pilot, profile, destination)
    assert destination.read_bytes() == b"other writer\n"
    assert not list(tmp_path.glob(".bts-report-*"))


def test_invalid_source_reported_cause_total_is_rejected():
    pilot, profile = reference_reports()
    profile["months"][0]["groups"]["ALL_DL"]["reported_cause_minutes"]["LateAircraftDelay"] = float("nan")
    with pytest.raises(ValueError, match="reported cause minutes"):
        validate(pilot, profile)


def test_wrong_reporting_year_rejected():
    pilot, profile = reference_reports()
    pilot["months"][0]["year"] = 2024
    with pytest.raises(ValueError, match="study scope"):
        validate(pilot, profile)
