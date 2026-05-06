# Data sources

Each source Fleet Tracker reads from, what it provides, and the constraints that shape how it's used. v1 is OpenSky-only for live data; the rest are stubbed for Phase 4 per [docs/PLAN.md](PLAN.md).

For the broader landscape research that produced these decisions, see [docs/RESEARCH.md](RESEARCH.md).

## Sources at a glance

| Source | Role | Status | Refresh | Notes |
|---|---|---|---|---|
| OpenSky Network | Live flight history | **Active in v1** | On-demand + 24h cache (v1), nightly (v1.5) | Authenticated tier required. /flights/aircraft has 2-day window + overnight batch lag. |
| airfleets.net | Ownership / lessor primary | Phase 4 stub | Weekly per tail | Free public, scrape with identifiable UA, ≤1 req/sec. |
| Planespotters fleet pages | Ownership secondary, photo metadata | Phase 4 stub | Weekly per tail | Photo links only, never re-host images. |
| AeroLOPA | Seat maps | Phase 4 stub | Per sub-fleet | URL link-out per sub-fleet; no embed. |
| Airline press releases | High-confidence ownership / retrofit confirmations | Phase 4 stub | Event-driven | Tail-named facts carry confidence 1.00 (DESIGN §2). |
| Wikipedia airline fleet articles | Type-level ownership cross-check + reference roster seed | **Active in v1** (collector) + manual seeding | Daily per airline (cached); seed CSVs curated separately | CC-BY-SA-4.0; type-level only, base confidence 0.65 (DESIGN §2). |
| FlightAware AeroAPI | Live flights (alternative) | Skipped (v1 + v1.5) | n/a | $5/mo personal allowance does not cover public-dashboard redistribution. |
| ADS-B Exchange | Live flights (alternative) | Skipped (v1) | n/a | Commercial license required for public dashboards. |
| Flightradar24 | Hangar dwell tracking | Deferred to v1.5 | n/a | Paid tier; stub `hangar_tracker` collector exists. |
| ch-aviation | Lessor / asset data | Skipped (v1 + v1.5) | n/a | Subscription cost out of scope for portfolio project. |

## OpenSky Network (active in v1)

- **Endpoint used**: `GET /api/flights/aircraft` (authenticated)
- **Required parameters**: `icao24` (24-bit transponder address, lowercase hex), `begin` and `end` (Unix seconds).
- **Window cap**: 2 days between `begin` and `end`. Larger spans return HTTP 400.
- **Recency cap**: only flights from yesterday (UTC) or earlier. The endpoint is populated by an overnight batch job; same-day flights are not yet available. The dashboard's per-tail page surfaces this as `Flight history (through yesterday: YYYY-MM-DD)` per [DESIGN §4](DESIGN.md).
- **Rate limit**: shared daily credit pool (8000 credits/day for active feeders, smaller for non-feeder accounts). One `/flights/aircraft` call costs roughly 4 credits in current OpenSky pricing.
- **Auth**: HTTP Basic, credentials from `OPENSKY_USERNAME` / `OPENSKY_PASSWORD` env vars (loaded via `python-dotenv`).
- **Empty response semantics**: HTTP 404 means "no flights for this aircraft in the requested window" (treated as empty, not an error). HTTP 401 means bad credentials. Other 5xx responses bubble up.

The collector (`src/fleet_tracker/collectors/opensky.py`) caches each per-tail response for 24 hours by filename date; see [DESIGN §1](DESIGN.md) for the cache governance rules.

## icao24 lookups (manual in v1, automated in v1.5)

OpenSky's `/flights/aircraft` requires the 24-bit transponder address (e.g. `c01040`), not the registration (`C-FBOM`). v1 ships with `icao24=todo_lookup` placeholders in `data/reference/{airline}-mainline.csv`; the slice CLI accepts `--icao24 <hex>` directly to bypass the CSV lookup.

### Why web-based lookup is blocked

Public registration→icao24 lookup pages (Planespotters, FlightRadar24, kloth.net, OpenSky's own metadata endpoint, Transport Canada's CCARCS) all either return 403 to programmatic requests or are HTML form-driven without a JSON endpoint. The OpenSky Aircraft Database CSV exists but is gigabyte-scale; not practical for a per-tail lookup.

### Manual technique that works (used during v1 scaffolding)

OpenSky's public `/api/states/all` endpoint requires no auth and returns every aircraft currently transmitting. Grep for the airline's ICAO callsign prefix:

```bash
curl -sS "https://opensky-network.org/api/states/all" \
  | python3 -c "
import json, sys
for s in json.load(sys.stdin).get('states', []):
    icao24, callsign, country = s[0], (s[1] or '').strip(), s[2]
    if callsign.startswith('ACA') and country == 'Canada':
        print(f'{icao24}  {callsign}')
"
```

This returns rows like:

```
c01040  ACA9
c023aa  ACA42
c010f6  ACA123
```

Correlate the icao24 with the tail's known route or aircraft type (AC9 is normally the Toronto-Tokyo 787-9, etc.) to match it to a registration in your seed CSV. Repeat over a few snapshots across days to catch tails that only fly intermittently.

### Why this is not automated in v1

Reliable correlation requires a registration database (airfleets, Wikipedia, or a paid source like ch-aviation), and Fleet Tracker's v1 collectors for those sources are stubbed. v1.5 is the right place to build automated discovery: the nightly job already pulls from airfleets for ownership, so the same scrape pass can extract the icao24 mapping into a `data/reference/icao24-map.csv` that the collector consults transparently.

For v1, manual curation of 5-10 seed tails per airline is acceptable — that's roughly 15 minutes per airline of grepping `/states/all` snapshots and correlating against known routes.

## Wikipedia airline fleet articles (active in v1)

- **Pages used**: `https://en.wikipedia.org/wiki/{airline}_fleet` (e.g. `Air_Canada_fleet`, `Delta_Air_Lines_fleet`).
- **What gets parsed**: the *Current fleet* wikitable. Type-level: aircraft type, in-service count, orders, seat configuration (J/W/Y/total), and the free-text Notes column.
- **What does NOT exist on these pages**: per-tail registration tables. The user-facing impact: Wikipedia observations confirm "this airline operates this aircraft type", attached to seed-CSV tails by aircraft_type match. Per-tail ownership has to come from airfleets/Planespotters (deferred) or OpenSky metadata.
- **Confidence**: base 0.65, slightly below OpenSky's 0.70 (DESIGN §2). Lower because: community-edited rather than a declarative airline source; type-level only; tail-level changes lag by weeks-to-months.
- **Refresh / cache**: filename-date governance, mirrored from the OpenSky cache (DESIGN §1). One cached HTML per airline per UTC day in `data/cache/wikipedia/{airline}_fleet_{YYYYMMDD}.html`.
- **User-Agent**: `FleetTrackerBot/0.1 (...)`, identifiable per Wikipedia's bot policy.
- **Licence**: article text is CC-BY-SA-4.0. The captured fixture in `tests/fixtures/wikipedia_ac_fleet.html` carries an attribution comment in its header.
- **Multi-config types**: aircraft types with two cabin configs (e.g. AC's A321-200 with one fleet of 16J/180Y and another of 8W/176Y) appear as separate rows. The parser preserves them; aggregate by `aircraft_type` if you want a per-type rollup.

The collector lives at `src/fleet_tracker/collectors/wikipedia_fleet.py` and exposes `fetch_fleet_html(airline)`, `parse_current_fleet(html) -> list[FleetTypeRow]`, and `find_rows_for_type(rows, "A220-300")` for the seed-CSV match.

## Airfleets, Planespotters, AeroLOPA (Phase 4 stubs)

See [docs/RESEARCH.md](RESEARCH.md) topics B, C, D for the full source-by-source notes that produced the v1 deferrals. The collector stubs in `src/fleet_tracker/collectors/` carry one-line docstrings pointing back to those sections.

## Sources we explicitly do not use

- **Private data**: no tipsters, no leaks, no scraping of internal airline systems. v1 and beyond.
- **Cached Trump-card sources**: no Internet Archive / Wayback Machine workarounds for paywalled content.
- **Facial data**: photos that incidentally show passengers or crew get filtered or excluded. Fleet Tracker tracks aircraft, not people. See [docs/ethics.md](ethics.md).
