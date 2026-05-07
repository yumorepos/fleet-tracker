"""Tests for src/fleet_tracker/collectors/airline_press.py.

Live HTTP not exercised in CI: tests parse captured fixtures under
`tests/fixtures/airline_press/`, captured 2026-05-07 from news.delta.com
via the project's collector.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from fleet_tracker.collectors import airline_press
from fleet_tracker.collectors.airline_press import (
    PressRelease,
    RssItem,
    _normalize_type_token,
    _slug_from_url,
    collect_dl,
    fetch_release,
    fetch_rss,
    find_aircraft_types,
    parse_release,
    parse_rss,
)

FIXTURES = Path(__file__).parent / "fixtures" / "airline_press"


@pytest.fixture(scope="module")
def dl_a330neo_html() -> str:
    return (FIXTURES / "dl_a330neo.html").read_text()


@pytest.fixture(scope="module")
def dl_a321neo_html() -> str:
    return (FIXTURES / "dl_a321neo.html").read_text()


@pytest.fixture(scope="module")
def dl_cabin_fleet_html() -> str:
    return (FIXTURES / "dl_cabin_fleet.html").read_text()


@pytest.fixture(scope="module")
def dl_rss_xml() -> str:
    return (FIXTURES / "dl_rss.xml").read_text()


# ---------------------------------------------------------------------------
# RSS discovery
# ---------------------------------------------------------------------------


def test_parse_rss_extracts_items_with_dates(dl_rss_xml):
    """Every <item> in the captured DL RSS has a parseable URL + date."""
    items = parse_rss(dl_rss_xml)
    assert len(items) > 0
    # All items have a non-empty news.delta.com URL.
    for item in items:
        assert item.url.startswith("https://news.delta.com/")
        assert item.title  # title is required
    # At least one item should have a parseable RFC 822 pubDate.
    dated = [i for i in items if i.pub_date is not None]
    assert dated, "At least one item should have a parseable pubDate"
    # And the pubDate should be timezone-aware (RSS feeds always include offset).
    assert dated[0].pub_date.tzinfo is not None


def test_parse_rss_tolerates_missing_pubdate():
    """Items missing pubDate parse with pub_date=None, not crash."""
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
        <channel>
            <title>Test</title>
            <item>
                <title>One</title>
                <link>https://news.delta.com/one</link>
            </item>
        </channel>
    </rss>"""
    items = parse_rss(xml)
    assert len(items) == 1
    assert items[0].pub_date is None


def test_fetch_rss_cache_hit_no_http(tmp_path, monkeypatch):
    """A today-dated cache file short-circuits the HTTP call."""
    today = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    cache_path = tmp_path / f"dl_rss_{today.strftime('%Y%m%d')}.xml"
    cache_path.write_text("<rss>cached</rss>")

    def _no_http(*a, **kw):
        raise AssertionError("HTTP must not be called on cache hit")

    monkeypatch.setattr(airline_press.requests, "get", _no_http)
    xml = fetch_rss("dl", cache_root=tmp_path, now=today)
    assert xml == "<rss>cached</rss>"


def test_fetch_rss_evicts_stale_then_fetches(tmp_path, monkeypatch):
    """Yesterday's cache is evicted; today's file is written from HTTP."""
    today = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    stale = tmp_path / "dl_rss_20260506.xml"
    stale.write_text("<rss>stale</rss>")

    class FakeResp:
        status_code = 200
        text = "<rss>fresh</rss>"
        def raise_for_status(self): pass

    monkeypatch.setattr(airline_press.requests, "get", lambda *a, **kw: FakeResp())
    xml = fetch_rss("dl", cache_root=tmp_path, now=today)
    assert xml == "<rss>fresh</rss>"
    assert not stale.exists()


def test_fetch_rss_rejects_unknown_airline(tmp_path):
    with pytest.raises(ValueError, match="No RSS feed configured"):
        fetch_rss("xx", cache_root=tmp_path)


def test_fetch_rss_sends_identifiable_user_agent(tmp_path, monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        text = "<rss/>"
        def raise_for_status(self): pass

    def fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers
        captured["url"] = url
        return FakeResp()

    monkeypatch.setattr(airline_press.requests, "get", fake_get)
    fetch_rss("dl", cache_root=tmp_path)
    assert "FleetTrackerBot" in captured["headers"]["User-Agent"]
    assert captured["url"] == "https://news.delta.com/rss.xml"


# ---------------------------------------------------------------------------
# Per-release parsing — JSON-LD extraction
# ---------------------------------------------------------------------------


def test_parse_release_extracts_a330neo_fields(dl_a330neo_html):
    """The Argentina A330-900neo release has type-tagged JSON-LD `about`."""
    pr = parse_release(
        dl_a330neo_html,
        source_url="https://news.delta.com/delta-introduces-next-generation-airbus-a330-900neo-flights-between-us-and-argentina",
    )
    assert pr.headline.startswith("Delta introduces next-generation Airbus A330-900neo")
    assert pr.published_at.date() == datetime(2025, 1, 15).date()
    assert pr.publisher == "Delta News Hub"
    assert pr.modified_at is not None
    # Type-tagged in `about[]` AND in headline → must surface.
    assert "A330-900neo" in pr.aircraft_types
    # `about` includes "Aircraft" and the type.
    assert "Aircraft" in pr.categories
    # Body text is non-empty after stripping <script>/<style>.
    assert len(pr.body_text) > 200


def test_parse_release_finds_type_in_headline_when_about_lacks_it(dl_a321neo_html):
    """A321neo Delta First release: no type tag in `about[]`, type lives in headline."""
    pr = parse_release(
        dl_a321neo_html,
        source_url="https://news.delta.com/select-a321neos-begin-service-larger-delta-first-cabin",
    )
    assert "A321neo" in pr.aircraft_types
    # `about[]` is general categories ("On Board", "Domestic First Class", ...)
    # — type is NOT in there for this release. Confirm the parser still
    # caught the type via headline regex.
    assert "A321neo" not in pr.categories


def test_parse_release_handles_no_type_mentioned(dl_cabin_fleet_html):
    """Fleet-wide cabin announcement: no specific type → empty aircraft_types."""
    pr = parse_release(
        dl_cabin_fleet_html,
        source_url="https://news.delta.com/delta-unveils-new-cabin-interior-across-its-fleet",
    )
    # Headline is "Delta unveils new cabin interior across its fleet".
    # No specific type in headline; body might mention some types in passing.
    # This test confirms the parser does NOT invent types — if any are found,
    # they're real mentions in the body.
    for t in pr.aircraft_types:
        # Every reported type must actually appear in body_text.
        assert t.lower().replace(" ", "") in pr.body_text.lower().replace(" ", "")


def test_parse_release_raises_on_missing_jsonld():
    """Layout drift should fail loudly per the wikipedia_fleet pattern."""
    with pytest.raises(ValueError, match="No <script.*ld\\+json"):
        parse_release("<html><body><p>nope</p></body></html>", source_url="https://x")


def test_parse_release_raises_on_missing_date():
    """A NewsArticle without datePublished is unusable; fail loud."""
    html = """<html><head>
    <script type="application/ld+json">
    {"@type": "NewsArticle", "headline": "hi", "publisher": "x"}
    </script>
    </head><body>hi</body></html>"""
    with pytest.raises(ValueError, match="datePublished"):
        parse_release(html, source_url="https://x")


def test_parse_release_walks_graph_wrapper():
    """JSON-LD with @graph wrapper still finds the NewsArticle node."""
    html = """<html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
        {"@type":"WebSite","name":"site"},
        {"@type":"NewsArticle","headline":"H","datePublished":"2026-05-07T10:00:00-04:00","publisher":"P"}
    ]}
    </script></head><body>body</body></html>"""
    pr = parse_release(html, source_url="https://x/y")
    assert pr.headline == "H"
    assert pr.publisher == "P"


# ---------------------------------------------------------------------------
# Aircraft type regex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    # Narrowbody Airbus
    ("Air Canada operates 42 A220-300s with 12J/125Y", {"A220-300"}),
    ("AC's A321XLR enters service in 2026", {"A321XLR"}),
    ("A320neo orders booked for delivery", {"A320neo"}),
    # Widebody Airbus
    ("A330-900neo route to Argentina", {"A330-900neo"}),
    ("A330-300 fleet retrofitted by 2028", {"A330-300"}),
    ("A350-1000 with new Delta One suites", {"A350-1000"}),
    # Boeing
    ("Boeing 737 MAX 8 transitions to Rouge", {"737 MAX 8"}),
    ("the 737 MAX 9 is being retired", {"737 MAX 9"}),
    ("777-300ER and 787-9 wide-body retrofits", {"777-300ER", "787-9"}),
    ("interior refresh on select Boeing 737-800s", {"737-800"}),
    ("787-10 entering service", {"787-10"}),
])
def test_find_aircraft_types_extracts_canonical_form(text, expected):
    assert find_aircraft_types(text) == expected


def test_find_aircraft_types_dedupes_plurals_and_case():
    """A220-300, A220-300s, a220-300 all collapse to one entry."""
    text = "the A220-300 is delivered. We have many a220-300s. Three A220-300 today."
    types = find_aircraft_types(text)
    assert types == {"A220-300"}


def test_find_aircraft_types_handles_max_casing_variants():
    """737 MAX 8, 737 max 8, 737 Max 8 → all canonicalize to '737 MAX 8'."""
    types = find_aircraft_types("737 MAX 8 and 737 max 8 and 737 Max 8")
    assert types == {"737 MAX 8"}


def test_find_aircraft_types_empty_input():
    assert find_aircraft_types("") == set()
    assert find_aircraft_types(None or "") == set()


def test_find_aircraft_types_does_not_match_random_numbers():
    """'737' alone (not 737-NNN, not 737 MAX) shouldn't match — too ambiguous."""
    types = find_aircraft_types("the 737 by itself, or just 787, or 320")
    # Bare '737', '787', '320' without sub-variant don't have patterns. Good:
    # those would be ambiguous. The regex requires a sub-variant or MAX qualifier.
    assert types == set()


def test_normalize_strips_manufacturer_prefixes():
    assert _normalize_type_token("Airbus A220-300") == "A220-300"
    assert _normalize_type_token("Boeing 737 MAX 8") == "737 MAX 8"
    assert _normalize_type_token("A220-300") == "A220-300"  # idempotent


# ---------------------------------------------------------------------------
# fetch_release: cache discipline (no live HTTP)
# ---------------------------------------------------------------------------


def test_fetch_release_cache_hit(tmp_path, monkeypatch):
    today = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    url = "https://news.delta.com/foo-bar-baz"
    slug = "foo-bar-baz"
    cache_path = tmp_path / f"{slug}_{today.strftime('%Y%m%d')}.html"
    cache_path.write_text("<html>cached</html>")

    def _no_http(*a, **kw):
        raise AssertionError("HTTP must not be called on cache hit")

    monkeypatch.setattr(airline_press.requests, "get", _no_http)
    html = fetch_release(url, cache_root=tmp_path, now=today)
    assert html == "<html>cached</html>"


def test_fetch_release_evicts_stale(tmp_path, monkeypatch):
    today = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    url = "https://news.delta.com/some-release"
    stale = tmp_path / "some-release_20260101.html"
    stale.write_text("<html>old</html>")

    class FakeResp:
        status_code = 200
        text = "<html>new</html>"
        def raise_for_status(self): pass

    monkeypatch.setattr(airline_press.requests, "get", lambda *a, **kw: FakeResp())
    fetch_release(url, cache_root=tmp_path, now=today)
    assert not stale.exists()


def test_slug_from_url():
    """URL slug extraction must be filesystem-safe."""
    assert _slug_from_url("https://news.delta.com/foo-bar/") == "foo-bar"
    assert _slug_from_url("https://x.y/z") == "z"
    # Hostile chars get replaced.
    assert _slug_from_url("https://x/foo bar?a=1") == "foo_bar"
    # Empty path falls back to default.
    assert _slug_from_url("https://x/") == "release"


# ---------------------------------------------------------------------------
# collect_dl: end-to-end discovery + parse against fixtures
# ---------------------------------------------------------------------------


def test_collect_dl_against_fixtures(tmp_path, monkeypatch):
    """End-to-end: pre-seed the RSS + per-release caches with fixtures.

    Exercises the full collect_dl path (RSS discovery → fetch each →
    parse → return PressRelease list) without any live HTTP.
    """
    today = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    today_str = today.strftime("%Y%m%d")

    # Pre-seed RSS cache with a synthetic feed that lists our 3 fixtures.
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
        <title>Delta News Hub</title>
        <item>
            <title>A330-900neo</title>
            <link>https://news.delta.com/delta-introduces-next-generation-airbus-a330-900neo-flights-between-us-and-argentina</link>
            <pubDate>Wed, 15 Jan 2025 16:05:11 -0500</pubDate>
        </item>
        <item>
            <title>A321neo Delta First</title>
            <link>https://news.delta.com/select-a321neos-begin-service-larger-delta-first-cabin</link>
            <pubDate>Wed, 11 Feb 2026 11:23:33 -0500</pubDate>
        </item>
        <item>
            <title>Cabin across fleet</title>
            <link>https://news.delta.com/delta-unveils-new-cabin-interior-across-its-fleet</link>
            <pubDate>Sun, 06 Oct 2024 05:49:31 -0400</pubDate>
        </item>
    </channel></rss>"""
    (tmp_path / f"dl_rss_{today_str}.xml").write_text(rss_xml)

    # Pre-seed each release's cache file with the matching fixture HTML.
    fixture_map = {
        "delta-introduces-next-generation-airbus-a330-900neo-flights-between-us-and-argentina": "dl_a330neo.html",
        "select-a321neos-begin-service-larger-delta-first-cabin": "dl_a321neo.html",
        "delta-unveils-new-cabin-interior-across-its-fleet": "dl_cabin_fleet.html",
    }
    for slug, fixture_name in fixture_map.items():
        (tmp_path / f"{slug}_{today_str}.html").write_text(
            (FIXTURES / fixture_name).read_text()
        )

    def _no_http(*a, **kw):
        raise AssertionError(f"HTTP must not be called: {a[0] if a else 'unknown'}")

    monkeypatch.setattr(airline_press.requests, "get", _no_http)

    releases = collect_dl(max_releases=10, cache_root=tmp_path, now=today)
    assert len(releases) == 3

    # First release (A330neo) — has type-tagged about, parsed cleanly.
    r0 = releases[0]
    assert "A330-900neo" in r0.headline
    assert "A330-900neo" in r0.aircraft_types

    # Second release (A321neo) — type lives in headline, not about.
    r1 = releases[1]
    assert "A321neo" in r1.aircraft_types

    # Third (cabin fleet) — fleet-wide, no specific type required.
    r2 = releases[2]
    assert isinstance(r2, PressRelease)


def test_collect_dl_skips_unparseable_releases(tmp_path, monkeypatch):
    """One bad release shouldn't blow up the whole pull — log + skip."""
    today = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    today_str = today.strftime("%Y%m%d")

    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
        <item><title>Good</title><link>https://news.delta.com/select-a321neos-begin-service-larger-delta-first-cabin</link></item>
        <item><title>Bad</title><link>https://news.delta.com/broken</link></item>
    </channel></rss>"""
    (tmp_path / f"dl_rss_{today_str}.xml").write_text(rss_xml)
    (tmp_path / f"select-a321neos-begin-service-larger-delta-first-cabin_{today_str}.html").write_text(
        (FIXTURES / "dl_a321neo.html").read_text()
    )
    # The "broken" release: no JSON-LD, will trigger ValueError in parse_release.
    (tmp_path / f"broken_{today_str}.html").write_text("<html>nothing useful</html>")

    monkeypatch.setattr(
        airline_press.requests,
        "get",
        lambda *a, **kw: pytest.fail("HTTP must not fire"),
    )

    releases = collect_dl(max_releases=10, cache_root=tmp_path, now=today)
    # Only the good release made it through.
    assert len(releases) == 1
    assert "A321neo" in releases[0].aircraft_types
