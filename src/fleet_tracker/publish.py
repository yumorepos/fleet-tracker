"""Static-site asset generation (stub).

Phase 4 implementation. publish.py emits the JSON blobs and SVG arc maps
that the Astro dashboard consumes:

  - One JSON per airline (landing card data)
  - One JSON per tail (per-tail page data, including the flight history
    consumed by the SVG renderer)
  - One SVG per tail (Winkel-tripel great-circle arc map of recent flights)
  - One JSON for the type-rollup view

Called from the build step before `astro build`. See docs/DESIGN.md §5 for
the SVG renderer details.
"""

from __future__ import annotations
