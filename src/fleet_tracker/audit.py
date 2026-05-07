"""Audit helpers for cross-checking the seed reference rosters against external sources.

First (and currently only) audit: type-level drift between a seed CSV
(`data/reference/{airline}-mainline.csv`) and the Wikipedia fleet article
for the same airline. The seed is hand-curated and a deliberate small
subset of the full fleet (Phase 4 expands it to full inventories); the
audit flags two things that matter for portfolio honesty:

    1. `unrepresented_in_seed` — types Wikipedia lists as in service for
       the airline that the seed has zero tails of. As the seed grows,
       these are the types worth pulling representative tails from next.
    2. `seed_types_missing_from_wikipedia` — types in the seed that
       Wikipedia does not list as in service. Implies retired-but-still-
       in-seed rows, a seed typo, or a Wikipedia article that's behind
       reality. Either way: investigate.

Per-type tail-count deltas are deliberately NOT surfaced. The seed is
intentionally a subset, so deltas always exist; including them turns the
report into noise without changing any decision.

This module is the first downstream consumer of `signal_kind='fleet_membership'`
(see DESIGN §6 and `collectors/wikipedia_fleet.py`). The schema split
between 'ownership' (per-tail, OpenSky) and 'fleet_membership' (type-
level, Wikipedia) exists precisely because audits like this one operate
on the type-level signal — not the per-tail one. Without this consumer,
the schema split is just plumbing; with it, the carve-out earns its keep.

Out of scope for v1:

  - DuckDB-backed historical drift (comparing fleet_membership rows
    across snapshots over time). v1's observations table is rebuilt
    fresh per slice, so historical drift only becomes a real question
    once the v1.5 nightly job is on. Until then this helper operates on
    parsed FleetTypeRow objects + CSV rows directly — no database touch.
  - Auto-correcting the seed CSV. Flagging is the scope; correction is a
    manual review step (DESIGN §2 reserves the MANUAL source for that).
  - Cross-airline batching. One airline at a time keeps the report
    readable; a multi-airline rollup is a notebook concern, not a
    library one.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fleet_tracker.collectors.wikipedia_fleet import (
    FleetTypeRow,
    fetch_fleet_html,
    normalize_aircraft_type,
    page_url,
    parse_current_fleet,
)

logger = logging.getLogger(__name__)

DEFAULT_REFERENCE_ROOT = Path("data/reference")

# Currently only AC has a captured Wikipedia fixture; DL is blocked until
# `tests/fixtures/wikipedia_dl_fleet.html` is captured and the parser is
# verified against it. Adding DL is a separate session, not a flag flip.
SUPPORTED_AIRLINES: frozenset[str] = frozenset({"ac"})


@dataclass(frozen=True)
class SeedDrift:
    """Result of `diff_seed_against_wikipedia`.

    Both lists carry aircraft types in normalized seed form (manufacturer
    prefix stripped — "A220-300", not "Airbus A220-300"), sorted
    alphabetically for stable test assertions and report ordering.
    """
    unrepresented_in_seed: list[str]
    seed_types_missing_from_wikipedia: list[str]


def _read_seed_types(seed_csv_path: Path) -> set[str]:
    """Distinct aircraft types referenced by a seed CSV, normalized.

    The seed CSV's `aircraft_type` column already uses the manufacturer-
    stripped form. Pass each value through `normalize_aircraft_type`
    anyway so a future seed entry written as "Airbus A220-300" still
    compares cleanly against the Wikipedia rows.
    """
    types: set[str] = set()
    with seed_csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = (row.get("aircraft_type") or "").strip()
            if t:
                types.add(normalize_aircraft_type(t))
    return types


def _wikipedia_in_service_types(fleet_rows: list[FleetTypeRow]) -> set[str]:
    """Distinct types Wikipedia lists as currently in service, normalized.

    Order-only rows (in_service is None or 0) are excluded — the seed
    only ever contains delivered aircraft, so flagging an order-only
    type as "unrepresented in seed" would be a false positive (the
    aircraft don't exist yet to put in the seed). Multi-config rows
    collapse to one entry per type via the set.
    """
    return {
        normalize_aircraft_type(r.aircraft_type)
        for r in fleet_rows
        if r.in_service is not None and r.in_service > 0
    }


def diff_seed_against_wikipedia(
    seed_csv_path: Path,
    fleet_rows: list[FleetTypeRow],
) -> SeedDrift:
    """Type-level diff: which types are in one source but not the other?

    Both inputs must already represent a single airline. The caller is
    responsible for picking the seed CSV and the parsed Wikipedia rows
    that correspond to the same carrier — no airline-matching is done
    inside this function.
    """
    seed_types = _read_seed_types(seed_csv_path)
    wiki_types = _wikipedia_in_service_types(fleet_rows)
    return SeedDrift(
        unrepresented_in_seed=sorted(wiki_types - seed_types),
        seed_types_missing_from_wikipedia=sorted(seed_types - wiki_types),
    )


def format_drift_report(airline: str, drift: SeedDrift) -> str:
    """Plain-text report suitable for CLI output and notebook display."""
    lines: list[str] = [
        f"Reference roster drift: {airline.upper()}",
        "=" * 60,
        f"Wikipedia article: {page_url(airline)}",
        "",
    ]
    if drift.unrepresented_in_seed:
        lines.append(
            f"Types Wikipedia lists in service that the seed has no tails of "
            f"({len(drift.unrepresented_in_seed)}):"
        )
        for t in drift.unrepresented_in_seed:
            lines.append(f"  - {t}")
    else:
        lines.append("Every Wikipedia in-service type is represented in the seed.")
    lines.append("")
    if drift.seed_types_missing_from_wikipedia:
        lines.append(
            f"Seed types Wikipedia does not list as in service "
            f"({len(drift.seed_types_missing_from_wikipedia)}) — investigate "
            f"(retired? typo? Wikipedia behind?):"
        )
        for t in drift.seed_types_missing_from_wikipedia:
            lines.append(f"  - {t}")
    else:
        lines.append("Every seed type appears in Wikipedia's current fleet table.")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Fetch + parse + diff + print. Returns 0 on success."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="python -m fleet_tracker.audit",
        description=(
            "Diff a seed reference roster against the Wikipedia fleet article "
            "for the same airline. Type-level drift only."
        ),
    )
    parser.add_argument(
        "--airline",
        default="ac",
        help="Airline code (currently 'ac' only; 'dl' is blocked until a DL "
             "Wikipedia fixture is captured).",
    )
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=DEFAULT_REFERENCE_ROOT,
        help="Directory containing {airline}-mainline.csv files.",
    )
    args = parser.parse_args(argv)

    airline = args.airline.lower()
    if airline == "dl":
        # Explicit pointer per scope guardrail; argparse default would just
        # KeyError later in page_url. Better to fail fast with a usable hint.
        logger.error(
            "DL is out of scope: capture tests/fixtures/wikipedia_dl_fleet.html "
            "first (mirror the AC fixture's pruning), add a parser test, then "
            "add 'dl' to fleet_tracker.audit.SUPPORTED_AIRLINES."
        )
        return 2
    if airline not in SUPPORTED_AIRLINES:
        logger.error(
            "Unknown --airline %r. Supported: %s",
            args.airline, sorted(SUPPORTED_AIRLINES),
        )
        return 2

    seed_path = args.reference_root / f"{airline}-mainline.csv"
    if not seed_path.exists():
        logger.error("Seed CSV not found: %s", seed_path)
        return 2

    html = fetch_fleet_html(airline)
    fleet_rows = parse_current_fleet(html)
    drift = diff_seed_against_wikipedia(seed_path, fleet_rows)
    print(format_drift_report(airline, drift))
    return 0


if __name__ == "__main__":
    sys.exit(main())
