"""airfleets.net collector (stub).

Phase 4 implementation. Per docs/RESEARCH.md topic C, airfleets.net is the
primary v1 ownership source. The Phase 4 collector will scrape the per-airline
fleet pages (e.g. https://www.airfleets.net/flottecie/Air%20Canada.htm) and
the per-aircraft pages (keyed by MSN) to populate ownership_history rows.

Refresh cadence per docs/DESIGN.md §2: weekly per tail, identifiable User-Agent,
≤1 req/sec.
"""

from __future__ import annotations


def fetch(tail_number: str):
    """Phase 4 stub. See docs/RESEARCH.md topic C."""
    raise NotImplementedError(
        "Phase 4: airfleets.net scraping not yet implemented. "
        "See docs/RESEARCH.md topic C."
    )
