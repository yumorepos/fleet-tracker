"""Tests for src/fleet_tracker/collectors/.

Real opensky.py is fixture-tested (no live OpenSky HTTP in CI). Stub
collectors (adsb_exchange, planespotters, etc.) are asserted to raise
NotImplementedError so accidental future use fails loudly.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fleet_tracker.collectors import opensky
from fleet_tracker.model import FleetTrackerSource

FIXTURES = Path(__file__).parent / "fixtures"


def _now() -> datetime:
    return datetime(2026, 5, 5, 18, 0, tzinfo=timezone.utc)


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# fetch_flights: cache behaviour
# ---------------------------------------------------------------------------

def test_fetch_flights_cache_hit_no_http(tmp_path, monkeypatch):
    """Cache file with today's date stamp short-circuits the HTTP call entirely."""
    fixture = _load_fixture("opensky_typical.json")
    today = _now().strftime("%Y%m%d")
    cache_path = tmp_path / f"C-FBOM_{today}.json"
    cache_path.write_text(json.dumps(fixture))

    def _no_http(*a, **kw):
        raise AssertionError("HTTP must not be called on cache hit")

    monkeypatch.setattr(opensky.requests, "get", _no_http)

    flights = opensky.fetch_flights(
        icao24="c01234",
        hours=24,
        tail_number="C-FBOM",
        cache_root=tmp_path,
        now=_now(),
    )
    assert len(flights) == 3
    assert all(f.tail_number == "C-FBOM" for f in flights)
    assert all(f.source == FleetTrackerSource.OPENSKY_LIVE for f in flights)


def test_fetch_flights_cache_miss_evicts_stale(tmp_path, monkeypatch):
    """A cache file with yesterday's date stamp is evicted and refetched."""
    yesterday = "20260504"
    today = _now().strftime("%Y%m%d")
    stale_path = tmp_path / f"C-FBOM_{yesterday}.json"
    stale_path.write_text(json.dumps([{"icao24": "old", "firstSeen": 1, "estDepartureAirport": "OLD"}]))

    fresh_response = _load_fixture("opensky_typical.json")
    monkeypatch.setattr(opensky, "_http_fetch", lambda icao24, hours, now: fresh_response)
    monkeypatch.setenv("OPENSKY_USERNAME", "u")
    monkeypatch.setenv("OPENSKY_PASSWORD", "p")

    flights = opensky.fetch_flights(
        icao24="c01234", hours=24, tail_number="C-FBOM",
        cache_root=tmp_path, now=_now(),
    )
    assert len(flights) == 3
    assert not stale_path.exists()                          # stale file was evicted
    assert (tmp_path / f"C-FBOM_{today}.json").exists()     # fresh cache written


def test_fetch_flights_caps_at_two_day_window(tmp_path, monkeypatch, caplog):
    """Hours > 48 get capped to 48 (OpenSky's 2-day window)."""
    captured = {}

    def fake_http(icao24, hours, now):
        captured["hours"] = hours
        return []

    monkeypatch.setattr(opensky, "_http_fetch", fake_http)
    monkeypatch.setenv("OPENSKY_USERNAME", "u")
    monkeypatch.setenv("OPENSKY_PASSWORD", "p")

    opensky.fetch_flights(
        icao24="c01234", hours=240, tail_number="C-FBOM",
        cache_root=tmp_path, now=_now(),
    )
    assert captured["hours"] == 48


# ---------------------------------------------------------------------------
# _to_flight: record conversion
# ---------------------------------------------------------------------------

def test_to_flight_typical_record():
    record = _load_fixture("opensky_typical.json")[0]
    f = opensky._to_flight(record, tail_number="C-FBOM", now=_now())
    assert f.tail_number == "C-FBOM"
    assert f.flight_id.startswith("opensky:c01234:")
    assert f.flight_number == "ACA456"
    assert f.origin_icao == "CYUL"   # OpenSky returns 4-letter ICAO codes
    assert f.destination_icao == "CYYZ"
    assert f.status == "completed"
    assert f.source == FleetTrackerSource.OPENSKY_LIVE
    assert f.actual_off.tzinfo is not None


def test_to_flight_handles_null_airports():
    null_dep_record = _load_fixture("opensky_with_nulls.json")[0]
    f = opensky._to_flight(null_dep_record, tail_number="C-FBOM", now=_now())
    assert f.origin_icao is None
    assert f.destination_icao == "CYYZ"

    null_callsign_record = _load_fixture("opensky_with_nulls.json")[1]
    f2 = opensky._to_flight(null_callsign_record, tail_number="C-FBOM", now=_now())
    assert f2.flight_number is None


def test_to_flight_in_flight_status_when_no_lastseen():
    record = {
        "icao24": "c01234",
        "firstSeen": 1746460320,
        "lastSeen": None,
        "estDepartureAirport": "CYUL",
        "estArrivalAirport": None,
        "callsign": "ACA999  ",
    }
    f = opensky._to_flight(record, tail_number="C-FBOM", now=_now())
    assert f.actual_on is None
    assert f.status == "in_flight"


# ---------------------------------------------------------------------------
# _log_null_rates: instrumentation
# ---------------------------------------------------------------------------

def test_log_null_rates_below_threshold(caplog):
    raw = _load_fixture("opensky_typical.json")  # 3 records, no nulls
    with caplog.at_level("INFO", logger="fleet_tracker.collectors.opensky"):
        opensky._log_null_rates(raw, "C-FBOM")
    info_msgs = [r for r in caplog.records if r.levelname == "INFO"]
    assert any("null estDepartureAirport=0" in r.getMessage() for r in info_msgs)


def test_log_null_rates_above_threshold_warns(caplog):
    raw = _load_fixture("opensky_with_nulls.json")  # 2 records, 1 null dep, 1 null arr -> 50% each
    with caplog.at_level("WARNING", logger="fleet_tracker.collectors.opensky"):
        opensky._log_null_rates(raw, "C-FBOM")
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings
    assert "exceeds 5%" in warnings[0].getMessage()


def test_log_null_rates_empty_response(caplog):
    with caplog.at_level("INFO", logger="fleet_tracker.collectors.opensky"):
        opensky._log_null_rates([], "C-FBOM")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0 flights returned" in m for m in msgs)


# ---------------------------------------------------------------------------
# Reference CSV lookup
# ---------------------------------------------------------------------------

def test_lookup_tail_finds_tail_in_csv(tmp_path):
    csv_path = tmp_path / "ac-mainline.csv"
    csv_path.write_text(
        "tail_number,icao24,aircraft_type,msn,sub_fleet,delivered\n"
        "C-FBOM,c01234,A220-300,55088,33H,2020-06-12\n"
    )
    row = opensky.lookup_tail("C-FBOM", reference_root=tmp_path)
    assert row is not None
    assert row["tail_number"] == "C-FBOM"
    assert row["icao24"] == "c01234"
    assert row["airline"] == "ac"


def test_lookup_tail_case_insensitive(tmp_path):
    csv_path = tmp_path / "ac-mainline.csv"
    csv_path.write_text(
        "tail_number,icao24,aircraft_type,msn,sub_fleet,delivered\n"
        "C-FBOM,c01234,A220-300,55088,33H,2020-06-12\n"
    )
    row = opensky.lookup_tail("c-fbom", reference_root=tmp_path)
    assert row is not None and row["tail_number"] == "C-FBOM"


def test_lookup_tail_returns_none_when_missing(tmp_path):
    (tmp_path / "ac-mainline.csv").write_text("tail_number,icao24\n")
    assert opensky.lookup_tail("X-NONE", reference_root=tmp_path) is None


def test_lookup_tail_finds_in_dl_csv(tmp_path):
    (tmp_path / "dl-mainline.csv").write_text(
        "tail_number,icao24,aircraft_type,msn,sub_fleet,delivered\n"
        "N501DN,a01234,A350-900,182,35Y,2017-09-01\n"
    )
    row = opensky.lookup_tail("N501DN", reference_root=tmp_path)
    assert row is not None
    assert row["airline"] == "dl"


# ---------------------------------------------------------------------------
# _http_fetch: env var validation
# ---------------------------------------------------------------------------

def test_http_fetch_raises_when_env_missing(monkeypatch):
    for var in ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET",
                "OPENSKY_USERNAME", "OPENSKY_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    # python-dotenv may load from a .env file in cwd; explicitly empty it for the test
    monkeypatch.setattr(opensky, "load_dotenv", lambda: None)

    with pytest.raises(RuntimeError, match="No OpenSky credentials"):
        opensky._http_fetch("c01234", 24, _now())


def test_http_fetch_uses_oauth_when_client_creds_set(monkeypatch):
    """OAuth bearer flow: token fetched, then GET with Authorization: Bearer."""
    captured = {}

    monkeypatch.setattr(opensky, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "cid")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "csecret")

    def fake_token(cid, cs):
        captured["token_call"] = (cid, cs)
        return "tok-123"

    monkeypatch.setattr(opensky, "_fetch_oauth_token", fake_token)

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return []

    def fake_get(url, params=None, auth=None, headers=None, timeout=None):
        captured["get_call"] = {"auth": auth, "headers": headers, "params": params}
        return FakeResp()

    monkeypatch.setattr(opensky.requests, "get", fake_get)

    opensky._http_fetch("c01234", 24, _now())

    assert captured["token_call"] == ("cid", "csecret")
    assert captured["get_call"]["auth"] is None
    assert captured["get_call"]["headers"]["Authorization"] == "Bearer tok-123"


def test_http_fetch_uses_basic_when_only_username_set(monkeypatch):
    """Basic auth fallback when OAuth env vars are absent."""
    captured = {}

    monkeypatch.setattr(opensky, "load_dotenv", lambda: None)
    monkeypatch.delenv("OPENSKY_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("OPENSKY_USERNAME", "u")
    monkeypatch.setenv("OPENSKY_PASSWORD", "p")

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return []

    def fake_get(url, params=None, auth=None, headers=None, timeout=None):
        captured["get_call"] = {"auth": auth, "headers": headers}
        return FakeResp()

    monkeypatch.setattr(opensky.requests, "get", fake_get)

    opensky._http_fetch("c01234", 24, _now())

    assert captured["get_call"]["auth"] == ("u", "p")
    assert "Authorization" not in (captured["get_call"]["headers"] or {})


def test_http_fetch_returns_empty_on_404(monkeypatch):
    class FakeResp:
        status_code = 404
        def raise_for_status(self): pass

    monkeypatch.setattr(opensky.requests, "get", lambda *a, **kw: FakeResp())
    monkeypatch.delenv("OPENSKY_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("OPENSKY_USERNAME", "u")
    monkeypatch.setenv("OPENSKY_PASSWORD", "p")
    monkeypatch.setattr(opensky, "load_dotenv", lambda: None)

    assert opensky._http_fetch("c01234", 24, _now()) == []


# ---------------------------------------------------------------------------
# Stub collectors: assert they raise loudly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", [
    "adsb_exchange", "planespotters", "airfleets", "seatmap",
])
def test_collector_stub_raises_not_implemented(module_name):
    """airline_press graduated out of this list when the DL collector landed
    (see tests/test_airline_press.py); the rest are still stubbed."""
    import importlib
    mod = importlib.import_module(f"fleet_tracker.collectors.{module_name}")
    with pytest.raises(NotImplementedError, match="Phase 4"):
        mod.fetch("C-FBOM")
