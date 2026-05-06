# Roadmap

The phased build is described in [docs/PLAN.md](docs/PLAN.md). This roadmap covers what comes after Phase 3.

## Phase 4 (next)

The frontend and the rest of the collectors.

- **Astro dashboard**: build the per-tail, per-airline, per-type, and route map views from [docs/DESIGN.md §4](docs/DESIGN.md). Pin Astro version after a one-minute check of the GitHub releases page; planned baseline is Astro 5.17, with v6 stable as a possible upgrade if it has GA'd by Phase 4 kickoff.
- **Map rendering**: implement the Winkel-tripel SVG arc renderer per [DESIGN §5](docs/DESIGN.md). Pre-process Natural Earth coastline once, embed per page.
- **Remaining collectors**: implement `airfleets.py`, `planespotters.py`, `seatmap.py`, `airline_press.py`. Stubs raise `NotImplementedError` today; replace with real fetchers per [docs/RESEARCH.md](docs/RESEARCH.md) recommendations.
- **Nightly collection workflow**: enable `.github/workflows/nightly-collection.yml`. Triggers OpenSky pulls for every active tail, refreshes airfleets / Planespotters fleet rolls weekly, regenerates the Astro site.
- **Public deploy**: GitHub Pages or Vercel, free tier.
- **Full reference rosters**: expand `data/reference/{ac,dl}-mainline.csv` from the 5-10 seed tails to the full 216 (AC) and 987 (DL) inventories.
- **Notebooks**: populate the three placeholder notebooks under `notebooks/` with real analysis (fleet overview, route density, retrofit progress).

## v1.5 (after Phase 4 stabilises)

Triggered by either of the migration signals in [DESIGN §1](docs/DESIGN.md): more than 20 tracked tails per airline, or OpenSky daily credit ceiling hit more than once per week.

- **Nightly OpenSky pull** for in-scope tails, append-only Parquet history. Replaces the v1 on-demand + 24h cache pattern.
- **Retrofit IN_PROGRESS support**: requires hangar dwell data. Either FlightRadar24 paid tier or accumulated OpenSky observations over a long enough window.
- **Ownership classification execution**: today's `resolve_current_owner` stub becomes a real function reading observations from the database.
- **Cabin retrofit pipeline end-to-end**: the retrofit module already exists; v1.5 wires it to real airline_press, planespotters, and seatmap collectors so the IN_PROGRESS / RETROFIT classifications fire automatically.

## v2 (only if the project gets traction)

- **Historical flight backfill**: requires OpenSky Trino/MinIO research-tier access. Skipped in v1 and v1.5 per Yumo's Phase 0 review (a multi-week side quest that does not belong in initial scoping).
- **Interactive map**: only if real users ask for it. v1 and v1.5 ship server-rendered SVG.
- **Additional airlines**: v1 covers AC and DL mainline; v2 could expand to WestJet, United, regional carriers (Jazz, Endeavor, Rouge), or international operators.
- **ch-aviation integration** for higher-fidelity ownership and lessor data. Subscription cost decision pending project traction.

## Future cleanup

Things that should be done eventually but are not blocking v1.

- **Convert retrofit module to editable install once `fleet-retrofit-tracker` is published.** Today `src/fleet_tracker/classify/retrofit.py` is a manual sync from a desktop snapshot, with a pristine-hash test (`tests/test_retrofit_pristine.py`) preventing accidental edits. When the upstream project ships as a pip-installable package, drop the copied file and replace with `pip install fleet-retrofit-tracker` in pyproject. The boundary converter in `src/fleet_tracker/classify/__init__.py` stays; it is the right shape regardless.

- **Re-evaluate Astro version pin** at every major release. Currently planned for 5.17 as Phase 4 baseline; revisit if 6.x has compelling features (live content collections, Rust compiler) by the time Phase 4 starts.

- **Reference roster refresh cadence**: hand-curated CSVs go stale. Build a quarterly refresh script that diffs the current Wikipedia fleet table against the seed CSV and flags adds / removes.
