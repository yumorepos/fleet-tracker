"""ADS-B Exchange collector (stub).

Phase 4 implementation, if at all. Per docs/RESEARCH.md topic A, ADS-B Exchange
requires a written commercial license for any use beyond personal/non-commercial,
and a public dashboard sits in a grey zone. v1 skips this source entirely;
v2 may revisit if the project gains traction and a license is in scope.
"""

from __future__ import annotations


def fetch(tail_number: str):
    """Phase 4 stub. See docs/RESEARCH.md topic A."""
    raise NotImplementedError(
        "Phase 4 (likely never): ADS-B Exchange skipped in v1 due to ToS. "
        "See docs/RESEARCH.md topic A."
    )
