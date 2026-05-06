# Fleet Tracker – Architecture Design

Date: 2026-05-05
Predecessor: docs/RESEARCH.md (Phase 0)
Status: Phase 1 deliverable, awaiting Yumo review before Phase 2.

This document pins down the architecture decisions Phase 0 surfaced. It commits where the brief asks for commitment and flags the few places that warrant a Phase 2 confirmation.

---

## 1. Flight history storage

### Decision

Hybrid path, three milestones, with the migration trigger spelled out:

| Phase | Behavior | Trigger to advance |
|---|---|---|
| **v1** | On-demand fetch from OpenSky per tail, 24-hour file cache, route map renders from cache | Active in-scope tail count exceeds 20, or on-demand calls hit OpenSky's per-account credit ceiling more than once per week |
| **v1.5** | Nightly GitHub Actions job pulls *new* flights for every in-scope tail, appended to per-tail Parquet history | Two-plus airlines actively tracked, or seed roster grows past 50 tails total |
| **v2** | Historical backfill (deferred indefinitely; revisit only if Trino access is granted) | Out of scope for this engagement; ROADMAP entry only |

Per Yumo's Phase 0 review, Trino/MinIO is not pursued. The "History since collection start" framing is the honest, shippable answer for v1 and v1.5 alike.

### Storage layout

Two layers: a transient cache and a durable Parquet archive.

```
data/
├── cache/
│   └── flights/
│       └── {tail_number}_{YYYYMMDD}.json     # gitignored; 24h TTL, lazy eviction
├── flights/
│   ├── airline=ac/
│   │   ├── year=2026/
│   │   │   ├── month=05/
│   │   │   │   └── flights.parquet
│   │   │   └── month=06/
│   │   │       └── flights.parquet
│   │   └── year=2027/
│   │       └── month=01/
│   │           └── flights.parquet
│   └── airline=dl/
│       └── ...
└── fleet.duckdb                              # gitignored; rebuilt from Parquet + reference CSVs
```

- Hive partitioning by `airline`, `year`, `month`. Per Yumo's Phase 0 review, this is a commit, not a defer.
- Partition values live in **directory names**, not filenames. (An earlier draft of this DESIGN had `month=05.parquet` as a filename pattern; that does not work with DuckDB's `hive_partitioning = true`, which extracts partition values from directory components only. Caught at CHECKPOINT 1 during Phase 3 scaffolding and corrected here.)
- At expected v1.5 volume (AC + DL combined, roughly 2.2M flights per year), monthly partitions land near 90k rows each. Healthy for both DuckDB writes and predicate-pushdown reads.
- Append-only. Flights are immutable observations; corrections happen by inserting a new observation, not by editing.
- v1.5 nightly writes one Parquet file per month directory per run; on second-run-in-same-month we either append a sibling file (`flights.parquet`, `flights_001.parquet`, ...) or overwrite the existing one. Collision handling is deferred to the first nightly observation; the read path glob (`month=*/*.parquet`) tolerates either.

### Cache invalidation rules

- **TTL governed by filename, not mtime.** Today's UTC date is compared to the `YYYYMMDD` in the filename. mtime is ignored. (Filename and mtime can disagree across midnight: a fetch at 23:55 UTC writes a file with yesterday's filename and today's mtime; a request at 00:05 UTC the next day would see them disagree. Filename is the single source of truth.)
- **Eviction**: lazy. The collector compares the filename date to today's UTC date on read; if they differ, the file is treated as stale and overwritten by the next fetch in the same call.
- **Key**: `{tail_number}_{YYYYMMDD}.json`. The `YYYYMMDD` is the UTC calendar day the data was fetched.
- **Read path**: cache hit (filename date == today's UTC) returns immediately. Cache miss triggers an OpenSky fetch, writes the cache file with today's filename, and returns the response.
- **Write to durable archive**: only the v1.5 nightly job writes to `data/flights/`. The v1 cache layer never writes Parquet.

### Migration trigger from v1 to v1.5

Two concrete signals; either advances the system to v1.5:

1. The `data/reference/{airline}-mainline.csv` files grow past 20 tails of active tracking each (i.e., the dashboard or notebooks ask for these tails routinely).
2. The OpenSky daily credit ledger hits its ceiling more than once per week.

(An earlier draft also tracked cache-hit-rate as a third trigger. Cut: a low cache-hit rate is a downstream symptom of (1) and (2), not an independent signal, and acting on it risks reacting to noise.)

### Open design tension acknowledged

OpenSky's 1-hour history window is the structural constraint. v1 starts with no history; the first observation captured is `t=0` for that tail's route map. The dashboard surface (per-tail page) must say so honestly. See §4 for the UI commitment.

---

## 2. Ownership classification

### Decision

Two-source consensus with manual tie-break, recency-weighted, with explicit confidence per source.

### Sources and base confidence

| Source | Base confidence | Role | Refresh cadence |
|---|---|---|---|
| airfleets.net | 0.80 | Primary | Weekly per tail |
| Planespotters fleet pages | 0.75 | Secondary | Weekly per tail |
| OpenSky Network metadata (`/api/metadata/aircraft/icao/{icao24}`) | 0.70 | Per-tail cross-check | Per-tail on slice run |
| Wikipedia airline fleet articles | 0.65 | Type-level cross-check | Daily per airline (cached) |
| Airline press releases (tail-specific facts) | 1.00 | Confirmatory (when available) | Event-driven |
| Manual review (Yumo) | 0.95 | Tie-break | Triggered by REVIEW_REQUIRED queue |

**Why Wikipedia ranks below OpenSky at 0.65**: Wikipedia airline-fleet articles list aircraft at the *type* level only (e.g. "Air Canada operates 42 A220-300s with 12J/125Y"), not per-tail. Observations emitted by the `wikipedia_fleet` collector are type-level confirmations attached to seed-CSV tails by aircraft_type match: "per Wikipedia, this airline operates this type." That is a weaker signal than OpenSky's per-icao24 metadata for three reasons: it is community-edited rather than a declarative airline source; it has no per-tail granularity; and tail-level changes (sub-fleet transfers, retirements) typically lag the airline's actual fleet by weeks-to-months. Wikipedia stays in the source mix because it is genuinely ToS-clean (CC-BY-SA-4.0 article text, no anti-bot blocks) and surfaces type-vs-airline contradictions cheaply. It is not a substitute for the eventual airfleets/Planespotters per-tail collectors.

**Why press releases score 1.00**: Tail-level facts in airline communications are declarative commitments. When AC announces "C-FBOM was the first A220 retrofitted under the new program," the airline is on the record about a specific aircraft's status. That is qualitatively different from third-party scraping (airfleets, Planespotters), which interprets and re-publishes airline-supplied data through its own editorial layer. Press observations naming a specific tail are treated as ground truth and override conflicting third-party reports without going through the REVIEW_REQUIRED flow. (Manual review by Yumo stays at 0.95: a human can still misread a source.)

### Resolution rule (run per tail, deterministic)

```
def resolve_current_owner(tail) -> OwnershipState:
    primary = latest_airfleets_observation(tail)
    secondary = latest_planespotters_observation(tail)
    press = latest_press_observation(tail)
    manual = latest_manual_observation(tail)

    candidates = [obs for obs in (manual, press, primary, secondary) if obs is not None]
    candidates = [obs for obs in candidates if (now - obs.observed_at) <= STALE_AFTER]

    if not candidates:
        return UNKNOWN

    # Manual or press always win when present and fresh.
    for obs in candidates:
        if obs.source in {MANUAL, AIRLINE_PRESS}:
            return state_from(obs)

    # Otherwise primary wins unless it's materially older than secondary.
    if primary and secondary:
        if primary.owner_entity == secondary.owner_entity \
           and primary.owner_type == secondary.owner_type:
            return state_from(primary)
        # Disagreement: prefer the more recent unless they're within 14 days.
        if abs(primary.observed_at - secondary.observed_at) <= timedelta(days=14):
            flag_for_review(tail, primary, secondary)
            return REVIEW_REQUIRED
        return state_from(max(primary, secondary, key=lambda o: o.observed_at))

    return state_from(primary or secondary)
```

### Confidence scoring on the dashboard

The per-tail UI shows the source of the current ownership state and its confidence. A REVIEW_REQUIRED tail shows `ownership: pending review` with the conflicting sources visible. Conservative classification per the retrofit tracker convention: false positives erode credibility faster than coverage gaps.

### Staleness handling

- `STALE_AFTER = timedelta(days=180)`. Matches the retrofit module's constant for consistency.
- Tails with no observation in 180 days surface as `ownership: UNKNOWN` with the most recent stale observation displayed as historical.
- The nightly job (v1.5) refreshes any tail with last-observation older than 30 days, prioritising stale tails to keep the median freshness inside one month.

### Acquisition tracking

`ownership_history` carries two extra columns for context on how each tail entered the operator's fleet:

- `acquisition_type` (TEXT, nullable, `AcquisitionType` enum): one of `new_delivery` (direct from manufacturer), `secondhand` (acquired from another operator), `lease` (leased in; the lease sub-type lives in `owner_type` via `LEASED_IN`).
- `acquisition_context` (TEXT, nullable): free-text annotation for narrative context, e.g. `"Acquired via Delta-Northwest merger, October 2008"` or `"Sale-leaseback through AerCap, March 2018"`.

**Population rule**: these columns are populated **only on the first ownership row for a tail at a given operator** — the row whose `effective_from` matches the operator's acquisition date. Subsequent ownership rows for the same tail at the same operator (lease renewal, ownership-type change) leave both columns NULL. The dashboard reads the earliest row for the operator to display acquisition context.

**Why mergers are SECONDHAND, not a separate enum value**: at the legal level, mergers transfer aircraft as secondhand acquisitions; the corporate event is interesting context but not a distinct acquisition mechanism. Treating "via merger" as a sibling of "secondhand" creates classification ambiguity (was it secondhand-via-merger? secondhand-not-via-merger?) that doesn't map cleanly to the underlying ownership transfer. The free-text `acquisition_context` captures the merger narrative without forking the type.

**What this scope deliberately excludes**: purchase prices, lessor financial terms, aircraft asset values. Those are commercial-grade data points (ch-aviation / Cirium charge for them), and even public mentions of them are speculative or leaked. Fleet Tracker stays narrative-level on acquisitions.

---

## 3. Retrofit module integration

### What gets copied

Per the brief's strategy, the desktop snapshot is copied directly into Fleet Tracker.

| Source | Destination | Notes |
|---|---|---|
| `~/Desktop/files/model.py` | `src/fleet_tracker/classify/retrofit.py` | Header comment per the brief: synced from desktop snapshot 2026-05-05, manually maintained until `fleet-retrofit-tracker` ships as installable package |
| `~/Desktop/files/test_model.py` | `tests/test_retrofit_classify.py` | Import paths updated from `src.model` to `fleet_tracker.classify.retrofit` |

The copied module retains its own surface: `Aircraft`, `Observation`, `ObservationSource`, `StateSignal`, `CabinState`, `classify`, `install_rate`, `project_completion`, plus the four constants (`HIGH_CONFIDENCE`, `RETROFIT_FRESHNESS`, `HANGAR_DWELL_FOR_LIKELY`, `STALE_AFTER`).

### Adaptation strategy: untouched module, parallel types

Per Yumo's Phase 1 amendment:

- The retrofit module is **left untouched**. Its enums, dataclasses, and functions match the desktop snapshot byte-for-byte, with only the import statements modified.
- Fleet Tracker defines **parallel types** in `src/fleet_tracker/model.py`:
  - `FleetTrackerSource` enum (extends coverage to OPENSKY_LIVE, AIRFLEETS, AEROLOPA, WIKIPEDIA_FLEET, in addition to PLANESPOTTERS, AIRLINE_PRESS, SEATMAP, HANGAR_ROUTING, MANUAL).
  - `OwnershipSignal` enum: OWNED, LEASED_IN, LEASED_OUT, RETIRED.
  - `LifecycleSignal` enum: IN_SERVICE, STORED, WRITTEN_OFF.
  - `Aircraft` dataclass (richer): `tail_number, airline, aircraft_type, msn, sub_fleet, delivered, retired, current_state, last_confirmed_at`.
- A **boundary converter** lives in `src/fleet_tracker/classify/__init__.py`:

  ```python
  def to_retrofit_aircraft(ac: model.Aircraft) -> retrofit.Aircraft:
      return retrofit.Aircraft(
          tail_number=ac.tail_number,
          airline=ac.airline,
          aircraft_type=ac.aircraft_type,
          sub_fleet=ac.sub_fleet or "",  # retrofit module declares str, not Optional
          delivered=ac.delivered,
      )
  ```

  The converter discards `msn`, `retired`, `current_state`, `last_confirmed_at`. The retrofit module does not need them; they would be dead weight inside that module. The `or ""` substitution handles tails where the airline-internal sub-fleet code isn't yet known; see `test_to_retrofit_aircraft_handles_missing_sub_fleet`.

  **Retired short-circuit**: callers of the retrofit module must handle `retired` themselves before invoking it. The convention lives in `compute_retrofit_state` (see §6 for code): if `aircraft.retired is not None`, return `(CabinState.UNKNOWN, None)` immediately without calling `retrofit.classify`. The retrofit module's classifier has no concept of retirement and will happily classify a stale observation against a long-retired tail; the short-circuit is the boundary's responsibility, not the module's. This keeps the retrofit module pristine and pushable upstream once `fleet-retrofit-tracker` ships.

### Why parallel types over enum extension

Three reasons, in priority order:

1. **The retrofit module ships as a separate project soon.** Once `fleet-retrofit-tracker` is published, Fleet Tracker swaps the copied file for an editable install. If we modified the enums in-place, that future swap requires a fork or upstream PRs. Parallel types keep the module pristine and the swap one-line.
2. **Different signal taxonomies for different concerns.** `StateSignal` describes cabin retrofit observations. Ownership and lifecycle are different domains; conflating them invites bugs (a retrofit filter accidentally matching an ownership signal).
3. **Conversion at boundary is cheap.** The converter is six lines. The cost of clarity is low.

### Technical debt entry

`ROADMAP.md` will include, under "Future cleanup":

- Convert retrofit module to editable install once `fleet-retrofit-tracker` is published. Drop `src/fleet_tracker/classify/retrofit.py` and replace with `pip install fleet-retrofit-tracker` in pyproject. Boundary converter stays; it's the right shape regardless.

---

## 4. Dashboard IA

Five views in v1. Static-rendered Astro pages, no client-side routing.

### Landing page (`/`)

```
┌──────────────────────────────────────────────────────────────┐
│  FLEET TRACKER                                               │
│  Tracking current and historical fleets of major airlines.   │
│                                                              │
│  ┌──────────────────────┐  ┌──────────────────────┐          │
│  │  Air Canada          │  │  Delta Air Lines     │          │
│  │  ───────────         │  │  ───────────         │          │
│  │  Mainline:    216    │  │  Mainline:    987    │          │
│  │  Tracked:      10    │  │  Tracked:       8    │          │
│  │  Retrofit:    18/167 │  │  Retrofit:    142/?? │          │
│  │  →                   │  │  →                   │          │
│  └──────────────────────┘  └──────────────────────┘          │
│                                                              │
│  Recently observed                                           │
│    C-FBOM   AC  A220-300  YUL→YYZ   2026-05-05 14:22        │
│    C-FXKQ   AC  A321-200  YOW→YYC   2026-05-05 13:48        │
│    N512DN   DL  A350-900  ATL→NRT   2026-05-05 11:05        │
│                                                              │
│  Methodology: docs/data-sources.md                           │
└──────────────────────────────────────────────────────────────┘
```

Numbers come from the aircraft table aggregate. "Tracked" reflects what's live in `data/reference/`. "Retrofit" comes from the retrofit module's `install_rate` rollup.

### Per-airline page (`/airline/{ac|dl}`)

This is where Yumo's three-number requirement lives.

```
┌──────────────────────────────────────────────────────────────┐
│  AIR CANADA                                                  │
│                                                              │
│  Fleet                                                       │
│    Mainline fleet:                216 aircraft               │
│    In retrofit program scope:     167 aircraft               │
│    Retrofitted to date:            18 aircraft               │
│                                                              │
│    The retrofit program covers a subset of mainline; types   │
│    not in the announced program (notably 777-200LR being     │
│    aged out, and certain older sub-variants) are excluded    │
│    from the 167 figure but still appear in fleet listings    │
│    below.                                                    │
│                                                              │
│  Composition (mainline)                                      │
│    A220-300       40   ████████████████████                  │
│    A321ceo        24   ████████████                          │
│    A330-300       14   ███████                               │
│    787-8           8   ████                                  │
│    787-9          32   ████████████████                      │
│    777-200LR       6   ███           [out of retrofit scope] │
│    777-300ER      19   █████████                             │
│    [...]                                                     │
│                                                              │
│  Tails (10 currently tracked)                                │
│    C-FBOM   A220-300   33H   delivered 2020-06   →           │
│    C-GTSI   787-9      77B   delivered 2018-04   →           │
│    [...]                                                     │
│                                                              │
│  Retrofit progress (program scope only)                      │
│    [retrofit module rollup chart, copied from retrofit       │
│     tracker conventions]                                     │
└──────────────────────────────────────────────────────────────┘
```

The "subset of mainline" callout is the explicit relationship Yumo asked for. It appears once on the per-airline page and is referenced (not repeated) elsewhere.

### Per-tail page (`/tail/{registration}`)

Information priority: identity → state → ownership → flight history → media → specs.

```
┌──────────────────────────────────────────────────────────────┐
│  C-FBOM                                                      │
│  Air Canada · Airbus A220-300 · sub-fleet 33H                │
│  MSN 55088 · delivered 2020-06-12                            │
│                                                              │
│  Current state                                               │
│    Cabin:          Original (last confirmed 2026-04-29)      │
│    Ownership:      Owned (Air Canada, since 2020-06)         │
│    Lifecycle:      In service                                │
│                                                              │
│  Ownership history                                           │
│    Acquired:  new from Airbus (June 2020)                    │
│    2020-06 to present   Owned · Air Canada                   │
│      Source: airfleets.net (fetched 2026-05-04, conf 0.80)   │
│      Source: planespotters.net (fetched 2026-05-04, conf 0.75)│
│                                                              │
│  Flight history (through yesterday: 2026-05-04)              │
│                                                              │
│    [SVG great-circle arc map, viewBox 0 0 800 400]           │
│                                                              │
│    Recent flights                                            │
│      2026-05-05  YUL → YYZ  AC456  off 14:22                 │
│      2026-05-05  YYZ → YUL  AC457  off 09:11                 │
│      [...]                                                   │
│                                                              │
│  Media                                                       │
│    Exterior  →  planespotters.net/photo/12345 (© J. Smith)   │
│    Interior  →  planespotters.net/photo/12348 (© M. Tran)    │
│                                                              │
│  Specs                                                       │
│    Seats:     12J / 125Y                                     │
│    Engine:    PW1521G                                        │
│    Seat map:  aerolopa.com/ac/a220-300-33h →                 │
└──────────────────────────────────────────────────────────────┘
```

The "through yesterday" annotation is the honest UI commitment for OpenSky's overnight-batch lag (the `/flights/aircraft` endpoint only returns flights from the previous day or earlier; same-day flights are not yet available). Per the CHECKPOINT 2 finding, the actual constraint is a 1-day lag, not a 1-hour window — the previous "since collection start" framing was based on the misunderstood `/states/all` 1-hour limit.

### Per-type view (`/type/{slug}`)

```
┌──────────────────────────────────────────────────────────────┐
│  AIRBUS A220-300                                             │
│  Operators tracked: Air Canada · Delta Air Lines             │
│                                                              │
│  By airline                                                  │
│    Air Canada     40    avg age 4.1y    [link to AC tails]   │
│    Delta          45    avg age 3.8y    [link to DL tails]   │
│                                                              │
│  Sub-fleet variants                                          │
│    AC 33H          40   12J / 125Y                           │
│    DL 35Y          45    0J / 132Y                           │
│                                                              │
│  Retrofit status across operators                            │
│    AC 33H          6 of 33 (18%)                             │
│    DL 35Y          (not in tracked retrofit program)         │
└──────────────────────────────────────────────────────────────┘
```

### Route map view (`/tail/{registration}#map`)

Embedded inside the per-tail page (anchor link, not a separate page in v1). The map is a server-rendered SVG. Detail in §5.

---

## 5. Map view

### Commitment

v1 uses **server-rendered static SVG arcs**. Not Leaflet. Not MapLibre. Not Mapbox GL. No JavaScript map library at all.

Per-tail pages embed an inline `<svg>` element generated at build time. The SVG contains:

- A simplified world coastline as a background path (Natural Earth low-resolution, served as a one-time static asset).
- One great-circle arc per flight in the tail's history.
- Origin and destination markers.
- Optional shading for arc density (older flights fade).

### Rationale

1. **Astro is static-first.** Adding a JS map library negates that posture and inflates bundle size by hundreds of kilobytes for a feature that does not need interactivity.
2. **Distinctive look.** Most fleet dashboards use the same Leaflet-with-OSM aesthetic. A pure SVG arc map reads as deliberate craft, which is the right vibe for a portfolio piece.
3. **No tile-provider obligations.** OSM tile use carries attribution and rate-limit constraints. We avoid them entirely.
4. **No runtime cost.** Arc geometry is computed once at build time per tail; the dashboard ships static HTML.

### Implementation sketch

- Great-circle math: port from `gcmap` or use `spherical_geometry`. Computes latitude-longitude waypoints along the arc; we then project to viewport coordinates.
- Projection: **Winkel-tripel**. Equirectangular distorts transpolar AC routes (YYZ-DEL, YVR-DEL) badly enough to mislead a reader; at least one in-scope widebody flies them, so the projection choice is load-bearing for accuracy. Winkel-tripel is the standard "looks right at a glance" projection (it is what National Geographic uses for world maps) and the additional math is roughly 30 lines beyond equirectangular: well within v1's complexity budget. Adopting it now avoids a refactor later.
- Output: a Python helper in `src/fleet_tracker/publish.py` (or a sibling module) that consumes a list of (origin, destination) pairs and returns SVG string.
- Coastline: pre-processed Natural Earth `ne_110m_coastline` simplified to ≤2k vertices, projected through Winkel-tripel once at build time and embedded as a single SVG path per page (not per arc).
- Bundle target: per-tail SVG well under 50 KB even for a tail with 200 flights.

### What we are deferring (deliberately)

- Interactive maps: deferred to v2 only if a real user need surfaces. "Real user need" means feedback from someone actually using the site, not a guess.
- Multi-airline aggregate maps: deferred to v2 alongside any interactive treatment.
- Heat maps of route density: deferred to v2.

---

## 6. Schema

Final v1 schema. DuckDB tables for everything except flights, which is Parquet (read into DuckDB via Hive partitioning glob).

### Enums (Python `StrEnum`, mirrored to TEXT in DuckDB)

```python
# src/fleet_tracker/model.py

class FleetTrackerSource(StrEnum):
    PLANESPOTTERS = "planespotters"
    AIRLINE_PRESS = "airline_press"
    SEATMAP = "seatmap"
    HANGAR_ROUTING = "hangar_routing"
    MANUAL = "manual"
    OPENSKY_LIVE = "opensky_live"
    AIRFLEETS = "airfleets"
    AEROLOPA = "aerolopa"
    WIKIPEDIA_FLEET = "wikipedia_fleet"

class OwnershipSignal(StrEnum):
    OWNED = "owned"
    LEASED_IN = "leased_in"
    LEASED_OUT = "leased_out"
    RETIRED = "retired"

class LifecycleSignal(StrEnum):
    IN_SERVICE = "in_service"
    STORED = "stored"
    WRITTEN_OFF = "written_off"

class AcquisitionType(StrEnum):
    NEW_DELIVERY = "new_delivery"
    SECONDHAND = "secondhand"
    LEASE = "lease"
```

The retrofit module's `ObservationSource`, `StateSignal`, `CabinState` stay separate, untouched, used only inside the retrofit code path.

### `aircraft`

```sql
CREATE TABLE aircraft (
    tail_number       TEXT PRIMARY KEY,
    airline           TEXT NOT NULL,
    aircraft_type     TEXT NOT NULL,
    msn               TEXT,
    sub_fleet         TEXT,
    delivered         TIMESTAMP,
    retired           TIMESTAMP,
    current_state     TEXT,            -- denormalised cache, computed
    last_confirmed_at TIMESTAMP
);
CREATE INDEX idx_aircraft_airline_state ON aircraft (airline, current_state);
```

`current_state` is denormalised for cheap landing-page reads; rebuilt from observations whenever the aggregate job runs.

### `ownership_history`

```sql
CREATE TABLE ownership_history (
    tail_number          TEXT NOT NULL,
    effective_from       TIMESTAMP NOT NULL,
    effective_to         TIMESTAMP,             -- NULL means current
    owner_type           TEXT NOT NULL,         -- OwnershipSignal value
    owner_entity         TEXT NOT NULL,         -- 'Air Canada', 'AerCap', etc.
    source_url           TEXT NOT NULL,
    confidence           DOUBLE NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    -- acquisition_* are populated ONLY on the first ownership row for a tail
    -- at each operator (the row whose effective_from matches the operator's
    -- acquisition date). Subsequent rows leave both null. See §2 for rules.
    acquisition_type     TEXT,                  -- AcquisitionType value
    acquisition_context  TEXT,                  -- free-text annotation, nullable
    PRIMARY KEY (tail_number, effective_from)
);
-- DuckDB does not support partial indexes (NotImplementedException as of
-- 1.x). The intended spec was a partial index `WHERE effective_to IS NULL`
-- to make "current owner" lookups predicate-pushdown cheap; instead we use
-- a non-partial tail_number index and let the query planner filter on
-- effective_to at scan time. Revisit if DuckDB lands partial-index support.
CREATE INDEX idx_ownership_tail ON ownership_history (tail_number);
```

### `flights` (Parquet, partitioned, queried via DuckDB)

Logical schema (Parquet does not support constraints, but DuckDB will enforce types):

| column | type | nullable | notes |
|---|---|---|---|
| flight_id | TEXT | no | composite from source: `opensky:{icao24}:{firstSeen}` |
| tail_number | TEXT | no | join key to `aircraft` |
| flight_number | TEXT | yes | best-effort parse from callsign |
| origin_icao | TEXT | yes | 4-letter ICAO airport code as returned by OpenSky (e.g. CYUL). IATA conversion deferred to display time in Phase 4. |
| destination_icao | TEXT | yes | same |
| scheduled_off | TIMESTAMP | yes | null when source has none |
| actual_off | TIMESTAMP | no | OpenSky `firstSeen` |
| actual_on | TIMESTAMP | yes | null while in flight |
| status | TEXT | no | `completed` \| `in_flight` \| `cancelled` |
| source | TEXT | no | FleetTrackerSource value |
| ingested_at | TIMESTAMP | no | when this row was written |

Hive partition keys: `airline`, `year`, `month` (derived from `actual_off`). Append-only; corrections by inserting a new row, not updating.

DuckDB read pattern:

```sql
SELECT * FROM read_parquet(
    'data/flights/airline=ac/year=*/month=*/*.parquet',
    hive_partitioning = true
);
```

### `observations`

```sql
CREATE TABLE observations (
    observation_id  INTEGER PRIMARY KEY,           -- auto-increment via sequence
    tail_number     TEXT NOT NULL,
    observed_at     TIMESTAMP NOT NULL,
    source          TEXT NOT NULL,                  -- FleetTrackerSource value
    source_url      TEXT NOT NULL,
    signal_kind     TEXT NOT NULL,                  -- 'cabin' | 'ownership' | 'lifecycle' | 'flight'
    signal_value    TEXT NOT NULL,                  -- e.g. 'owned', 'in_service', 'retrofit'
    confidence      DOUBLE NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    notes           TEXT
);
CREATE INDEX idx_obs_tail_time ON observations (tail_number, observed_at DESC);
CREATE INDEX idx_obs_kind_time ON observations (signal_kind, observed_at DESC);
```

`signal_kind` plus `signal_value` lets one table carry observations from every domain (cabin, ownership, lifecycle, flight events) without joins. The retrofit module reads only `signal_kind = 'cabin'` rows after conversion.

### `media`

```sql
CREATE TABLE media (
    tail_number   TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('exterior', 'interior')),
    image_url     TEXT NOT NULL,
    attribution   TEXT NOT NULL,                    -- e.g. '© John Smith / planespotters.net'
    captured_at   TIMESTAMP,                        -- photographer-supplied date
    ingested_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (tail_number, kind)
);
```

v1 stores one current image per kind per tail. v2 may store history. Never re-host the binary; `image_url` always points to the source platform.

### `specs`

```sql
CREATE TABLE specs (
    tail_number              TEXT PRIMARY KEY,
    seats_first              INTEGER,
    seats_business           INTEGER,
    seats_premium_economy    INTEGER,
    seats_economy            INTEGER,
    seat_map_url             TEXT,
    lopa_source              TEXT,                  -- 'aerolopa' | 'airline'
    engine_type              TEXT,
    delivered_config_notes   TEXT
);
```

### `retrofit_state` (computed view)

Not a table. Materialised on demand from observations + the retrofit module's `classify` function:

```python
def compute_retrofit_state(tail_number: str) -> tuple[CabinState, datetime | None]:
    aircraft_ft = load_aircraft(tail_number)

    # Retired short-circuit: the retrofit module has no concept of retirement.
    # A long-retired tail with a stale RETROFIT observation would otherwise
    # classify as RETROFIT forever. Boundary's responsibility, not the module's.
    if aircraft_ft.retired is not None:
        return CabinState.UNKNOWN, None

    aircraft_rt = to_retrofit_aircraft(aircraft_ft)
    obs_rows = duckdb.sql(
        "SELECT * FROM observations WHERE tail_number = ? AND signal_kind = 'cabin'",
        params=[tail_number],
    ).fetchall()
    obs = [to_retrofit_observation(row) for row in obs_rows]
    state = retrofit.classify(aircraft_rt, obs)
    last = max((o.observed_at for o in obs), default=None)
    return state, last
```

Cached on the `aircraft.current_state` column when it represents the cabin state; otherwise computed at render time. v1.5 will move this into a materialised view if read latency demands it.

---

## 7. AC fleet count reconciliation

Per Yumo's amendment, this section commits to the dashboard's display contract for the three numbers.

### The numbers

| Number | Meaning | Source |
|---|---|---|
| **216** | Air Canada mainline fleet, total active passenger aircraft | Wikipedia + airfleets, refreshed quarterly |
| **167** | Aircraft in scope of the announced retrofit program (April 2026) | Air Canada press release, fixed until program scope changes |
| **18** | Tails confirmed retrofitted to date | Computed from observations via retrofit module |

### Why 216 ≠ 167

The retrofit program (announced April 2026) excludes the following types from its 167-aircraft scope:

- **777-200LR (~6 aircraft)**: aging out, not getting the new cabin.
- **Certain older A321ceo sub-variants**: candidates for retirement before the program would reach them.
- **Some 787-8s** in their current configuration: scoping decision pending.
- **A350-1000 (incoming)**: already delivered with the new standard, counted separately.

The exact composition of the 49-aircraft gap will firm up over the program's life. v1 stores both numbers and shows the gap explicitly rather than hiding it behind a single percentage.

### Display contract

The per-airline page (Air Canada) MUST show all three numbers in the "Fleet" block (sketched in §4) with the relationship spelled out in plain prose. The retrofit progress chart shows percentages relative to 167 (the program scope), not 216 (the mainline fleet), and is labelled accordingly: "Retrofit progress (program scope only)."

The landing page card shows `Mainline: 216` and `Retrofit: 18/167` on separate lines so the two domains stay visually distinct.

### Why this matters

If the dashboard reported only "18 of 167 retrofitted" without the 216 context, a visitor familiar with AC's broader fleet would notice the discrepancy and assume an error. If it reported only "18 of 216", it would understate progress and contradict AC's own program targets. Showing both, with the gap explained, is the only honest framing.

---

## 8. IN_PROGRESS state scope

### Decision

In v1, `CabinState.IN_PROGRESS` is **retrofit-specific**. It fires only from the retrofit module's hangar dwell logic (two or more `IN_HANGAR` observations within `HANGAR_DWELL_FOR_LIKELY` of each other, no later `ORIGINAL` sighting).

Fleet Tracker has **no general indicator** for "grounded for maintenance" or "out of service" in v1.

### What the lifecycle enum does and does not cover

`LifecycleSignal` covers durable lifecycle events: `IN_SERVICE`, `STORED`, `WRITTEN_OFF`. It does NOT cover:

- Routine hangar visits (C-checks, line maintenance)
- Short-term groundings (weather, AOG)
- Cabin retrofit hangar time (covered by `CabinState.IN_PROGRESS` exclusively)

### Rationale

Three reasons to keep the scope narrow:

1. **Hangar dwell tracking depends on Flightradar24 history**, which Phase 0 deferred to v1.5. Without that data, a general maintenance indicator would be unreliable.
2. **Conservative classification**: false positives (saying a tail is grounded when it just had a quiet day) cost more credibility than gaps.
3. **The retrofit module already does the right thing for its narrow case.** Generalising it now would either dilute it or duplicate it; neither is good.

### What a v1.5 future could look like

If Fleet Tracker grows a real maintenance-state need (e.g. a user wants to see "currently in hangar"), the path is:

- Introduce a `MaintenanceSignal` enum (`AT_BASE`, `AT_MRO`, `EXTENDED_DWELL`).
- Wire FR24 history (paid tier or accumulated OpenSky data) into the hangar collector.
- Add a `maintenance_state` column to `aircraft`, computed analogously to `current_state` for cabin.

This is a v2 conversation, not a v1 one.

---

## Open questions for Yumo

All Phase 1 open questions resolved by Yumo's review on 2026-05-05. See PLAN.md for any items still requiring a decision before Phase 3 starts.

### Resolution log (2026-05-05)

1. Boundary converter discards `msn`, `retired`, `current_state`, `last_confirmed_at` as proposed. Added `retired` short-circuit in `compute_retrofit_state` (§3, §6).
2. Per-tail page priority approved: identity → state → ownership → flight history → media → specs.
3. 5% null rate threshold for OpenSky `estDepartureAirport` / `estArrivalAirport` confirmed.
4. Ownership confidence base values approved with one change: press releases naming specific tails carry confidence 1.00, not 0.95 (§2).
5. Map projection: Winkel-tripel committed for v1 (§5). Equirectangular dropped.

---

## Phase status

Phase 1 complete. Stopping here per the brief's stop gates. Awaiting Yumo review before starting Phase 2 (PLAN.md).
