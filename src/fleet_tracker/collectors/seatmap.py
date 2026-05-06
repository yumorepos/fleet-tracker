"""Airline booking-site seat map collector (stub).

Phase 4 implementation, possibly never. Per docs/RESEARCH.md topic D, scraping
booking-site seat maps requires a real booking session (cart, dates) or a
reverse-engineered API call; both are brittle and ToS-grey.

v1 uses AeroLOPA URLs stored in the specs table (link-out only). The seatmap
collector exists in the directory layout for symmetry but is intentionally
deferred.
"""

from __future__ import annotations


def fetch(tail_number: str):
    """Phase 4 stub. See docs/RESEARCH.md topic D."""
    raise NotImplementedError(
        "Phase 4 (likely never): airline booking-site seat map scraping "
        "skipped in v1. See docs/RESEARCH.md topic D."
    )
