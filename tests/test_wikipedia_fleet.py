"""Tests for src/fleet_tracker/collectors/wikipedia_fleet.py.

Live HTTP not exercised in CI: tests parse the captured fixture
`tests/fixtures/wikipedia_ac_fleet.html`, pruned from the real Wikipedia
article on 2026-05-06 (CC-BY-SA-4.0; attribution in the fixture header).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from fleet_tracker import db
from fleet_tracker.collectors import wikipedia_fleet
from fleet_tracker.collectors.wikipedia_fleet import (
    CURRENT_FLEET_COLUMNS,
    FleetTypeRow,
    find_rows_for_type,
    normalize_aircraft_type,
    parse_current_fleet,
)
from fleet_tracker.ingest import write_ownership_observation
from fleet_tracker.model import FleetTrackerSource, OwnershipSignal

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ac_fleet_html() -> str:
    return (FIXTURES / "wikipedia_ac_fleet.html").read_text()


@pytest.fixture(scope="module")
def ac_rows(ac_fleet_html: str) -> list[FleetTypeRow]:
    return parse_current_fleet(ac_fleet_html)


# ---------------------------------------------------------------------------
# parse_current_fleet: structural assertions on real Wikipedia data
# ---------------------------------------------------------------------------

def test_parse_returns_expected_aircraft_types(ac_rows):
    """Every type currently in AC's mainline fleet should be parsed out.

    Asserts the 'shape' of AC's fleet as Wikipedia listed it on 2026-05-06.
    If the article gains/loses a type, this test will fail and the fixture
    needs refreshing.
    """
    types = {row.aircraft_type for row in ac_rows}
    expected = {
        "Airbus A220-300",
        "Airbus A320-200",
        "Airbus A321-200",
        "Airbus A321XLR",
        "Airbus A330-300",
        "Airbus A350-1000",
        "Boeing 737 MAX 8",
        "Boeing 777-200LR",
        "Boeing 777-300ER",
        "Boeing 787-8",
        "Boeing 787-9",
        "Boeing 787-10",
        "Heart ES-30",
    }
    assert expected.issubset(types), f"missing: {expected - types}"


def test_parse_a220_300_in_service_count(ac_rows):
    """C-FBOM's type (A220-300) — the user-relevant analog of 'C-FBOM is present'.

    Wikipedia is type-level, so this is the closest assertion to the user's
    'specific row' test case: the type C-FBOM belongs to is in the table
    with the expected fleet count.
    """
    row = next(r for r in ac_rows if r.aircraft_type == "Airbus A220-300")
    assert row.in_service == 42
    assert row.orders == 23


def test_parse_a220_300_seat_config(ac_rows):
    """Seat config: 12J / — W / 125Y / 137 total."""
    row = next(r for r in ac_rows if r.aircraft_type == "Airbus A220-300")
    assert row.seats_business == 12
    assert row.seats_premium is None  # em-dash → None
    assert row.seats_economy == 125
    assert row.seats_total == 137


def test_parse_a321_200_two_subconfigs(ac_rows):
    """Multi-config types appear as multiple rows with shared aircraft_type.

    AC's A321-200 has 16 aircraft in one config (16W/180Y/196 total) and
    5 in a second (8W/176Y/184 total) transferred from EVA Air. The parser
    must surface both sub-rows so callers can see config-level detail.
    """
    a321_rows = [r for r in ac_rows if r.aircraft_type == "Airbus A321-200"]
    assert len(a321_rows) == 2
    in_service_counts = sorted(r.in_service for r in a321_rows)
    assert in_service_counts == [5, 16]  # 21 total
    # The second sub-config (5 aircraft) carries the EVA Air transfer note.
    eva_row = next(r for r in a321_rows if r.in_service == 5)
    assert "EVA Air" in eva_row.notes


def test_parse_strips_citation_markers(ac_rows):
    """Wikipedia's [1], [2] citation superscripts must not bleed into notes."""
    for row in ac_rows:
        assert "[1]" not in row.notes
        assert "[2]" not in row.notes
        # Specific A220-300 note should be clean prose, no bracketed numbers.
        if row.aircraft_type == "Airbus A220-300":
            assert "Deliveries until 2027" in row.notes


def test_parse_handles_em_dash_as_none(ac_rows):
    """Em-dash (—) in numeric columns parses to None, not 0."""
    # A350-1000 is order-only at the time of fixture capture: no in-service.
    a350 = next(r for r in ac_rows if r.aircraft_type == "Airbus A350-1000")
    assert a350.in_service is None
    assert a350.orders == 8


def test_parse_skips_total_footer(ac_rows):
    """The 'Total' footer row must not appear as an aircraft row."""
    types = [r.aircraft_type for r in ac_rows]
    assert "Total" not in types
    assert "total" not in [t.lower() for t in types]


def test_parse_raises_when_no_table():
    """Layout drift should fail loudly, not silently return []."""
    with pytest.raises(ValueError, match="No <table"):
        parse_current_fleet("<html><body><p>nothing here</p></body></html>")


def test_current_fleet_columns_constant_matches_table_shape():
    """Sanity: the 8-column constant matches reality.

    Catches a future Wikipedia layout change that adds/removes a column.
    """
    assert CURRENT_FLEET_COLUMNS == 8


# ---------------------------------------------------------------------------
# normalize_aircraft_type / find_rows_for_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wiki, seed", [
    ("Airbus A220-300", "A220-300"),
    ("Boeing 787-9", "787-9"),
    ("Embraer 175", "175"),
    ("Bombardier CRJ-900", "CRJ-900"),
    ("A220-100", "A220-100"),  # already-stripped form is idempotent
])
def test_normalize_aircraft_type_strips_manufacturer(wiki, seed):
    assert normalize_aircraft_type(wiki) == seed


def test_find_rows_for_type_matches_seed_csv_format(ac_rows):
    """Seed CSV uses 'A220-300'; the matcher should still find the Wikipedia row."""
    matches = find_rows_for_type(ac_rows, "A220-300")
    assert len(matches) == 1
    assert matches[0].aircraft_type == "Airbus A220-300"


def test_find_rows_for_type_returns_all_subconfigs(ac_rows):
    """Multi-config types: caller gets every sub-row, not just the first."""
    matches = find_rows_for_type(ac_rows, "A321-200")
    assert len(matches) == 2


def test_find_rows_for_type_returns_empty_for_unknown(ac_rows):
    """A type AC doesn't operate returns []. That's a meaningful finding."""
    assert find_rows_for_type(ac_rows, "A380-800") == []


# ---------------------------------------------------------------------------
# fetch_fleet_html: cache discipline (no live HTTP)
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)


def test_fetch_fleet_html_cache_hit_no_http(tmp_path, monkeypatch):
    """Cache file with today's date short-circuits the HTTP call."""
    today = _now().strftime("%Y%m%d")
    cache_path = tmp_path / f"ac_fleet_{today}.html"
    cache_path.write_text("<html>cached</html>")

    def _no_http(*a, **kw):
        raise AssertionError("HTTP must not be called on cache hit")

    monkeypatch.setattr(wikipedia_fleet.requests, "get", _no_http)

    html = wikipedia_fleet.fetch_fleet_html(
        "ac", cache_root=tmp_path, now=_now(),
    )
    assert html == "<html>cached</html>"


def test_fetch_fleet_html_cache_miss_evicts_stale(tmp_path, monkeypatch):
    """Yesterday's cache file is evicted; today's file is written from HTTP."""
    yesterday = "20260505"
    today = _now().strftime("%Y%m%d")
    stale_path = tmp_path / f"ac_fleet_{yesterday}.html"
    stale_path.write_text("<html>stale</html>")

    class FakeResp:
        status_code = 200
        text = "<html>fresh</html>"
        def raise_for_status(self): pass

    monkeypatch.setattr(wikipedia_fleet.requests, "get", lambda *a, **kw: FakeResp())

    html = wikipedia_fleet.fetch_fleet_html(
        "ac", cache_root=tmp_path, now=_now(),
    )
    assert html == "<html>fresh</html>"
    assert not stale_path.exists()
    assert (tmp_path / f"ac_fleet_{today}.html").exists()


def test_fetch_fleet_html_sends_identifiable_user_agent(tmp_path, monkeypatch):
    """ToS-clean scraping requires identifying the bot in User-Agent."""
    captured = {}

    class FakeResp:
        status_code = 200
        text = "<html>x</html>"
        def raise_for_status(self): pass

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(wikipedia_fleet.requests, "get", fake_get)
    wikipedia_fleet.fetch_fleet_html("ac", cache_root=tmp_path, now=_now())

    assert "FleetTrackerBot" in captured["headers"]["User-Agent"]
    assert captured["url"] == "https://en.wikipedia.org/wiki/Air_Canada_fleet"


def test_fetch_fleet_html_rejects_unknown_airline(tmp_path):
    with pytest.raises(ValueError, match="Unknown airline"):
        wikipedia_fleet.fetch_fleet_html("xx", cache_root=tmp_path, now=_now())


def test_page_url_returns_known_airline():
    assert wikipedia_fleet.page_url("ac").endswith("/Air_Canada_fleet")
    assert wikipedia_fleet.page_url("dl").endswith("/Delta_Air_Lines_fleet")


# ---------------------------------------------------------------------------
# End-to-end: parse + write_ownership_observation hits DuckDB
# ---------------------------------------------------------------------------

def test_end_to_end_emits_ownership_observations(tmp_path, ac_rows):
    """Wire: Wikipedia fixture → seed-tail match → write_ownership_observation.

    Demonstrates the two-source pattern from DESIGN §2: the same observations
    table accepts WIKIPEDIA_FLEET rows alongside OPENSKY_LIVE rows. This is
    the path the notebook 01 cell will exercise.
    """
    conn = db.connect(tmp_path / "fleet.duckdb")
    db.init_schema(conn)

    # Two seed tails, both A220-300 (the type C-FBOM and C-GROV share).
    seed = [
        ("C-FBOM", "A220-300"),
        ("C-GROV", "A220-300"),
    ]
    source_url = wikipedia_fleet.page_url("ac")
    written = []
    for tail, ac_type in seed:
        matches = find_rows_for_type(ac_rows, ac_type)
        if not matches:
            continue
        obs_id = write_ownership_observation(
            conn,
            tail_number=tail,
            owner_entity="Air Canada",
            signal=OwnershipSignal.OWNED,
            source=FleetTrackerSource.WIKIPEDIA_FLEET,
            source_url=source_url,
            confidence=0.65,
            observed_at=datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc),
            notes=f"Wikipedia type-level: {matches[0].aircraft_type}",
        )
        written.append(obs_id)

    assert len(written) == 2
    rows = conn.sql(
        "SELECT tail_number, source, signal_kind, confidence, notes "
        "FROM observations ORDER BY tail_number"
    ).fetchall()
    assert len(rows) == 2
    for tail_number, source, kind, conf, notes in rows:
        assert source == "wikipedia_fleet"
        assert kind == "ownership"
        assert conf == pytest.approx(0.65)
        assert "owner_entity=Air Canada" in notes
        assert "Wikipedia type-level: Airbus A220-300" in notes
    conn.close()
