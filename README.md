# Fleet Tracker

Tracking current and historical fleets of major airlines, with per-aircraft history.

## What this is

Fleet Tracker maintains a tail-by-tail record of an airline's fleet: which aircraft are flying, who owns them, where they've been, and how their cabins are configured. v1 covers Air Canada and Delta Air Lines mainline operations.

The project answers questions that public fleet pages typically don't:

- For any given tail number, what does its history look like?
- Who currently owns it, who used to, and when did the leases turn over?
- Which sub-fleet variant is it, and when was the last cabin retrofit confirmed?
- Where has it flown over the time we've been watching?

## Status

Active development. The repository contains the data model, schema, full test suite (61 tests), and a working OpenSky live-flight collector with OAuth authentication. Additional collectors (Planespotters photos, airfleets ownership, AeroLOPA seat maps, airline press) are stubbed for Phase 4 with their interfaces defined. The Astro dashboard lives in `site/` and is also Phase 4 work.

## Stack

- Python 3.12+, managed with `uv`
- DuckDB for the query layer, Parquet for flight history (Hive-partitioned by airline / year / month)
- OpenSky Network for live flights (authenticated tier)
- Static site generated with Astro for the dashboard (Phase 4)
- GitHub Actions for nightly collection (Phase 4)

## Layout

```
src/fleet_tracker/        Python package
data/reference/           Hand-curated fleet rosters
data/flights/             Parquet archive (gitignored)
data/cache/flights/       24h fetch cache (gitignored)
docs/                     Research, design, plan, methodology
tests/                    Pytest suite
notebooks/                Jupyter analysis (Phase 4)
site/                     Astro dashboard (Phase 4)
```

See [docs/DESIGN.md](docs/DESIGN.md) for the architecture, [docs/PLAN.md](docs/PLAN.md) for the build sequence, and [docs/RESEARCH.md](docs/RESEARCH.md) for the data-source landscape.

## Running locally

```bash
# Install
uv sync

# Run tests
uv run pytest

# Vertical slice: pull recent flights for one Air Canada tail
cp .env.example .env  # then add your OpenSky credentials
uv run python -m fleet_tracker.collectors.opensky --icao24 c01040 --airline ac --hours 48
```

The example uses an icao24 hex code directly. To use registration syntax (`--tail C-FBOM`), populate the icao24 column in `data/reference/ac-mainline.csv` first. See [docs/data-sources.md](docs/data-sources.md) for the lookup technique.

## Sample output

Trimmed from a real slice run on 2026-05-05 against C-FBOM (icao24 c01040):

```
opensky: wrote cache C01040_20260506.json (1 records)
opensky[C01040]: 1 flights, null estDepartureAirport=1 (100.0%), null estArrivalAirport=0 (0.0%) — exceeds 5% threshold from DESIGN §1
Wrote data/flights/airline=ac/year=2026/month=05/flights.parquet
```

The 100% null `estDepartureAirport` rate on this single flight is a structural OpenSky pattern at smaller airports, not a bug — see "Notes on the data" below.

## Contributing

If you work on a fleet planning team and notice something off in this data, please open an issue. Better to be corrected than wrong.

## Notes on the data

OpenSky's `estDepartureAirport` field is frequently null at smaller airports with weaker ADS-B ground coverage. The tracker preserves these null values rather than guessing; the per-tail dashboard view (Phase 4) will render flights with unknown origin as "? → DEST" rather than dropping them.

Airport codes throughout the project are ICAO (CYUL, KATL), not IATA (YUL, ATL). This matches what OpenSky natively returns. ICAO → IATA display conversion happens at render time.

## Sources and ethics

Fleet Tracker uses public data only. See [docs/data-sources.md](docs/data-sources.md) for the source list and [docs/ethics.md](docs/ethics.md) for the principles that shape what is collected, displayed, and not displayed.

## Licence

MIT. See [LICENSE](LICENSE).
