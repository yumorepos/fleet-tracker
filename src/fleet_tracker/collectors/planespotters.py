"""Planespotters.net collector (stub).

Phase 4 implementation. Per docs/RESEARCH.md topic B, Planespotters has no
public API; the v1 plan is link-out only (per-tail page links to
planespotters.net/photos/reg/{REG} with attribution, no image embed).

If a Phase 4 collector is built, it will scrape the per-registration page
to populate the media table with image URLs and credits — never re-host
the images.
"""

from __future__ import annotations


def fetch(tail_number: str):
    """Phase 4 stub. See docs/RESEARCH.md topic B."""
    raise NotImplementedError(
        "Phase 4: Planespotters scraping not yet implemented. "
        "See docs/RESEARCH.md topic B."
    )
