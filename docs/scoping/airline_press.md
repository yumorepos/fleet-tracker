# `airline_press` collector — scoping

Pre-implementation scoping for the first cabin-observation collector. The
question this doc answers is narrow: **before opening the implementation
work, can we extract the IN_PROGRESS retrofit signals [DESIGN §6](../DESIGN.md)
needs — announcement date, aircraft type affected, retrofit start, cabin
class — from each carrier's press feed without bespoke per-carrier
parsing?** The eyeballed answer is "yes for the structured fields, no
for the deep retrofit semantics" — see Findings below.

## Why this collector first

The other two cabin collectors (`planespotters`, `seatmap`) both have ToS
or source-availability questions ([DESIGN §2](../DESIGN.md), [data-sources.md](../data-sources.md)).
`airline_press` is the only cabin source that:

1. Has unambiguous ToS posture (publisher is the airline; PR distribution
   is literally meant to be redistributed).
2. Produces the IN_PROGRESS signal that `retrofit.py` needs — announcements
   land before installations start, so the press feed is the *earliest*
   evidence of an in-flight retrofit program.
3. Is dual-use: the same parsed announcement also confirms `fleet_membership`
   facts ("AC says they operate 787-10s") which can cross-validate the
   Wikipedia fleet collector.

So implementing `airline_press` first does double work and unblocks the
retrofit module's classification path that has been stubbed since v1.

## What the collector needs to extract

For each press release that mentions a retrofit, fleet change, or cabin
program, the collector should emit one or more observations carrying:

| Field | Source in release | Confidence |
|---|---|---|
| `published_at` | JSON-LD `datePublished` | 0.95 (structured) |
| `headline` | JSON-LD `headline` | 0.95 (structured) |
| `airline` | URL/source assignment | 1.0 (input) |
| `aircraft_type` | regex over headline + body | 0.70 (lexical) |
| `signal_kind` | `retrofit_announcement` (new) or `fleet_membership` (overlap) | — |
| `signal_value` | aircraft_type + program name | 0.65 |
| `source_url` | release URL | 1.0 |

Deep semantics — *"retrofit starts in September 2026"*, *"42 aircraft
affected"*, *"by 2030, 90% will have doors"* — are body-text-only and
need either an LLM extraction pass or per-carrier curation. **Out of scope
for v1 of this collector.** First implementation captures the announcement;
a later pass adds structured retrofit-timeline extraction.

## Findings — Carrier 1: Delta (`news.delta.com`)

**Status: green light.** Trivially scrapable; first to implement.

### Discovery
- RSS feed at `https://news.delta.com/rss.xml` returns valid RSS 2.0 (55KB,
  HTTP 200 with the project's User-Agent). This is the new-release signal —
  no need to scrape the index.

### Per-release parsing
Three releases captured (Apr 2026 cabin announcement, A330neo Argentina
launch, A321neo Delta First). All three expose:

- `<script type="application/ld+json">` with `@type: "NewsArticle"`
  containing structured `headline`, `datePublished`, `dateModified`, and a
  `publisher.name = "Delta News Hub"`. Dates are ISO 8601 with timezone.
- An `about` array of categories. For aircraft-specific releases this
  includes the type tag verbatim:
  - A330neo release: `["Aircraft", "A330-900neo", ...]`
  - A321neo release: `["On Board", "Domestic First Class", ...]` (no type tag — release is fleet-wide for that subtype)
  - Cabin-fleet release: `["On Board", "Customer Experience", "Delta Fleet"]` (no type tag — multi-fleet program)

### Implication
DL parsing is `json.loads()` on the JSON-LD block, no DOM scraping needed
for the structured fields. Aircraft type extraction needs a regex pass
over `headline` and (when available) `about[]` because the type tag is
present roughly half the time.

### Sample release URLs verified
- `https://news.delta.com/delta-introduces-next-generation-airbus-a330-900neo-flights-between-us-and-argentina`
- `https://news.delta.com/select-a321neos-begin-service-larger-delta-first-cabin`
- `https://news.delta.com/delta-unveils-new-cabin-interior-across-its-fleet`

## Findings — Carrier 2: Air Canada — yellow/red light

**Status: blocked at the airline-direct path; viable via Cision.**

### Direct newsroom: blocked
- `https://www.aircanada.com/media/<slug>/` returns **HTTP 403 with Akamai
  `errors.edgesuite.net` reference**. Same anti-bot pattern documented in
  [data-sources.md](../data-sources.md) for Planespotters/FlightRadar24/CCARCS.
- `https://aircanada.mediaroom.com/` (the Cision-hosted IR portal AC links
  to) **also returns HTTP 403**. The AC media stack is uniformly hostile
  to programmatic access.
- Both User-Agent identification and standard headers were tried; the
  block is not UA-based, it's edge-network policy.

### Workaround: Cision newswire.ca
- `https://www.newswire.ca/news/air-canada/` is the third-party PR
  distribution mirror — Cision publishes AC releases here as part of the
  paid distribution AC pays them for. Returns HTTP 200, ~250KB index.
- Individual release URLs: `https://www.newswire.ca/news-releases/<slug>-<id>.html`
- One captured release (`air-canada-toasts-economy-customers-...`)
  contains a single `<script type="application/ld+json">` block with
  `@type: "NewsArticle"`, `headline`, `datePublished`, `dateModified`,
  and `publisher.name = "CNW Group"` (Cision's Canadian arm). **Same
  shape as DL.**

### What's missing on Cision
- No discoverable RSS feed (`/rss/orgnews/?n=Air+Canada` 404s; no
  `<link rel=alternate>` on the index page).
- No `about` category tags in the JSON-LD I tested.
- Discovery would have to be via index-page scraping with diff against a
  seen-URLs set — slightly more brittle than DL's RSS, but standard.

### ToS posture
Cision's content is the airline's own press release republished by the
distributor AC pays. ToS-clean for read access; rate-limit politely
(daily index check, not minutely). Each parsed release carries
`source_url` pointing to the Cision page so attribution is in the
observation row.

### Cision dependency fragility
Cision is a workaround, not a primary source. Three things follow:

- **Cision is the discovery surface, AC's own newsroom is the canonical
  source.** If a future Akamai-bypass or AC API change unblocks the
  direct newsroom, the AC collector should switch over and treat
  Cision as a fallback.
- **The collector records the canonical AC URL alongside the Cision URL
  it actually fetched from.** A Cision release page links back to
  `aircanada.com/media/...`; capture both, store the AC URL as the
  authoritative `source_url` and the Cision URL as `fetched_from` (or
  similar). This means a future migration off Cision doesn't break the
  link to the original release.
- **Monthly tripwire on Cision liveness.** A check that
  `newswire.ca/news/air-canada/` has at least one release dated within
  the last 60 days. If it doesn't — AC moved PR distributors, Cision
  changed URL structure, or the index template broke — the alert fires
  loudly so we know to investigate. Silent breakage on a third-party
  mirror is the failure mode this guards against.

## Shared parser shape

Both carriers converge on the same per-release extraction:

```
1. Fetch release HTML
2. Find <script type="application/ld+json"> blocks
3. Filter to @type == "NewsArticle"
4. Pull: headline, datePublished, dateModified, publisher.name
5. Combine headline + body text
6. Regex aircraft types (A220-300, 787-9, 737 MAX 8, A330-900neo, ...)
7. Emit one observation per recognized type
```

Discovery is the only carrier-specific layer:
- DL: parse RSS, get list of `<item><link>` URLs
- AC: scrape `newswire.ca/news/air-canada/` index, extract
  `/news-releases/...` hrefs, diff against seen set

The cleanest module shape: `airline_press.py` exposes `discover(airline)`
that returns a list of release URLs and `parse_release(url, html)` that
returns a list of observations. The discover function dispatches per
carrier; the parser is shared.

## Recommendation: implementation order

1. **DL collector first.** RSS discovery is half a day; JSON-LD parsing
   is shared so building it in DL-first form sets up AC for free. Land
   one PR with `airline_press.collect_dl()`, a captured DL release
   fixture in `tests/fixtures/airline_press/`, and parser tests against
   the three DL captures already in this scoping work.

2. **AC collector as a second PR.** Same `parse_release` reused, new
   `discover_ac()` that scrapes Cision's `/news/air-canada/` index. Two
   captured AC releases as fixtures (one cabin-related, one routine like
   the beer-and-wine release that's already verified extractable).

3. **Hard scope boundary on body-text extraction.** v1 of the collector
   captures **announcement existence**: date, headline, URL, JSON-LD
   metadata, and the full body as opaque text stored alongside the
   observation. v1 does **not** parse retrofit semantics from the body —
   no extraction of "starts September 2026", "42 aircraft affected",
   cabin-class breakdowns, or aircraft-type-to-timeline mapping. The
   retrofit module consumes announcement existence as a weak signal
   only ("AC announced a cabin program; flag any A330-300 in the seed
   as potentially-IN_PROGRESS until tail-level evidence resolves it").
   v1.5 picks one of LLM-driven extraction or per-carrier curation —
   that choice is **deferred with a tripwire**: revisit when
   `retrofit.py` actually needs `install_rate` numerics, not before.
   This boundary is load-bearing for keeping the v1 collector small;
   "out of scope" by itself is too soft and invites scope creep.

The two-PR split mirrors the OpenSky → Wikipedia order ([PRs #2-#6](https://github.com/yumorepos/fleet-tracker/pulls?q=is%3Apr)):
prove the shared shape on the cleaner source first, then adapt to the
harder one.

## Out of scope for the implementation PRs

- Auto-classifying announcement→retrofit-start dates (LLM extraction or
  per-carrier regex; deferred to v1.5).
- Cabin-class breakdown (J/W/Y) extraction beyond keyword matching.
- Multi-airline RSS aggregation. Phase 4 is AC + DL only; United/WestJet/
  regional carriers wait for v2 per [ROADMAP.md](../../ROADMAP.md).
- Press release archives older than the RSS window (DL RSS shows ~recent
  releases; the 2024 cabin-fleet announcement we captured was findable
  by URL but wouldn't appear in fresh RSS pulls). v1 covers go-forward
  observations only; backfill is manual if anyone asks.
- AC's direct newsroom. The Akamai 403 is a hard ban; Cision is the
  realistic path and trying to defeat the bot block is both a ToS
  violation and a brittle long-term position.

## Open questions worth flagging before implementation

- **DL RSS retention window.** The RSS feed currently lists ~recent
  releases; cadence for "did we miss one" depends on how often we poll
  vs how fast DL evicts older items. Initial v1 cadence: daily pull,
  matches OpenSky. Adjust if eviction is faster than that.
- **Cision rate-limiting policy for AC index scraping.** Daily is almost
  certainly fine; sub-hourly probably isn't. No published rate limit;
  start daily and watch HTTP 429s.
- **`retrofit_announcement` as a new `signal_kind`** vs reusing
  `fleet_membership`. The press release confirms the airline operates
  the type (= `fleet_membership`) AND that a retrofit is announced
  (=new). DESIGN §6 already separates per-tail vs type-level signals;
  this is a third axis (declarative vs observational vs announcement).
  Recommend: a new `signal_kind = 'retrofit_announcement'` to keep
  audit semantics honest, mirroring how PR #6's
  `fleet_membership` carve-out earned its keep when PR #7's audit
  module read it.
