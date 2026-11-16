# Delta BTS 2025: departure-bank and shared-destination mix audit

**Status:** Research extension, not a published operational result until an official-source run and independent SQL parity both pass.

## Decision question and expected value

Do the observed ATL-origin versus other-origin **arrival punctuality** differences vary by **origin-local scheduled departure bank**, and do they persist when comparing flights serving the same destination in the same local departure-time bin?

This helps an operations analyst decide **which departure periods and destination mixes to investigate next**. It does not establish an airport-process problem, weather cause, intervention opportunity, or predictive performance.

**Scope:** Only BTS Reporting Carrier On-Time Performance 2025 January and July source ZIP archives with `Reporting_Airline=DL`; exact source SHA-256 values must match the previous validated study. Read-only source processing, with no raw flight output retained.

**Time/effort gate:** Approximately 2–3 focused hours for primary method, synthetic tests, source check, independent SQL, and a concise interpretation. Stop rather than expand if source reconciliation or independent SQL fails.

## Predefined definitions

- **Local scheduled clock:** `CRSDepTime`, representing scheduled departure at the **origin** airport using local time, from [BTS Technical Directive #39](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time). Special BTS value `2400` maps to the 00–05 bin. Invalid clock or airport data fail the research gate.
- **Departure bins:** 00:00–05:59, 06:00–11:59, 12:00–17:59, 18:00–23:59. Bin names `00-05`, `06-11`, `12-17`, `18-23`; *not* empirically observed airline schedule banks.
- **Scheduled denominator:** all `Reporting_Airline=DL` reportable domestic scheduled records in the segment.
- **Arrival on-time denominator:** non-canceled, non-diverted records with valid `ArrDel15` (0 or 1). On-time numerator: `ArrDel15=0`.
- **Origin comparison:** ATL departures versus all non-ATL departures; both are heterogeneous observational populations. A destination match **does not** match the actual origin–destination route.
- **Shared destination-bank match:** within each month, use destination × scheduled local departure bin only where both ATL and other-origin segments have at least **25 valid arrivals**. Drop any unmatched cell from the standardized comparison but **report coverage in each origin group**; do not treat excluded flights as on time or late.
- **Descriptive standardization:** for each matched cell `i`, pooled completed-flight weight `w_i = n_ATL,i + n_other,i`. Compare `sum(w_i * ontime_ATL,i / n_ATL,i)/sum(w_i)` against the analogous other-origin expression. Difference is `ATL minus other` in percentage points. These are **pooled-distribution-standardized descriptive rates on a selected set**, NOT causal effects or a complete network adjustment.
- **Interpretation gate:** if matched coverage in either group is under 50%, mark `LOW_COVERAGE_OR_NO_MATCH` and do not represent the comparison as a general network finding. Even a higher-coverage comparison remains *exploratory*.

## Source validation and independent verification

1. Reuse `bts_delta_pilot` to independently establish historical source hashes and January/July baseline counts and denominator gates.
2. Primary streaming analysis: `src/fleet_tracker/bts_bank_mix.py`. Aggregates the verified ZIP into 16 month × origin × departure-bin rows, plus a summary of matched destination/bin strata. No flight-level rows persisted.
3. Independent method: `src/fleet_tracker/bts_bank_sql_verify.py`. Separately rereads source rows, reconstructs the grouping in in-memory SQLite, and checks **all 16 bank-group rows and matched summary quantities**. No shared primary aggregation, clock helper or matching function.
4. Fail closed on source hash drift, unexpected month, invalid clock, airport, status or arrival flags, population/KPI mismatch, or independent SQL discrepancy. Return rejected findings rather than repairing unknown records.
5. Manual-source GitHub Actions verification is triggered by relevant PR changes or manually; no scheduled data collection is configured. Raw BTS ZIPs are removed from the research runner; artifact retention is limited to aggregate-only reports for seven days.

### Manual source workflow

Download the two official ZIPs using the already documented `fleet_tracker.bts_delta_pilot.download` helper (or use existing verified local files), then:

```bash
PYTHONPATH=src python -m fleet_tracker.bts_delta_pilot \
  --january bts_1.zip --july bts_7.zip --output baseline.json

PYTHONPATH=src python -m fleet_tracker.bts_bank_mix \
  --january bts_1.zip --july bts_7.zip --baseline baseline.json \
  --output bank_mix.json

PYTHONPATH=src python -m fleet_tracker.bts_bank_sql_verify \
  --january bts_1.zip --july bts_7.zip --report bank_mix.json \
  --output bank_mix_sql_verification.json
```

## Decision and next development gate

If the source and independent SQL both pass, document (1) observed bank-level arrival punctuality, (2) raw ATL/other differences, (3) matched-stratum coverage, (4) the pooled-standardized comparison if coverage permits, and (5) alternative explanations and limits.

Do not update the recruiter website or invent a causal/predictive conclusion. Larger source windows, route controls, bank definitions based on actual airline schedules, statistical uncertainty intervals, and modeling are **future research candidates**, not automatic next tasks.
