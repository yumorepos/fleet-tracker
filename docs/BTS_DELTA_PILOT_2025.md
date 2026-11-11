# Delta January/July 2025 BTS on-time pilot — research-only gate

**Purpose:** validate official public flight records before developing the airline operational performance case study. No new dashboard, no claims of complete fleet utilization, no warehouse modification, and no historical KPI claim until actual-source verification.

- Official BTS [Reporting Carrier On-Time Performance 1987-present PREZIP](https://transtats.bts.gov/PREZIP/) monthly all-field ZIP archives, January and July 2025.
- Reporting population and flight definitions: [Technical directive #39 effective January 1, 2025](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time).
- **Population**: domestic nonstop reported flight operations with Reporting_Airline=DL. Not necessarily Delta mainline or all Delta-marketed partner services. Transborder/international service is outside the BTS reporting population. January/July differences are descriptive, not causal or calendar-mix-adjusted.
- Source grain is each reported scheduled operation. Original ZIP SHA-256, source row counts and flags are recorded; no raw flight/tail rows are committed.

## KPI and denominator contract
1. Cancellation rate: Cancelled=1 / every scheduled DL reporting-carrier row.
2. Diversion rate: Diverted=1 / every scheduled DL row. Separately computed, not assumed disjoint from cancellations.
3. Arrival on time: ArrDel15=0 / non-canceled, non-diverted DL rows having ArrDel15 in {0,1}. Explicit missingness and denominator. Not necessarily identical to a separately published BTS score.
4. Tail availability: nonempty Tail_Number / non-canceled non-diverted DL rows. This alone cannot validate aircraft continuity, turnarounds, or propagation.
5. Provisional duplicate key: date + flight number + origin + destination + CRS departure clock. Flag collisions without deduplication.

## Predeclared gates
Both months require >=1,000 DL rows and all 31 flight dates; >=99.5% valid cancellation/diversion flags; >=98% arrival flag coverage for non-canceled non-diverted flights; >=98% numeric arrival-delay coverage among valid flags; <=0.1% flag contradictions and provisional key collisions; zero missing route/CRS clock fields. A failure yields **REVISE**, not suppressed rows or inferred KPI results.

Separate tail field threshold >=90% gives **CANDIDATE_ONLY** for a later sequence study; it does not permit turnaround or delay propagation claims without independent airport/timestamp continuity and tail-swap tests.

## Run
Within Fleet Tracker's installed Python environment:

    python -m fleet_tracker.bts_delta_pilot --download --output /tmp/bts_dl_2025_quality.json

Or pass official local ZIPs via --january and --july. The branch-specific GitHub Action runs no recurring job; only aggregate JSON is retained as a short-lived workflow artifact. Do not merge or make a dashboard before real-data GO/REVISE review.

Avgeek's current ingester discards the date, tail and schedule fields and aggregates arrival flags using a different denominator; reuse field definitions, not its precomputed rates. Preserve existing Fleet Tracker code and do not build or migrate a frontend.
