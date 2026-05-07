# OpenSky flight fixtures

Captured 2026-05-07 from the live OpenSky API using the project's own
collector (`fleet_tracker.collectors.opensky`) against 9 real in-scope
tails. Each fixture is the unmodified JSON response cached by the
collector during a 48-hour pull window.

## Re-capturing

Requires `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` in `.env`. Per
tail:

    uv run python -m fleet_tracker.collectors.opensky --tail <TAIL> --hours 48

Then move the resulting cache file from `data/cache/flights/` into this
directory and update `manifest.json`.

## Why this matters

The notebook's Pass 3 cell falls back to these fixtures when the local
cache is empty, which is the state on a fresh clone. The fallback
preserves "real captured data" semantics — the alternative
(synthesized OpenSky-shape data) was rejected during the session that
built this fixture as a less honest portfolio artifact.
