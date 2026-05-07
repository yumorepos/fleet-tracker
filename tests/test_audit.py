"""Tests for src/fleet_tracker/audit.py.

Inputs are deterministic: the captured Wikipedia AC fixture
(`tests/fixtures/wikipedia_ac_fleet.html`, pruned 2026-05-06) and the
real `data/reference/ac-mainline.csv`. No live HTTP.

When either of those changes — Wikipedia adds/retires an AC type, or the
seed grows — these tests will fail with a list of which types moved
between buckets. That's the audit doing its job in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet_tracker import audit
from fleet_tracker.audit import (
    SeedDrift,
    _read_seed_types,
    _wikipedia_in_service_types,
    diff_seed_against_wikipedia,
    format_drift_report,
)
from fleet_tracker.collectors.wikipedia_fleet import (
    FleetTypeRow,
    parse_current_fleet,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
AC_SEED = REPO / "data" / "reference" / "ac-mainline.csv"


@pytest.fixture(scope="module")
def ac_rows() -> list[FleetTypeRow]:
    return parse_current_fleet((FIXTURES / "wikipedia_ac_fleet.html").read_text())


@pytest.fixture(scope="module")
def ac_drift(ac_rows) -> SeedDrift:
    return diff_seed_against_wikipedia(AC_SEED, ac_rows)


# ---------------------------------------------------------------------------
# Helpers: confirm the inputs the diff is built from
# ---------------------------------------------------------------------------

def test_seed_types_normalized_to_manufacturer_stripped_form():
    """The seed CSV uses 'A220-300' etc. — read as-is, no manufacturer prefix."""
    seed_types = _read_seed_types(AC_SEED)
    assert seed_types == {
        "A220-300", "787-9", "777-300ER", "A330-300", "A321-200",
    }


def test_wikipedia_in_service_types_excludes_order_only(ac_rows):
    """Order-only types (A350-1000, 787-10, ES-30 in fixture) must not appear.

    The seed only contains delivered tails, so flagging order-only types as
    'unrepresented in seed' would be a permanent false positive.
    """
    in_service = _wikipedia_in_service_types(ac_rows)
    assert "A350-1000" not in in_service  # in_service is None in fixture
    assert "787-10" not in in_service     # ditto
    assert "ES-30" not in in_service      # ditto
    # And every seed type IS present (they're all currently delivered).
    assert {"A220-300", "787-9", "777-300ER", "A330-300", "A321-200"} <= in_service


def test_wikipedia_in_service_types_dedupes_multi_config_rows(ac_rows):
    """A321-200 and 777-300ER each appear as 2 fixture rows; the audit sees 1 type."""
    in_service = _wikipedia_in_service_types(ac_rows)
    # Counted once each despite multi-row Wikipedia configs.
    assert sum(1 for t in in_service if t == "A321-200") == 1
    assert sum(1 for t in in_service if t == "777-300ER") == 1


# ---------------------------------------------------------------------------
# diff_seed_against_wikipedia: the load-bearing assertions
# ---------------------------------------------------------------------------

def test_diff_unrepresented_in_seed_matches_fixture_truth(ac_drift):
    """As of fixture capture: 5 in-service AC types are not in the seed.

    A320-200, A321XLR, 737 MAX 8, 777-200LR, 787-8. When the seed grows
    per Phase 4 ('expand to full inventories'), these names will move to
    seed_types_missing_from_wikipedia=[] and this list will shrink.
    """
    assert ac_drift.unrepresented_in_seed == [
        "737 MAX 8",
        "777-200LR",
        "787-8",
        "A320-200",
        "A321XLR",
    ]


def test_diff_seed_types_missing_from_wikipedia_is_empty(ac_drift):
    """Every type in the AC seed is currently listed as in service by Wikipedia.

    A non-empty list here means either a seed typo, a retired type still
    in the seed, or Wikipedia lagging reality — all of which warrant
    manual review (per DESIGN §2's MANUAL source carve-out).
    """
    assert ac_drift.seed_types_missing_from_wikipedia == []


def test_diff_lists_are_sorted(ac_drift):
    """Stable ordering: tests stay readable, report output is consistent."""
    assert ac_drift.unrepresented_in_seed == sorted(ac_drift.unrepresented_in_seed)
    assert ac_drift.seed_types_missing_from_wikipedia == sorted(
        ac_drift.seed_types_missing_from_wikipedia
    )


def test_diff_handles_empty_seed_csv(tmp_path, ac_rows):
    """An empty seed produces 'every Wikipedia type is unrepresented'."""
    empty_seed = tmp_path / "empty-mainline.csv"
    empty_seed.write_text("tail_number,icao24,aircraft_type\n")
    drift = diff_seed_against_wikipedia(empty_seed, ac_rows)
    assert drift.seed_types_missing_from_wikipedia == []
    # All 10 in-service types from the fixture should land in unrepresented.
    assert len(drift.unrepresented_in_seed) == 10


def test_diff_handles_no_wikipedia_rows(tmp_path):
    """No Wikipedia rows means every seed type lands in 'missing from wiki'."""
    drift = diff_seed_against_wikipedia(AC_SEED, [])
    assert drift.unrepresented_in_seed == []
    assert drift.seed_types_missing_from_wikipedia == sorted({
        "A220-300", "787-9", "777-300ER", "A330-300", "A321-200",
    })


# ---------------------------------------------------------------------------
# format_drift_report: human-readable output
# ---------------------------------------------------------------------------

def test_format_drift_report_includes_airline_and_url(ac_drift):
    report = format_drift_report("ac", ac_drift)
    assert "AC" in report
    assert "https://en.wikipedia.org/wiki/Air_Canada_fleet" in report


def test_format_drift_report_lists_unrepresented_types(ac_drift):
    report = format_drift_report("ac", ac_drift)
    for t in ac_drift.unrepresented_in_seed:
        assert t in report


def test_format_drift_report_celebrates_clean_seed_side(ac_drift):
    """When the seed has no missing-from-wiki types, the report says so."""
    report = format_drift_report("ac", ac_drift)
    assert "Every seed type appears in Wikipedia" in report


def test_format_drift_report_handles_drift_on_both_sides():
    drift = SeedDrift(
        unrepresented_in_seed=["A220-100"],
        seed_types_missing_from_wikipedia=["DC-9-30"],
    )
    report = format_drift_report("ac", drift)
    assert "A220-100" in report
    assert "DC-9-30" in report
    assert "investigate" in report  # the "retired? typo?" hint


# ---------------------------------------------------------------------------
# CLI: scope guardrail (DL blocked until fixture is captured)
# ---------------------------------------------------------------------------

def test_cli_blocks_dl_with_actionable_message(capsys, caplog):
    """--airline dl exits 2 with a message that names the missing fixture."""
    rc = audit.main(["--airline", "dl"])
    assert rc == 2
    log_text = caplog.text
    assert "wikipedia_dl_fleet.html" in log_text
    assert "DL is out of scope" in log_text


def test_cli_blocks_unknown_airline(capsys, caplog):
    rc = audit.main(["--airline", "ua"])
    assert rc == 2
    assert "Unknown --airline" in caplog.text


def test_cli_runs_against_fixture_path(tmp_path, monkeypatch, capsys):
    """End-to-end CLI: --airline ac with the fixture as cache produces a report.

    Pre-seed the wikipedia cache with today's fixture so fetch_fleet_html
    is a cache hit (no live HTTP). The CLI should print a report mentioning
    the AC URL and the unrepresented types.
    """
    # Pre-seed a today-dated cache file containing the AC fixture HTML.
    from fleet_tracker.collectors import wikipedia_fleet as wf
    cache_dir = tmp_path / "wikipedia"
    cache_dir.mkdir()
    today = wf.datetime.now(wf.timezone.utc).strftime("%Y%m%d")
    (cache_dir / f"ac_fleet_{today}.html").write_text(
        (FIXTURES / "wikipedia_ac_fleet.html").read_text()
    )
    monkeypatch.setattr(wf, "DEFAULT_CACHE_ROOT", cache_dir)

    rc = audit.main(["--airline", "ac"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Reference roster drift: AC" in out
    assert "A320-200" in out  # one of the unrepresented types
