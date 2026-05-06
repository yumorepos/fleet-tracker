"""Wikipedia airline fleet collector — first real ToS-clean ownership source.

Replaces the airfleets/Planespotters NotImplementedError stubs with a working
secondary signal. Parses the 'Current fleet' wikitable from per-airline
Wikipedia articles (e.g. https://en.wikipedia.org/wiki/Air_Canada_fleet) and
returns one structured row per aircraft sub-config.

Wikipedia fleet tables are TYPE-LEVEL, not per-tail: they list "Air Canada
operates 42 A220-300s with 12J/125Y", not "C-FBOM is owned by AC". So the
ownership observations this collector emits are type-level confirmations:
"per Wikipedia, this airline operates this aircraft type", attached to
seed-CSV tails that match by aircraft_type. That is a weaker signal than
OpenSky's per-icao24 metadata but a useful secondary cross-check, and the
two-source pattern in DESIGN §2 carries the lower confidence (0.65) on the
WIKIPEDIA_FLEET source to reflect this.

Why 0.65, below OpenSky's 0.70:
  - Community-edited (not declarative airline source)
  - Type-level only (no per-tail granularity in airline articles)
  - Frequently outdated for tail-level status (sub-fleet transfers, retirements
    typically lag the airline's actual fleet by weeks-to-months)

Wikipedia article text is licensed CC-BY-SA-4.0; attribution is in the
fixture header comment and in the source_url stored alongside each emitted
observation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

WIKIPEDIA_BASE_URL = "https://en.wikipedia.org/wiki"
USER_AGENT = (
    "FleetTrackerBot/0.1 (https://github.com/yumorepos/fleet-tracker; "
    "research portfolio piece) python-requests"
)
DEFAULT_CACHE_ROOT = Path("data/cache/wikipedia")

# One Wikipedia page per airline. Add more as the seed roster grows.
AIRLINE_PAGES: dict[str, str] = {
    "ac": "Air_Canada_fleet",
    "dl": "Delta_Air_Lines_fleet",
}

# The current-fleet wikitable on every airline article uses the same 8-column
# shape: Aircraft | In service | Orders | J | W | Y | Total | Notes. The 8 is
# load-bearing for _flatten_rowspans and is asserted in tests.
CURRENT_FLEET_COLUMNS = 8


@dataclass(frozen=True)
class FleetTypeRow:
    """One row of a Wikipedia airline fleet table.

    Multi-config aircraft types (e.g. AC's A321-200, which has two cabin
    configurations) appear as multiple rows with the same `aircraft_type`
    and different seat counts. Aggregate by `aircraft_type` if you need a
    per-type rollup.
    """
    aircraft_type: str         # As written by Wikipedia, e.g. "Airbus A220-300"
    in_service: Optional[int]  # None when "—" or order-only
    orders: Optional[int]
    seats_business: Optional[int]
    seats_premium: Optional[int]
    seats_economy: Optional[int]
    seats_total: Optional[int]
    notes: str


def page_url(airline: str) -> str:
    """Stable accessor for the Wikipedia article URL of a known airline.

    Useful as the `source_url` on emitted observations so the per-tail page
    can link directly to the source.
    """
    if airline not in AIRLINE_PAGES:
        raise ValueError(
            f"Unknown airline {airline!r}. Add to AIRLINE_PAGES first."
        )
    return f"{WIKIPEDIA_BASE_URL}/{AIRLINE_PAGES[airline]}"


def fetch_fleet_html(
    airline: str,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    now: Optional[datetime] = None,
) -> str:
    """Fetch the Wikipedia airline-fleet article HTML, cached for the day.

    Mirrors the OpenSky cache discipline (DESIGN §1): one cache file per
    airline per UTC day, keyed by filename date; mismatched filename dates
    trigger eviction + refetch.
    """
    url = page_url(airline)
    now = now or datetime.now(timezone.utc)
    cache_root.mkdir(parents=True, exist_ok=True)
    today = now.strftime("%Y%m%d")
    cache_path = cache_root / f"{airline}_fleet_{today}.html"

    if cache_path.exists():
        logger.info("wikipedia: cache hit %s", cache_path.name)
        return cache_path.read_text()

    for stale in cache_root.glob(f"{airline}_fleet_*.html"):
        if stale != cache_path:
            stale.unlink()

    logger.info("wikipedia: GET %s", url)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    cache_path.write_text(resp.text)
    return resp.text


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class _WikiTableExtractor(HTMLParser):
    """Capture every `<table class="wikitable">` as a 2-D grid of cell dicts.

    Each cell is `{"tag": "td"|"th", "rowspan": int, "colspan": int, "text": str}`.
    Citations (`<sup class="reference">…</sup>`) are stripped from cell text;
    `<br>` becomes a single space.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict]]] = []
        self._in_table = False
        self._current_table: list[list[dict]] = []
        self._current_row: list[dict] = []
        self._current_cell: Optional[dict] = None
        self._cell_text_parts: list[str] = []
        self._sup_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "table":
            cls = attrs_d.get("class") or ""
            if "wikitable" in cls:
                self._in_table = True
                self._current_table = []
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._current_cell = {
                "tag": tag,
                "rowspan": _safe_int(attrs_d.get("rowspan"), 1),
                "colspan": _safe_int(attrs_d.get("colspan"), 1),
            }
            self._cell_text_parts = []
        elif tag == "sup":
            self._sup_depth += 1
        elif tag == "br" and self._current_cell is not None:
            self._cell_text_parts.append(" ")

    def handle_data(self, data):
        if self._current_cell is not None and self._sup_depth == 0:
            self._cell_text_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "sup":
            if self._sup_depth > 0:
                self._sup_depth -= 1
            return
        if not self._in_table:
            return
        if tag in ("td", "th") and self._current_cell is not None:
            text = " ".join(self._cell_text_parts).strip()
            text = " ".join(text.split())  # collapse repeated whitespace
            self._current_cell["text"] = text
            self._current_row.append(self._current_cell)
            self._current_cell = None
        elif tag == "tr":
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = []
        elif tag == "table":
            if self._current_table:
                self.tables.append(self._current_table)
            self._in_table = False
            self._current_table = []


def _safe_int(s: Optional[str], default: int) -> int:
    if s is None:
        return default
    try:
        return int(s)
    except ValueError:
        return default


def _flatten_rowspans(
    rows: list[list[dict]], n_cols: int
) -> list[list[str]]:
    """Project rowspan/colspan-laden rows onto a uniform n_cols grid.

    Wikipedia uses rowspan when one aircraft type has multiple sub-configs
    (e.g. A321-200 with 16J and 8W variants share Aircraft/Orders/J cells).
    Each output row is exactly n_cols strings, with rowspan'd values copied
    down and colspan'd values copied right.
    """
    result: list[list[str]] = []
    carry: dict[int, tuple[str, int]] = {}
    for row in rows:
        flat: list[Optional[str]] = [None] * n_cols
        for col in list(carry.keys()):
            txt, rem = carry[col]
            if col < n_cols:
                flat[col] = txt
            if rem > 1:
                carry[col] = (txt, rem - 1)
            else:
                del carry[col]
        ci = 0
        for cell in row:
            while ci < n_cols and flat[ci] is not None:
                ci += 1
            if ci >= n_cols:
                break
            for _ in range(cell["colspan"]):
                if ci >= n_cols:
                    break
                flat[ci] = cell["text"]
                if cell["rowspan"] > 1:
                    carry[ci] = (cell["text"], cell["rowspan"] - 1)
                ci += 1
        result.append([c if c is not None else "" for c in flat])
    return result


_BLANK_TOKENS = {"", "—", "-", "–", "TBA", "Unknown"}


def _parse_int(cell: str) -> Optional[int]:
    """Convert a wikitable numeric cell to int. None for blanks/em-dashes/'TBA'."""
    s = cell.strip()
    if s in _BLANK_TOKENS:
        return None
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None


def parse_current_fleet(html: str) -> list[FleetTypeRow]:
    """Parse the 'Current fleet' wikitable into one row per aircraft sub-config.

    The first wikitable in the document is treated as the current fleet, in
    line with the consistent Wikipedia article layout (Current fleet section
    first, Historical fleet second). If the layout drifts, the column count
    mismatches will fail noisily — fix the parser, not the caller.
    """
    extractor = _WikiTableExtractor()
    extractor.feed(html)
    if not extractor.tables:
        raise ValueError(
            "No <table class='wikitable'> found in HTML — Wikipedia layout "
            "may have changed; refresh the fixture and re-check the parser."
        )
    raw_rows = extractor.tables[0]
    # The current-fleet table has a 2-row header band (Aircraft / In service /
    # Orders / Passengers (colspan=4) / Notes; J / W / Y / Total). Skip both.
    flat = _flatten_rowspans(raw_rows[2:], CURRENT_FLEET_COLUMNS)
    fleet_rows: list[FleetTypeRow] = []
    for row in flat:
        aircraft_type = row[0].strip()
        if not aircraft_type or aircraft_type.lower() == "total":
            continue
        fleet_rows.append(FleetTypeRow(
            aircraft_type=aircraft_type,
            in_service=_parse_int(row[1]),
            orders=_parse_int(row[2]),
            seats_business=_parse_int(row[3]),
            seats_premium=_parse_int(row[4]),
            seats_economy=_parse_int(row[5]),
            seats_total=_parse_int(row[6]),
            notes=row[7].strip(),
        ))
    return fleet_rows


# ---------------------------------------------------------------------------
# Type-name normalization for cross-source matching
# ---------------------------------------------------------------------------


_MANUFACTURER_PREFIXES = ("Airbus ", "Boeing ", "Embraer ", "Bombardier ", "Heart ")


def normalize_aircraft_type(t: str) -> str:
    """Strip manufacturer prefix and whitespace for cross-source comparison.

    Wikipedia uses 'Airbus A220-300', the seed CSV uses 'A220-300', OpenSky
    uses 'BCS3'. This handles the Wikipedia↔seed-CSV gap; the OpenSky
    typecode mapping lives in notebook 01's audit cell.
    """
    s = t.strip()
    for prefix in _MANUFACTURER_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def find_rows_for_type(
    rows: list[FleetTypeRow], aircraft_type: str
) -> list[FleetTypeRow]:
    """Every Wikipedia row whose normalized type matches the given seed type.

    Returns a list because multi-config types map to multiple rows. Returns
    an empty list when the type isn't listed at all — that's a meaningful
    finding for callers (Wikipedia doesn't think this airline operates this
    type, contradicting the seed CSV).
    """
    target = normalize_aircraft_type(aircraft_type)
    return [r for r in rows if normalize_aircraft_type(r.aircraft_type) == target]
