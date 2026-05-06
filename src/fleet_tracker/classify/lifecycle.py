"""Lifecycle classification (stub).

Phase 4 implementation per docs/DESIGN.md §8:

  Lifecycle state covers durable events (IN_SERVICE, STORED, WRITTEN_OFF).
  Distinct from cabin retrofit state (which lives in classify/retrofit.py)
  and from any future maintenance-state tracking (deferred to v2).

  v1 has no general "grounded for maintenance" indicator; that needs hangar
  dwell data which depends on FlightRadar24 paid tier or accumulated OpenSky
  observations, both deferred to v1.5+.

The stub here exists so importers don't ImportError; it raises if invoked.
"""

from __future__ import annotations


def resolve_lifecycle_state(tail_number: str) -> str:
    """Resolve the current LifecycleSignal for one tail.

    Phase 4 stub. See docs/DESIGN.md §8 for scope.
    """
    raise NotImplementedError(
        "Phase 4: lifecycle classification not yet implemented. "
        "See docs/DESIGN.md §8 for scope."
    )
