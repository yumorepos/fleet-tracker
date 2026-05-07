# Airline press fixtures

Captured 2026-05-07 from `news.delta.com` via the project's collector
(FleetTrackerBot User-Agent). Each release is the unmodified HTML
response. The DL News Hub publishes airline press releases that are
meant to be redistributed; no transformation needed.

## Files

- `dl_rss.xml` — `https://news.delta.com/rss.xml`. The discovery feed.
- `dl_a330neo.html` — Argentina A330-900neo route launch (datePublished 2025-01-15). Aircraft type tagged in JSON-LD `about[]`.
- `dl_a321neo.html` — A321neo Delta First cabin expansion (datePublished 2026-02-11). No aircraft type in `about[]`; type lives in headline + body only.
- `dl_cabin_fleet.html` — Fleet-wide cabin interior unveil (datePublished 2024-10-06). No type-specific tag — fleet-wide program.

The three releases were chosen to span the JSON-LD shape variations the
parser needs to handle: type-tagged `about` (a330neo), no type tag with
type in headline (a321neo), and no type at all in metadata (cabin-fleet
program announcement).

## Re-capturing

The DL collector runs `fetch_release(url)` against any
`news.delta.com/<slug>` URL with the project's User-Agent. To refresh:

    uv run python -m fleet_tracker.collectors.airline_press --discover dl --max 5

(Discovers via RSS and prints parsed observations; no DB write.) Then
copy the cache file from `data/cache/airline_press/<slug>_<date>.html`
into this directory.
