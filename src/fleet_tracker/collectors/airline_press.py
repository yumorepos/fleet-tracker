"""Airline press release collector (stub).

Phase 4 implementation. Per docs/DESIGN.md §2, press releases naming
specific tails carry confidence 1.00 (declarative airline commitments,
overriding third-party scraping). The Phase 4 collector will:
  - subscribe to AC and DL corporate-news RSS / press feeds
  - parse releases for tail-number mentions (regex C-[A-Z]{4}, N\\d{3,5}[A-Z]{0,2})
  - emit observations with source = AIRLINE_PRESS, confidence = 1.0

Event-driven, not scheduled. Refresh cadence: poll feeds hourly via the
nightly workflow's RSS reader.
"""

from __future__ import annotations


def fetch(tail_number: str):
    """Phase 4 stub. See docs/DESIGN.md §2."""
    raise NotImplementedError(
        "Phase 4: airline press release parsing not yet implemented. "
        "See docs/DESIGN.md §2."
    )
