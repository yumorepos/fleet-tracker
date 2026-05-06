# Ethics

Fleet Tracker is a public-facing dashboard built from public sources. Five principles shape what is collected, displayed, and not displayed.

## 1. Public sources only

Every claim in Fleet Tracker traces back to a publicly accessible source: airline press releases, regulator filings, photo databases, scheduled-flight tracking. No tipsters, no leaks, no scraping of internal airline systems, no inferred data presented as fact.

**Why**: the project's credibility depends on every assertion being independently verifiable by a reader. Insider information would erode that posture immediately, even if it improved coverage.

## 2. Link, don't host

Aircraft photos are linked to their source platforms (Planespotters.net, JetPhotos) with photographer attribution. Fleet Tracker never re-hosts the image binary, never serves a hot-linked thumbnail without the partner agreement that would make it acceptable, and never strips an attribution.

**Why**: image copyright belongs to the photographer. Re-hosting changes the licensing posture from "Fleet Tracker references third-party images" to "Fleet Tracker republishes them" — a meaningful legal and ethical line. Linking with attribution stays on the safe side.

## 3. Provenance on every claim

Every datum on the dashboard surfaces its source: a URL to the airfleets page, the press release, the OpenSky observation, the seat map. The per-tail page shows source confidence per [DESIGN §2](DESIGN.md), and the underlying observations are queryable per row.

**Why**: aviation people will push back on data, and they should. Provenance lets a reader check us, correct us, and trust us when the source is solid.

## 4. Track aircraft, not people

Fleet Tracker tracks tail numbers, types, ownership, routes, and cabin configurations. It does not collect, store, or display data about pilots, cabin crew, or passengers. Photos that incidentally show identifiable people are filtered or excluded; flight records do not carry crew assignments; ownership records cover legal entities, not individuals.

**Why**: the airline industry treats employee identification as a real privacy concern. The retrofit tracker convention carries forward: photos that incidentally show crew or passengers get cropped or excluded, and Fleet Tracker has no business knowing who flew which leg.

## 5. The cache is gitignored for the right reason

The `data/cache/flights/` directory is gitignored, but not because the data is private. OpenSky's response data is public — anyone with credentials can fetch the same JSON. The directory is gitignored because **re-publishing third-party data as a Fleet Tracker dataset would change its licensing posture**: from "Fleet Tracker queries OpenSky on demand and shows derived aggregates" to "Fleet Tracker redistributes OpenSky data as its own." The first is acceptable under OpenSky's terms; the second is not.

**Why**: the dashboard's posture is that we are a consumer of public data, not a redistributor of it. The cache layer enables performance; it does not become a publishable artifact.

---

If you spot something Fleet Tracker is doing that violates one of these principles, please open an issue. Better to be corrected than wrong.
