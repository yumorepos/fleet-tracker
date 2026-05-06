# Fleet Tracker – Data Landscape Research

Date conducted: 2026-05-05
Time-box: 30 min per topic
Scope: v1 covers Air Canada and Delta Air Lines mainline only.

This document captures the current state of the public data sources Fleet Tracker can use, the constraints attached to each, and a v1 recommendation per source. Phase 1 (DESIGN.md) will turn the recommendations into commitments.

---

## A. Flight data sources

### OpenSky Network

- Current state:
  - Anonymous access returns only the most recent state vectors with a 10-second rate limit.
  - Authenticated users (free OpenSky account) can retrieve up to 1 hour of history via the REST API. Requests with a `time` parameter older than 1 hour return HTTP 400.
  - Active feeders (an ADS-B receiver online ≥30% of the time) get 8000 API credits per day. Non-feeder accounts get a smaller daily quota.
  - Multi-hour and historical data must go through the Trino/MinIO interface, which is a separate access path with its own approval process aimed at researchers.
- Sources checked (2026-05-05):
  - https://openskynetwork.github.io/opensky-api/rest.html
  - https://opensky-network.org/about/faq
  - https://github.com/openskynetwork/opensky-api/blob/master/docs/free/rest.rst
- Gotchas:
  - The 1-hour window is the killer constraint. Without a feeder or Trino access, Fleet Tracker cannot backfill history.
  - Quota is shared across endpoints, so expensive `/flights/aircraft` calls can starve `/states/all` polling.
  - Coverage of remote airspace (northern Canada in particular) can be sparse, which matters for AC.
- Open questions:
  - Is a Trino/MinIO research-tier application realistic for a personal portfolio project? Worth a follow-up email from Yumo.
  - Does setting up a feeder at Yumo's location materially improve quota and coverage of in-scope tails?
- v1 recommendation: Use authenticated OpenSky as the primary live flight source. Accept the 1-hour history limitation and surface it in the dashboard UI as "History since collection start." Plan to revisit Trino access in v1.5.

### ADS-B Exchange

- Current state:
  - Personal and non-commercial access is via RapidAPI at low cost (paid, but cheap). Free keys are not advertised.
  - Any commercial use, including non-revenue projects built for a commercial entity, requires a written commercial license.
  - Limited reduced-fee access exists for non-profits, research, and education, but only for entities that also host a feeder.
- Sources checked (2026-05-05):
  - https://www.adsbexchange.com/products/enterprise-api/
  - https://www.adsbexchange.com/api-lite/
  - https://adsbx.zendesk.com/hc/en-us/articles/37363886073613
- Gotchas:
  - "Personal portfolio published publicly" sits in a grey zone. The site's wording leans toward requiring a commercial license for anything visible to the public.
  - RapidAPI billing is per-request, easy to overrun.
- Open questions:
  - Would ADSBexchange consider a portfolio piece "personal" or "commercial"? Safer to assume the latter without a written reply.
- v1 recommendation: Skip in v1. The ToS friction is not worth solving for a portfolio project when OpenSky covers the same use case.

### FlightAware AeroAPI

- Current state:
  - Personal and academic use is free up to a $5/month query budget. Above that, billing kicks in.
  - Standard commercial tier is $100/month, premium is $1000/month.
  - All plans include a 14-day free trial.
  - 60+ endpoints including flight history, flight tracks, schedules, and aircraft type lookups.
- Sources checked (2026-05-05):
  - https://www.flightaware.com/commercial/aeroapi/
  - https://www.flightaware.com/aeroapi/portal
  - https://www.flightaware.com/commercial/aeroapi/AeroAPI_Standard_License.pdf
- Gotchas:
  - The "personal/academic" $5/mo allowance does not cleanly cover a public-facing dashboard. The Standard License Agreement restricts redistribution; a public dashboard re-publishing AeroAPI fields likely needs a paid tier.
  - $5/month burns fast at AeroAPI per-query rates if the dashboard polls hot.
  - License terms restrict caching duration in some endpoints; need to read the Standard License PDF in full before relying on cached AeroAPI data on a public site.
- Open questions:
  - Does the Standard License explicitly forbid re-display of cached fields on a public site after N hours? Yumo to skim the PDF before Phase 1.
- v1 recommendation: Do not use AeroAPI for primary live flight data on the public dashboard. Optionally use it for one-off reference lookups (aircraft type, MSN) during local development, attributed but not redistributed. Reassess if the project moves to a paid tier in v2.

### Airline schedule data sources

- Current state:
  - OAG and Cirium are the comprehensive commercial sources. No free public tier.
  - IATA publishes aggregate quarterly chartbooks but not tail-level schedules.
  - Airlines publish schedule PDFs and timetables on their corporate sites with varying machine-readability. AC and DL both expose timetables via their booking widgets.
  - OpenSky's `/flights/aircraft` and AeroAPI's `/schedules` endpoints can synthesize per-tail history from observation data once we have it.
- Sources checked (2026-05-05):
  - https://www.oag.com/airline-schedules-data
  - https://www.cirium.com/data/flight-schedules/
- Gotchas:
  - Airline timetable HTML changes shape with seasonal redesigns. Brittle.
  - Schedule data is not the same as flown data; for retrofit/cabin work we want flown-history tied to specific tails, not published schedules.
- Open questions:
  - None blocking. Schedules are not in v1's critical path.
- v1 recommendation: Derive flight history from observed flights (OpenSky), not from published schedules. Defer schedule integration to v2 unless a specific need surfaces.

---

## B. Aircraft sighting and photo databases

### Planespotters.net

- Current state:
  - 1M+ photos covering 50,000+ aircraft. Per-registration URLs follow `https://www.planespotters.net/photos/reg/{REG}` and are stable.
  - Terms of Use grant Planespotters.net a non-exclusive license from uploaders; full rights remain with the photographer.
  - Thumbnails to partner sites are permitted with attribution `Copyright © {photographer name}` and a link back to the original photo.
  - No publicly documented API. Third-party scrapers exist on GitHub.
- Sources checked (2026-05-05):
  - https://www.planespotters.net/legal/termsofuse
  - https://www.planespotters.net/legal/privacypolicy
  - https://www.planespotters.net/
- Gotchas:
  - Hot-linking thumbnails to a public dashboard without a partner agreement is grey. The safest pattern is link-out (Fleet Tracker shows attribution and a clickable link to the photo page on Planespotters.net, with no inline image embed).
  - Scraping for fleet rosters is technically possible but should be rate-limited and identifiable via User-Agent.
- Open questions:
  - Is there a partner program for portfolio sites that would grant inline thumbnail rights? Worth a polite contact form ask, but not blocking.
- v1 recommendation: Use Planespotters as a primary link-out for the per-tail "media" surface. Never re-host images. Use as a secondary fleet roster source, scraped at low frequency (≤1 req/sec, identifiable UA, daily cap).

### JetPhotos

- Current state:
  - Public site at jetphotos.com. Per-registration pages at `/registration/{REG}`.
  - An undocumented JSON endpoint at `jetphotos.net/api.php?reg={REG}` is referenced in old forum posts and used by hobbyist projects.
  - No published API terms.
- Sources checked (2026-05-05):
  - https://www.jetphotos.com/
  - https://forums.jetphotos.com/forum/aviation-photography-videography-forums/aircraft-types-and-other-photo-data/59525-jetphotos-net-api
  - https://github.com/zaarheed/jetphotos-api
- Gotchas:
  - The `api.php` endpoint has no SLA, no documented terms, and could disappear without notice.
  - JetPhotos is owned by Flightradar24; redistribution policy likely follows FR24's, which is restrictive.
- Open questions:
  - Is there a sanctioned API path? Probably not for free. Worth a contact-form ask if Planespotters proves insufficient.
- v1 recommendation: Skip in v1. Use Planespotters as the only photo source. JetPhotos can be a v2 fallback if Planespotters has gaps for specific tails.

### Airliners.net

- Current state:
  - Long-running site, photo and forum content. No public API.
  - Per-registration search exists but URLs are query-string based, not as cleanly stable as Planespotters.
- Sources checked (2026-05-05):
  - https://www.airliners.net/
- Gotchas:
  - Site has stricter copyright posture historically; aggressive about hot-linking.
  - URL stability for per-tail pages is not guaranteed.
- Open questions:
  - None.
- v1 recommendation: Skip. Not worth the integration effort given Planespotters covers the role.

---

## C. Ownership and lessor data

### airfleets.net

- Current state:
  - Free public site. Per-airline fleet pages list every tail with type, MSN, delivery date, current operator, and historical ownership chain.
  - URL pattern `https://www.airfleets.net/flottecie/{airline}.htm` for fleet pages, per-aircraft pages keyed by MSN.
  - No published API. HTML is parseable but layout is dated and changes occasionally.
  - Third-party scrapers exist on GitHub (e.g. `albert-torres/airfleet-scraper`).
- Sources checked (2026-05-05):
  - https://www.airfleets.net/home/
  - https://www.airfleets.net/flottecie/Delta%20Air%20Lines.htm
  - https://github.com/albert-torres/airfleet-scraper
- Gotchas:
  - Site has no robots.txt restriction visible, but courteous scraping (≤1 req/sec, daily cap) is the right posture.
  - Lessor-vs-owner distinction is sometimes ambiguous in the data; needs validation against a second source.
  - Historical ownership is rich, but date precision varies (sometimes year-only).
- Open questions:
  - None blocking.
- v1 recommendation: Primary source for ownership and historical operator data. Cache aggressively; refresh per tail at most weekly.

### ch-aviation

- Current state:
  - Most authoritative commercial source. 81,000+ aircraft tracked, lessor portfolios, lease end dates, SPV ownership chains.
  - Paid only. Pricing not public; enterprise sales model.
- Sources checked (2026-05-05):
  - https://www.ch-aviation.com/
- Gotchas:
  - Subscription cost likely out of scope for a portfolio project.
- Open questions:
  - None.
- v1 recommendation: Skip in v1. Note as a v2 upgrade path if Fleet Tracker needs higher-fidelity ownership data.

### Planespotters.net fleet pages

- Current state:
  - Each airline has a fleet roster page with per-tail rows: type, MSN, delivery, status (active/stored/written-off).
  - Operator history shown per aircraft on its detail page.
  - Same ToS as the photo side covered above.
- Sources checked (2026-05-05):
  - https://www.planespotters.net/airlines
- Gotchas:
  - Operator history granularity is coarser than airfleets in some cases.
  - HTML structure is more modern and reliable than airfleets, but still scraper-dependent.
- Open questions:
  - None.
- v1 recommendation: Secondary source. Use as tie-break when airfleets and Planespotters disagree, with a manual review flag for cases where they cannot be reconciled. Resolution rule for Phase 1: airfleets primary, Planespotters secondary, manual review tertiary.

---

## D. Seat map and LOPA sources

### AeroLOPA

- Current state:
  - Active and growing as of 2026, in the middle of a phased feature rollout (color-coded recommendations, peer ratings, side-by-side comparisons).
  - SeatGuru shut down October 2025, leaving AeroLOPA as the dominant free LOPA reference.
  - URL pattern `https://www.aerolopa.com/{airline-code}/{type-config}` (varies by airline structure).
  - No formal attribution policy published; observed convention on third-party sites is link-back with a credit line.
- Sources checked (2026-05-05):
  - https://www.aerolopa.com/
  - https://blog.awardfares.com/seatguru-alternatives/
  - https://thriftytraveler.com/news/travel/aerolopa-levels-up/
- Gotchas:
  - The site's LOPAs are illustrations, not raw data; we cannot redistribute the images. URL link-outs only.
  - Sub-fleet coverage for AC and DL is good but not 100%; some niche configs (e.g. AC's older 777 sub-variants) may lag.
- Open questions:
  - Email AeroLOPA to confirm the link-out approach is acceptable for a portfolio dashboard. Not blocking but courteous.
- v1 recommendation: Primary seat-map source. Per sub-fleet, store one AeroLOPA URL plus a copy-credit line. Never embed the image.

### SeatGuru

- Current state:
  - Shut down October 2025. The seatguru.com domain redirects to TripAdvisor's main page.
- Sources checked (2026-05-05):
  - https://aerospaceglobalnews.com/news/seatguru-shutdown-seat-maps-airlnes/
- Gotchas:
  - Any historical reference to SeatGuru links is dead.
- v1 recommendation: Do not use. Remove from any reference notes inherited from the retrofit tracker if present.

### Airline booking-site seat maps

- Current state:
  - Both AC and DL expose seat maps inside the booking flow. These are real, sub-fleet-correct, and update when retrofits land.
  - Scraping requires either a real booking session (cart, dates) or a reverse-engineered API call. Brittle and ToS-grey.
- Sources checked (2026-05-05): retrofit tracker conventions in `STRUCTURE.md` (desktop snapshot).
- Gotchas:
  - Bot-detection on airline booking sites is aggressive. Likely needs Playwright with human-like timing.
  - Schema changes when the airline updates its booking platform.
- Open questions:
  - Worth the effort versus AeroLOPA coverage gaps?
- v1 recommendation: Defer. Inherit the retrofit tracker's `seatmap_scanner.py` shape but stub it out for v1; only build it if a specific sub-fleet has poor AeroLOPA coverage.

---

## E. Hangar and routing data

### Flightradar24 API

- Current state:
  - Official FR24 API exists at `fr24api.flightradar24.com`, with documented endpoints for live flights, historical flights, and flight summaries.
  - Tier pricing is not published; sales-led model. Self-serve free tier appears to exist for evaluation but is not clearly described in public docs.
  - History endpoints are the relevant ones for hangar dwell detection.
- Sources checked (2026-05-05):
  - https://fr24api.flightradar24.com/
  - https://fr24api.flightradar24.com/docs
  - https://www.flightradar24.com/blog/b2b/how-to-get-started-with-the-flightradar24-api/
- Gotchas:
  - Without published pricing, hard to plan around. Treat as paid until proven otherwise.
  - The retrofit tracker's `hangar_tracker.py` was designed against FR24 history pages, not the API; a port may need adaptation.
- Open questions:
  - Does FR24 have a personal/academic tier comparable to AeroAPI's $5/mo? Worth asking.
- v1 recommendation: Defer hangar dwell tracking to v1.5. Stub `collectors/hangar_tracker.py` in v1 with a docstring noting the data dependency. Hangar logic only matters when retrofit IN_PROGRESS classification fires, which is itself a v1.5 feature for Fleet Tracker.

### OpenSky for hangar dwell

- Current state:
  - The 1-hour history window makes OpenSky useless for detecting multi-week dwells unless we accumulate observations daily over a long period.
- v1 recommendation: Once nightly collection lands (v1.5 per the brief's storage strategy), accumulated OpenSky observations could substitute partially for FR24 history. This is a v1.5+ consideration.

---

## F. Reference fleet data

### Air Canada mainline

- Current state (as of 2026-05-05):
  - Total mainline ≈ 216 passenger aircraft per Wikipedia, with continuous flux due to Rouge transfers and new deliveries.
  - Approximate composition (sources disagree on exact counts due to live transfers):
    - A220-300: 37–42
    - A321ceo: 20–34 (active transfer of 737 MAX to Rouge announced; A321 numbers stable but A321XLR deliveries imminent)
    - A330-300: ~14
    - 787-8: ~8
    - 787-9: ~32
    - 777-200LR: ~6
    - 777-300ER: ~19
    - A220 + 737 MAX (latter transferring out)
  - A350-1000 deliveries upcoming (announced April 2026, fleet entry later in the decade).
- Sources checked (2026-05-05):
  - https://en.wikipedia.org/wiki/Air_Canada_fleet
  - https://simpleflying.com/air-canada-fleet-2026/
  - https://www.aircanada.com/ca/en/aco/home/fly/onboard/fleet.html
  - https://flymag.com/air-canada-to-move-entire-737-max-fleet-to-rouge-in-2026/
- Gotchas:
  - The retrofit tracker's `STRUCTURE.md` shows the dashboard reading "18 / 167" for AC retrofits, implying a 167-tail retrofit scope. With mainline ≈ 216, that 49-aircraft gap likely excludes 777-200LR (6), some A321 sub-variants, and certain widebodies not in the announced retrofit program. Phase 1 needs to reconcile this and document it explicitly so the dashboard is not confusing.
  - Rouge transfers move tails out of mainline scope but are public events — the seed CSV must be refreshable, not frozen.
- Open questions:
  - Is the 167 figure in the retrofit tracker authoritative or aspirational? Yumo will likely have direct knowledge.
- v1 recommendation: Hand-curate `data/reference/ac-mainline.csv` from the Wikipedia table cross-checked against airfleets.net. Ship with 5–10 representative tails per the brief's deferral, with `C-FBOM` (A220-300) confirmed for the vertical slice. Plan a quarterly refresh.

### Delta Air Lines mainline

- Current state (as of 2026-05-05):
  - Total mainline: 987 aircraft per Wikipedia, the third largest commercial fleet in the world.
  - World's largest sub-fleets of A220, 717, 757, 767, A330.
  - Active retrofit programs on 757, A321neo, A350 ("dark redesign", per the retrofit tracker README).
  - A350-1000 deliveries: 4 in 2026, 4 in 2027, 12 thereafter.
- Sources checked (2026-05-05):
  - https://en.wikipedia.org/wiki/Delta_Air_Lines_fleet
  - https://www.delta.com/us/en/aircraft/overview
  - https://www.airfleets.net/flottecie/Delta%20Air%20Lines.htm
  - https://flightseatmap.com/airlines/delta-air-lines/fleet
- Gotchas:
  - DL mainline is roughly 4.5x larger than AC. Storage and ingest planning needs to scale accordingly even at v1's "5–10 tails" sample.
  - Sub-fleet codes for DL (e.g. 35H for A350-900 Premium Select config) are operationally meaningful and should be preserved in the schema.
- Open questions:
  - None blocking.
- v1 recommendation: Hand-curate `data/reference/dl-mainline.csv` from the Wikipedia table. Pick a known retrofit-target tail for the vertical slice if `C-FBOM` proves problematic for the DL side; the retrofit tracker fixtures already favor `C-FBOM` for AC.

---

## G. Stack verification

### Astro

- Current state:
  - Stable: Astro 5.17.
  - Astro 6 is in beta as of January–February 2026, with stable release described as "weeks away" in a Feb 10 announcement. By 2026-05-05, v6 stable is plausible but worth confirming before scaffolding.
  - Astro 6 ships live content collections (stable, was experimental in 5.10), CSP support stable, refactored dev server, experimental Rust compiler.
- Sources checked (2026-05-05):
  - https://github.com/withastro/astro/releases
  - https://astro.build/
  - https://astro.build/blog/astro-6-beta/
  - https://astro.build/blog/whats-new-april-2026/
- Gotchas:
  - Phase 3 does not build the Astro frontend (deferred to Phase 4 per the brief). For Phase 3, Astro version choice is documentation-only.
  - When Phase 4 starts, pin the most recent stable release rather than chasing v6 beta if v6 has not GA'd.
- v1 recommendation: Document Astro 5.17 as the planned Phase 4 baseline, with a flag in `ROADMAP.md` to evaluate v6 stable before frontend work begins.

### DuckDB

- Current state:
  - Hive-style partitioning fully supported via `COPY ... (FORMAT PARQUET, PARTITION_BY (...))`.
  - `APPEND` option for adding to existing partitioned trees.
  - Filters on partition keys are pushed down automatically.
  - Best-practice guidance: do not over-partition. Many small files at write time is expensive and at read time hurts predicate pushdown.
- Sources checked (2026-05-05):
  - https://duckdb.org/docs/current/data/partitioning/hive_partitioning
  - https://duckdb.org/docs/current/data/partitioning/partitioned_writes
  - https://motherduck.com/learn/partitioned-writes-parquet-ducklake/
- Gotchas:
  - At Fleet Tracker's volume (a few thousand flights per airline per month), partitioning by `airline/year/month` produces files in the kilobyte-megabyte range. Consider partitioning by `airline/year` only for v1, then revisit.
  - Hive partitioning + DuckDB query patterns benefit from consistent column types across partitions; schema evolution needs care.
- v1 recommendation: Layout `data/flights/airline=*/year=*/month=*.parquet` per the brief, but commit in DESIGN.md to revisit if file counts grow uncomfortable.

### Python packaging

- Current state:
  - 2026 community consensus is `uv` for new projects: 10–100x faster than pip, ~10x faster than Poetry, strict PEP 517/518/621 compliance, integrated Python version management, lockfile (`uv.lock`).
  - Poetry retains advantages for library publishing workflows but is heavier for application projects.
- Sources checked (2026-05-05):
  - https://scopir.com/posts/best-python-package-managers-2026/
  - https://docs.bswen.com/blog/2026-02-12-uv-vs-poetry/
  - https://www.danilchenko.dev/posts/uv-vs-pip-vs-poetry/
- Gotchas:
  - `uv` is rapidly evolving; pin a uv version in CI to keep builds reproducible.
- v1 recommendation: `uv` as the project tool. `pyproject.toml` with PEP 621 metadata, `uv.lock` checked in.

### HTML parser

- Current state:
  - Performance order: selectolax (fastest, C-based, ~30x BeautifulSoup) > lxml > BeautifulSoup.
  - BeautifulSoup is most forgiving for malformed HTML, easiest API.
  - Both selectolax and lxml are first-class for the scraping volumes Fleet Tracker will operate at.
- Sources checked (2026-05-05):
  - https://medium.com/@yahyamrafe202/in-depth-comparison-of-web-scraping-parsers-lxml-beautifulsoup-and-selectolax-4f268ddea8df
  - https://webscraping.fyi/lib/compare/python-beautifulsoup-vs-python-selectolax/
- Gotchas:
  - Airfleets.net HTML is older and occasionally malformed; selectolax may choke where BeautifulSoup recovers.
- v1 recommendation: BeautifulSoup as default for collectors (Fleet Tracker is not parser-bound at v1 volume), with selectolax as a per-collector swap if a specific source proves slow. Document the choice so the upgrade path is obvious.

### Web map library

- Current state:
  - Brief commits to server-rendered static SVG arcs in v1, no Leaflet or MapLibre.
  - Python options for great-circle SVG: `gcmap` (specialised, draws great-circle arcs from coordinate pairs), `py-staticmaps` (full static maps with geodesic-line support, requires basemap tiles), `drawsvg` (low-level SVG generation), `cartopy` (heavyweight, scientific).
- Sources checked (2026-05-05):
  - https://github.com/paulgb/gcmap
  - https://github.com/flopp/py-staticmaps
  - https://pypi.org/project/drawsvg/
- Gotchas:
  - `py-staticmaps` defaults to OpenStreetMap tiles, which carry attribution and rate-limit obligations. We don't want a basemap if we are doing pure SVG arcs over a coastline outline.
  - `gcmap` raster outputs by default (PIL), so for SVG output we'd combine it with `drawsvg` or hand-rolled SVG.
- v1 recommendation: Hand-roll the SVG output, using a great-circle arc helper (port the relevant math from `gcmap` or `spherical_geometry`) and a static world coastline (Natural Earth simplified). This keeps the bundle small, attribution-free, and visually distinctive — aligned with the brief's stated rationale for static SVG.

---

## H. Retrofit integration prep

Per the brief, the retrofit tracker repo is unavailable, the strategy is to copy the desktop snapshot into Fleet Tracker as `src/fleet_tracker/classify/retrofit.py`. Phase 0 only verifies internal consistency of the snapshot.

### Snapshot consistency check

- Files reviewed: `~/Desktop/files/model.py`, `~/Desktop/files/test_model.py`, `~/Desktop/files/STRUCTURE.md`, `~/Desktop/files/README.md`.
- `model.py` exports:
  - Enums: `CabinState` (ORIGINAL, RETROFIT, IN_PROGRESS, UNKNOWN), `ObservationSource` (PLANESPOTTERS, AIRLINE_PRESS, SEATMAP, HANGAR_ROUTING, MANUAL), `StateSignal` (ORIGINAL, RETROFIT, IN_HANGAR).
  - Dataclasses (frozen): `Aircraft`, `Observation`.
  - Functions: `classify`, `install_rate`, `project_completion`.
  - Constants: `HIGH_CONFIDENCE`, `RETROFIT_FRESHNESS`, `HANGAR_DWELL_FOR_LIKELY`, `STALE_AFTER`.
- `test_model.py` imports `from src.model import (Aircraft, Observation, ObservationSource, StateSignal, CabinState, classify, install_rate, project_completion,)` — every imported symbol is exported. Internal consistency is confirmed.
- The five test functions cover: empty observation list (UNKNOWN), recent high-confidence retrofit (RETROFIT), aged retrofit signal falling through to UNKNOWN, hangar dwell with two recent IN_HANGAR observations (IN_PROGRESS), and `install_rate` + `project_completion` arithmetic.
- `STRUCTURE.md` description of the data model lines up with `model.py`. The dashboard ASCII in `README.md` references "18 / 167" tails for AC retrofit scope, matching the retrofit tracker's own scope definition.

### Adaptations Fleet Tracker will need

- Import path: tests in Fleet Tracker will import from `fleet_tracker.classify.retrofit`, not `src.model`.
- `ObservationSource` enum likely needs more values to cover Fleet Tracker's broader signal coverage. Candidates to consider during Phase 1:
  - `OPENSKY_LIVE` for live position observations
  - `AIRFLEETS` for ownership data
  - `AEROLOPA` for seat map references
  - `WIKIPEDIA_FLEET` for reference seed data
- `StateSignal` is retrofit-specific (ORIGINAL, RETROFIT, IN_HANGAR). Fleet Tracker may want a parallel signal taxonomy for ownership state changes (`OWNED`, `LEASED_IN`, `LEASED_OUT`, `RETIRED`) and lifecycle events (`IN_SERVICE`, `STORED`, `WRITTEN_OFF`). Keep these in separate enums; do not overload `StateSignal`.
- `Aircraft` dataclass currently has `tail_number, airline, aircraft_type, sub_fleet, delivered`. Fleet Tracker's broader schema (per the brief) adds `msn`, `retired`, `current_state`, `last_confirmed_at`. Resolution: keep the retrofit module's `Aircraft` import for retrofit-specific code paths; define a richer `Aircraft` in Fleet Tracker's main model layer and convert at the boundary.

### Open questions

- None blocking. Phase 1 will finalise the enum extensions and the boundary between retrofit-internal types and Fleet Tracker types.

### v1 recommendation

- Copy the four desktop files into `src/fleet_tracker/classify/retrofit.py` (model code) and `tests/test_retrofit_classify.py` (tests, with import paths updated). Add the header comment from the brief noting the manual-sync arrangement. Add `ROADMAP.md` entry for "Convert retrofit module to editable install once fleet-retrofit-tracker is published."

---

## Summary of recommendations

| Topic | v1 recommendation |
|---|---|
| OpenSky Network | Authenticated, primary live flight source. Accept 1-hour history limit. |
| ADS-B Exchange | Skip in v1. ToS friction not worth it for a portfolio. |
| FlightAware AeroAPI | Do not use for live data on the public dashboard. Optional dev-time reference lookups only. |
| Schedule data | Derive from observed flights, not from OAG/Cirium. Defer to v2. |
| Planespotters photos | Primary link-out for media. Never re-host. |
| JetPhotos | Skip in v1. Possible v2 fallback. |
| Airliners.net | Skip. |
| airfleets.net ownership | Primary ownership source. |
| ch-aviation | Skip in v1. Note as v2 upgrade. |
| Planespotters fleet pages | Secondary ownership source, manual review on disagreement. |
| AeroLOPA | Primary seat-map link-out per sub-fleet. |
| SeatGuru | Dead. Do not use. |
| Booking-site seat maps | Defer; stub the collector. |
| Flightradar24 | Defer hangar tracking to v1.5. Stub the collector. |
| AC mainline reference | Hand-curate from Wikipedia + airfleets, 5–10 seed tails for v1. |
| DL mainline reference | Same approach. |
| Astro | Plan for 5.17 in Phase 4; re-evaluate v6 stable before starting frontend work. |
| DuckDB partitioning | Hive layout `airline/year/month`, with caveat to revisit if file counts balloon. |
| Python packaging | uv. |
| HTML parser | BeautifulSoup default, selectolax per-collector swap if needed. |
| Web map | Hand-rolled SVG with great-circle arc helper, no basemap tiles. |
| Retrofit module | Copy from desktop snapshot to `src/fleet_tracker/classify/retrofit.py`. |

## Open questions for Yumo

1. Is a Trino/MinIO research-tier application to OpenSky realistic? It would unlock historical backfill and pull v2 forward.
2. Is the AC retrofit-scope figure of 167 (vs. mainline 216) authoritative? Phase 1's reconciliation depends on this.
3. Worth a polite contact-form ask to AeroLOPA confirming link-out for a portfolio dashboard is acceptable?
4. Is the FlightAware Standard License Agreement compatible with re-displaying cached data fields on a public dashboard? A skim of the PDF would resolve this before Phase 1 finalises any AeroAPI assumptions.
5. Should the v1 schedule for the Astro frontend wait for v6 stable, or proceed on 5.17?

---

## Phase status

Phase 0 complete. Stopping here per the brief's stop gates. Awaiting Yumo review before starting Phase 1 (DESIGN.md).
