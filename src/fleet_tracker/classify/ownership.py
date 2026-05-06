"""Ownership classification (stub).

Phase 4 implementation per docs/DESIGN.md §2:

  Two-source consensus: airfleets primary (conf 0.80), Planespotters secondary
  (conf 0.75), airline press tail-specific facts authoritative (conf 1.00),
  manual review tie-break (conf 0.95).

  Resolution rule:
    1. Manual or press observations always win when present and fresh.
    2. Otherwise primary wins unless materially older than secondary.
    3. If primary and secondary disagree within 14 days, flag REVIEW_REQUIRED.
    4. No observations within 180 days: UNKNOWN.

The stub here exists so importers don't ImportError; it raises if invoked,
making accidental dependency in v1 code paths fail loudly.
"""

from __future__ import annotations


def resolve_current_owner(tail_number: str) -> str:
    """Resolve the current owner_entity + owner_type for one tail.

    Phase 4 stub. See docs/DESIGN.md §2 for the algorithm.
    """
    raise NotImplementedError(
        "Phase 4: ownership classification not yet implemented. "
        "See docs/DESIGN.md §2 for the algorithm."
    )
