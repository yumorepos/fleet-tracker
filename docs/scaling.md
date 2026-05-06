# Scaling

Fleet Tracker's storage trajectory across v1, v1.5, and v2. The full storage decisions live in [DESIGN §1](DESIGN.md); this document is a one-page summary of where data volumes land at each stage.

## v1 — on-demand + 24h cache

| Layer | Storage | Volume |
|---|---|---|
| Cache | `data/cache/flights/{tail}_{YYYYMMDD}.json` | ~5-50 KB per tail per day, gitignored |
| Reference | `data/reference/{airline}-mainline.csv` | A few KB total, committed to git |
| DuckDB | `data/fleet.duckdb` | <1 MB (5-10 seed tails of metadata), gitignored, rebuildable |
| Parquet flights | `data/flights/airline=*/year=*/month=*/flights.parquet` | Empty in v1; the slice writes one fixture-sized file (~5 KB) per slice run |

v1 is dominated by the cache layer. Cache rotation is daily per the filename-date governance rule.

## v1.5 — nightly Parquet append

Triggered when the active tail-watch list exceeds 20 per airline OR OpenSky daily credit ceiling is hit more than once per week (DESIGN §1).

| Layer | Storage | Volume |
|---|---|---|
| Parquet flights | Hive layout, append-only | ~90 KB per partition (one airline-month) at AC + DL combined volume; ~2.2M rows per year combined |
| DuckDB | Same file, more reads | Reads scale with query patterns; 2-3 GB working-set at full v1.5 scope |

At AC + DL combined (~1200 mainline tails total, ~6000 flights/day), monthly partitions are healthy: 90k rows is well within DuckDB's predicate-pushdown sweet spot.

Per [DESIGN §1](DESIGN.md), the nightly job may write multiple files per month directory (`flights.parquet`, `flights_001.parquet`, ...) if it runs more than once per UTC month. The read glob `month=*/*.parquet` tolerates either pattern.

## v2 — historical backfill (deferred indefinitely)

Per Yumo's Phase 0 review: deferred indefinitely. Trino/MinIO research-tier access to OpenSky was the path; not pursued because the multi-week side quest does not belong in initial scoping.

If the project gains traction and historical backfill becomes valuable (e.g., for retrofit install-rate computation across multi-year programs), the steps would be:

1. Apply for OpenSky research-tier credentials.
2. Bulk-fetch historical `/flights/aircraft` data into `data/flights/airline=*/year=*/month=*/historical.parquet` (separate filename to distinguish from nightly partitions).
3. Read path stays unchanged; the glob picks up both filenames automatically.

Volume estimate at v2 (10 years of AC + DL combined history): ~20M flight rows, ~2 GB Parquet, well under DuckDB's single-file comfort zone.

## Sizing reference

| Stage | Total disk | Active queries | Notes |
|---|---|---|---|
| v1 | <10 MB | DuckDB metadata only | Cache files don't count toward query volume |
| v1.5 (1 month in) | ~100 MB | First-month Parquet, full DuckDB | First nightly accumulation |
| v1.5 (1 year in) | ~1 GB | 12 months Parquet | Predicate pushdown via Hive partitions keeps reads cheap |
| v2 (full backfill) | ~3-5 GB | 10+ years Parquet | DuckDB still single-host; no need for distributed engine |

DuckDB scales single-host to tens of GB without difficulty. Fleet Tracker is unlikely to need anything beyond DuckDB through v2.
