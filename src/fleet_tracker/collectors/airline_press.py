"""Airline press release collector — first cabin-observation source.

Implements the DL slice of the airline_press scoping plan
([docs/scoping/airline_press.md](../../docs/scoping/airline_press.md)).
Parses press releases from `news.delta.com` for aircraft-type and
retrofit-program signals. AC support lands in a follow-up PR adapting
the same `parse_release` to Cision's `newswire.ca/news/air-canada/`
discovery layer.

What v1 of this collector captures, per the scoping boundary:

  - announcement existence: date, headline, URL, JSON-LD metadata,
    full body as opaque text
  - aircraft types mentioned in headline + body (regex-based)

What v1 deliberately does NOT do:

  - parse retrofit semantics from body text ("starts September 2026",
    "42 aircraft affected", cabin-class breakdowns). That's an LLM
    extraction or per-carrier curation problem; the tripwire is when
    `retrofit.py` actually needs `install_rate` numerics. Not before.
  - write observations to DuckDB. Returning parsed `PressRelease`
    objects keeps the collector pure; ingest is a separate concern.
    A `write_retrofit_announcement_observation` helper requires a new
    `signal_kind` in the schema and is its own decision.
  - extract per-tail mentions. The original stub described a 1.0-
    confidence "press release names this specific tail" signal; that
    needs tail-regex parsing over body text and is out of scope for
    the v1 announcement-existence shape.

DL News Hub releases are licensed for redistribution by the publisher;
attribution is in each emitted observation's `source_url`.
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "FleetTrackerBot/0.1 (https://github.com/yumorepos/fleet-tracker; "
    "research portfolio piece) python-requests"
)
DEFAULT_CACHE_ROOT = Path("data/cache/airline_press")

# RSS discovery endpoints per airline. AC is intentionally absent in v1 —
# its discovery via newswire.ca/news/air-canada/ is index-scrape, not RSS,
# and lands in a follow-up PR.
RSS_FEEDS: dict[str, str] = {
    "dl": "https://news.delta.com/rss.xml",
}


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PressRelease:
    """One parsed airline press release.

    `aircraft_types` are the manufacturer-stripped, normalized strings
    matched in the headline + body (e.g. "A330-900neo", "737 MAX 8",
    "A321"). `body_text` is the full opaque body — v1 does not parse
    retrofit semantics; that's a v1.5 problem when `retrofit.py` needs
    structured timeline data. `categories` is the JSON-LD `about[]`
    array when present (DL uses it, AC's Cision pages typically don't).
    """
    source_url: str
    headline: str
    published_at: datetime
    publisher: str
    body_text: str
    aircraft_types: tuple[str, ...]
    categories: tuple[str, ...] = field(default_factory=tuple)
    modified_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# RSS discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RssItem:
    url: str
    title: str
    pub_date: Optional[datetime]


def fetch_rss(
    airline: str,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    now: Optional[datetime] = None,
) -> str:
    """Fetch the carrier's RSS feed XML, cached for the day.

    Mirrors the OpenSky/Wikipedia cache discipline (DESIGN §1):
    one cache file per airline per UTC day, stale evictions on miss.
    """
    if airline not in RSS_FEEDS:
        raise ValueError(
            f"No RSS feed configured for {airline!r}. Supported: {sorted(RSS_FEEDS)}"
        )
    url = RSS_FEEDS[airline]
    now = now or datetime.now(timezone.utc)
    cache_root.mkdir(parents=True, exist_ok=True)
    today = now.strftime("%Y%m%d")
    cache_path = cache_root / f"{airline}_rss_{today}.xml"

    if cache_path.exists():
        logger.info("airline_press: rss cache hit %s", cache_path.name)
        return cache_path.read_text()

    for stale in cache_root.glob(f"{airline}_rss_*.xml"):
        if stale != cache_path:
            stale.unlink()

    logger.info("airline_press: GET %s", url)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    cache_path.write_text(resp.text)
    return resp.text


def parse_rss(xml_text: str) -> list[RssItem]:
    """Parse RSS 2.0 feed into a list of items.

    Extracts <link>, <title>, <pubDate> from each <item>. <pubDate> uses
    RFC 822 format per the RSS 2.0 spec; tolerated if missing or
    malformed (item still returned with pub_date=None).
    """
    root = ET.fromstring(xml_text)
    items: list[RssItem] = []
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        pub_date: Optional[datetime] = None
        if pub_raw:
            try:
                # RFC 822: "Tue, 06 May 2026 14:30:00 -0400"
                pub_date = datetime.strptime(pub_raw, "%a, %d %b %Y %H:%M:%S %z")
            except ValueError:
                logger.debug("airline_press: unparseable pubDate %r", pub_raw)
        if link:
            items.append(RssItem(url=link, title=title, pub_date=pub_date))
    return items


# ---------------------------------------------------------------------------
# Per-release fetching + parsing
# ---------------------------------------------------------------------------


def fetch_release(
    url: str,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    now: Optional[datetime] = None,
) -> str:
    """Fetch one release HTML, cached per-URL per-day.

    Cache key is the URL's last path segment plus the date. Press
    releases are immutable once published, but day-keying matches the
    rest of the project's cache discipline and lets `dateModified`
    updates flow through if Delta re-publishes a tweaked version.
    """
    slug = _slug_from_url(url)
    now = now or datetime.now(timezone.utc)
    cache_root.mkdir(parents=True, exist_ok=True)
    today = now.strftime("%Y%m%d")
    cache_path = cache_root / f"{slug}_{today}.html"

    if cache_path.exists():
        logger.info("airline_press: release cache hit %s", cache_path.name)
        return cache_path.read_text()

    for stale in cache_root.glob(f"{slug}_*.html"):
        if stale != cache_path:
            stale.unlink()

    logger.info("airline_press: GET %s", url)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    cache_path.write_text(resp.text)
    return resp.text


def _slug_from_url(url: str) -> str:
    """Extract the URL's last non-empty path segment for cache filenames.

    Falls back to 'release' when the URL has no path (just a host).
    """
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return "release"
    last = segments[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", last) or "release"


def parse_release(html: str, source_url: str) -> PressRelease:
    """Parse one release HTML into a structured `PressRelease`.

    Extraction strategy per the scoping doc:
      1. Find <script type="application/ld+json"> blocks
      2. Filter to @type == "NewsArticle" (handles @graph wrappers too)
      3. Pull headline, datePublished, dateModified, publisher.name, about[]
      4. Strip body text from the visible HTML
      5. Regex aircraft types over headline + body

    Raises ValueError if no NewsArticle JSON-LD is present — that's a
    Wikipedia-style "fail loud, fix the parser" signal that the source's
    layout has drifted, not a quietly-empty observation.
    """
    article = _find_news_article_jsonld(html)
    if article is None:
        raise ValueError(
            "No <script type='application/ld+json'> with @type='NewsArticle' "
            "found. Source layout may have changed; refresh the fixture and "
            "re-check the parser."
        )

    headline = (article.get("headline") or "").strip()
    published_at = _parse_iso8601(article.get("datePublished"))
    if published_at is None:
        raise ValueError(
            f"datePublished missing or unparseable on {source_url}: "
            f"{article.get('datePublished')!r}"
        )
    modified_at = _parse_iso8601(article.get("dateModified"))
    publisher = _publisher_name(article.get("publisher"))

    body_text = _strip_to_text(html)
    types = find_aircraft_types(headline + " " + body_text)
    categories = _coerce_categories(article.get("about"))

    return PressRelease(
        source_url=source_url,
        headline=headline,
        published_at=published_at,
        publisher=publisher,
        body_text=body_text,
        aircraft_types=tuple(sorted(types)),
        categories=tuple(categories),
        modified_at=modified_at,
    )


# ---------------------------------------------------------------------------
# Aircraft type extraction
# ---------------------------------------------------------------------------

# Regex tuned against the 3 captured DL fixtures + the AC Cision sample.
# Matches manufacturer-prefixed forms ("Airbus A220-300", "Boeing 737 MAX 8")
# and bare forms ("A220-300", "787-9"). Each pattern accepts optional plural
# 's' before the trailing word boundary so "A220-300s" / "737-800s" /
# "A321neos" parse correctly; the trailing 's' is stripped during
# normalization. Order matters within the alternation: longer/more-specific
# patterns come first so "737 MAX 8" wins over a stray "737" match.
_TYPE_PATTERNS = [
    # Airbus narrowbody (A220, A319/320/321 with sub-variants)
    r"\bA220-(?:100|300)s?\b",
    r"\bA321(?:XLR|neo|LR)s?\b",
    r"\bA320neos?\b",
    r"\bA319-?100s?\b",
    r"\bA320-?200s?\b",
    r"\bA321-?200s?\b",
    # Airbus widebody (A330/A350)
    r"\bA330-?(?:200|300|800|900)(?:neo)?s?\b",
    r"\bA350-?(?:900|1000)s?\b",
    # Boeing narrowbody (737 family — MAX variants are explicit)
    r"\bBoeing\s+737\s*MAX\s*[789]?s?\b",
    r"\b737\s*MAX\s*[789]?s?\b",
    r"\b737-(?:700|800|900)(?:ER)?s?\b",
    # Boeing widebody (757, 767, 777, 787)
    r"\b757-?(?:200|300)s?\b",
    r"\b767-?(?:200|300|400)(?:ER)?s?\b",
    r"\b777-?(?:200|300)(?:ER|LR)?s?\b",
    r"\b787-?(?:8|9|10)s?\b",
]
_TYPE_REGEX = re.compile("|".join(_TYPE_PATTERNS), re.IGNORECASE)

_NORMALIZE_PREFIX = re.compile(r"^(?:Airbus|Boeing|Embraer|Bombardier|Heart)\s+", re.IGNORECASE)


def find_aircraft_types(text: str) -> set[str]:
    """Return the set of aircraft types referenced in `text`.

    Returns the manufacturer-stripped, normalized form (e.g. "A220-300",
    "737 MAX 8"). Set semantics deduplicate plural/singular and case
    variants; case-folding picks a canonical form per type.
    """
    if not text:
        return set()
    found: set[str] = set()
    for m in _TYPE_REGEX.finditer(text):
        token = _normalize_type_token(m.group(0))
        if token:
            found.add(token)
    return found


def _normalize_type_token(raw: str) -> str:
    """Manufacturer-strip + whitespace-collapse + canonicalize case.

    Canonical form: capital 'A' on Airbus types, uppercase 'ER'/'LR'/'XLR'
    on Boeing/Airbus suffixes, lowercase 'neo', uppercase 'MAX'. Trailing
    plural 's'/'S' is stripped — no canonical type token ends in 's'.
    """
    s = _NORMALIZE_PREFIX.sub("", raw.strip())
    s = re.sub(r"\s+", " ", s)
    # Strip trailing plural before suffix-anchored regexes so `$` works.
    if s and s[-1] in "sS":
        s = s[:-1]
    # Canonicalize case of known mixed-case prefix/suffixes.
    s = re.sub(r"^[Aa](?=\d)", "A", s)            # 'a220' → 'A220'
    s = re.sub(r"(?i)xlr$", "XLR", s)             # 'A321xlr' → 'A321XLR'
    s = re.sub(r"(?i)(?<=\d)lr$", "LR", s)        # '777-200lr' → '777-200LR'
    s = re.sub(r"(?i)er$", "ER", s)               # '777-300er' → '777-300ER'
    s = re.sub(r"(?i)neo$", "neo", s)             # 'A330-900NEO' → 'A330-900neo'
    s = re.sub(r"(?i)\bmax\b", "MAX", s)          # 'max' → 'MAX'
    return s


# ---------------------------------------------------------------------------
# JSON-LD + body extraction internals
# ---------------------------------------------------------------------------


_LD_BLOCK_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _find_news_article_jsonld(html: str) -> Optional[dict]:
    """Return the first NewsArticle node from any JSON-LD block in `html`.

    Handles three shapes seen in the wild:
      - top-level dict with "@type": "NewsArticle"
      - top-level dict with "@graph": [..., {"@type": "NewsArticle"}, ...]
      - top-level list of dicts containing one or more NewsArticle entries
    """
    for raw in _LD_BLOCK_RE.findall(html):
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        node = _walk_for_news_article(data)
        if node is not None:
            return node
    return None


def _walk_for_news_article(data: object) -> Optional[dict]:
    """Recursively search a parsed JSON-LD payload for an @type=NewsArticle dict."""
    if isinstance(data, dict):
        t = data.get("@type")
        if t == "NewsArticle" or (isinstance(t, list) and "NewsArticle" in t):
            return data
        if "@graph" in data:
            return _walk_for_news_article(data["@graph"])
    elif isinstance(data, list):
        for item in data:
            found = _walk_for_news_article(item)
            if found is not None:
                return found
    return None


def _parse_iso8601(s: Optional[str]) -> Optional[datetime]:
    """Tolerant ISO 8601 parser for JSON-LD date fields.

    DL emits dates like '2026-04-13T11:23:33-0500' (no colon in the
    timezone offset). Python's fromisoformat handles this from 3.11.
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _publisher_name(pub: object) -> str:
    """Pull a publisher name from JSON-LD's flexible publisher value."""
    if isinstance(pub, str):
        return pub
    if isinstance(pub, dict):
        name = pub.get("name")
        if isinstance(name, str):
            return name
    return ""


def _coerce_categories(about: object) -> list[str]:
    """JSON-LD `about` is a list of strings or a list of dicts with name."""
    if not about:
        return []
    items = about if isinstance(about, list) else [about]
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            n = item.get("name")
            if isinstance(n, str):
                out.append(n)
    return out


class _BodyTextExtractor(HTMLParser):
    """Strip HTML to visible text, dropping <script>/<style>/<noscript>."""

    _SKIP_TAGS = {"script", "style", "noscript", "head", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in ("br", "p", "li", "div", "h1", "h2", "h3", "h4", "tr"):
            self._parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


def _strip_to_text(html: str) -> str:
    extractor = _BodyTextExtractor()
    extractor.feed(html)
    return extractor.text()


# ---------------------------------------------------------------------------
# Top-level discover-and-parse helper
# ---------------------------------------------------------------------------


def collect_dl(
    *,
    max_releases: int = 10,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    now: Optional[datetime] = None,
) -> list[PressRelease]:
    """Discover the latest DL releases via RSS, fetch each, return parsed.

    `max_releases` caps the per-run fetch count — the RSS feed lists the
    most recent releases first, so the latest N is sufficient for the
    nightly v1 cadence. v1.5's nightly job will track a seen-URLs set
    for idempotent dedup; v1 just re-parses each run.

    Returns parsed `PressRelease` objects in feed order. Releases the
    parser can't structure (no NewsArticle JSON-LD, missing date) are
    logged at WARNING and skipped — one bad release shouldn't blow up
    the whole pull.
    """
    rss_xml = fetch_rss("dl", cache_root=cache_root, now=now)
    items = parse_rss(rss_xml)[:max_releases]
    out: list[PressRelease] = []
    for item in items:
        try:
            html = fetch_release(item.url, cache_root=cache_root, now=now)
            out.append(parse_release(html, source_url=item.url))
        except (ValueError, requests.RequestException) as e:
            logger.warning("airline_press: skipping %s — %s", item.url, e)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="python -m fleet_tracker.collectors.airline_press",
        description=(
            "Discover and parse airline press releases. v1 ships DL only "
            "(news.delta.com); AC support lands in a follow-up PR."
        ),
    )
    parser.add_argument(
        "--airline",
        choices=["dl"],
        default="dl",
        help="Airline code. Currently only 'dl' is supported.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=5,
        help="Max releases to fetch per run.",
    )
    args = parser.parse_args(argv)

    releases = collect_dl(max_releases=args.max)
    print(f"Fetched {len(releases)} releases from {args.airline.upper()}.\n")
    for r in releases:
        print(f"  [{r.published_at.date()}] {r.headline}")
        print(f"      {r.source_url}")
        if r.aircraft_types:
            print(f"      types: {', '.join(r.aircraft_types)}")
        if r.categories:
            print(f"      categories: {', '.join(r.categories[:5])}")
        print()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
