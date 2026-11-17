# Pilot 03 — Delta 2025 clock contradictions and observed same-tail overlaps

**Status:** Proposed bounded diagnosis, isolated feature branch. No research conclusion, merge, deployment or automatic collection authorized.

## Problem and prior evidence

Original, independently checked January/July 2025 U.S. BTS Reporting Carrier On-Time Performance research (filter: Reporting_Airline=DL) preserved **three January scheduled-arrival clock contradictions** and **two July observed same-tail overlapping pairs**. The original source data were not silently corrected. Relevant evidence:

- [Tail-sequence results](BTS_TAIL_SEQUENCE_2025_RESULTS.md), including official monthly SHA-256 values and the independent SQL reconstruction.
- [Original source/KPI validation](BTS_DELTA_PILOT_2025_RESULTS.md) and [BTS technical reporting directive 39](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time).
- Published candidate pairs: **53,047 January**, **71,881 July** for observed same-tail, same-airport, nonoverlapping **20–360-minute** ground gaps.

The BTS directive requires local clock reporting and elapsed time interpretation across time zones. An inconsistency in our reconstructed arrival clock is **not sufficient evidence** of which reported field is wrong; an observed same-tail overlap is **not evidence** of what an airline or aircraft actually did.

## Research questions

1. Can both independent timestamp paths still agree on all accepted/rejected records and preserve the original scheduled, valid-timestamp and candidate-pair counts?
2. Are the historical scheduled-arrival clock contradictions small timing residuals or material discrepancies? Report coarse magnitude groups only.
3. Are the observed overlaps within approximately one minute (potential rounding ambiguity) or larger? Report coarse magnitudes without disclosing tail, route, flight number, time, or date identifiers.
4. Do diagnostic counts contradict the frozen report? STOP rather than change the original published data.

## Method and privacy

The new Python module reads only the two original **SHA-256-pinned** official monthly ZIPs, filters reporting-airline DL, excludes canceled/diverted operations from gate analysis, and retains only in-memory temporary legs and an in-memory SQLite reconstruction. It compares the primary local-to-UTC gate parser with the independent actual-elapsed-time reconstruction and checks full candidate-pair/association summary parity before forming aggregate diagnostic summaries. It never commits or exports raw rows, dates, flight numbers, routes or tail IDs.

Only count totals, timestamp-rejection categories and coarse (0–1, >1–5, >5–15, >15–60, >60 minutes) disagreement/overlap magnitudes are recorded. Because some groups contain very few observations, bins are **not anonymization guarantees**; they are data-minimization safeguards, not a public record-level product.

## Acceptance, negative results and STOP rules

- No original source-hash or published study count drift.
- Both independent timestamp/pairing implementations agree for each source flight and aggregate result; no silent override of mismatches.
- Source workflow runs synthetic tests first, retains only a seven-day aggregate JSON and deletes the original source ZIP files from the runner.
- Classification results may establish **severity of observed inconsistencies**, not the cause, aircraft status, flight continuity, operational delay propagation, or a repair.
- An absence of explanatory evidence must be reported as **unresolved**. Do not modify the previously validated research results to improve the narrative.
- Pilot 03 code and results remain on an isolated branch / draft PR; **do not merge or deploy without explicit human approval**.
