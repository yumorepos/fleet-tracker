"""Aggregation layer (stub).

Phase 4 implementation. The aggregator builds the rollups the dashboard reads:
per-airline counts (mainline, retrofit-scope, retrofitted), per-type composition,
per-tail current-state caches, install rate over rolling windows.

In v1.5 this module also exposes a `nightly` entry point (invoked by
.github/workflows/nightly-collection.yml when enabled) that:
  - calls the real collectors for each tail in scope
  - writes new flights to data/flights/airline=*/year=*/month=*/flights.parquet
  - refreshes denormalised aircraft.current_state
  - writes the per-tail observation rows

See docs/DESIGN.md §4 for the rollups required by the dashboard.
"""

from __future__ import annotations
