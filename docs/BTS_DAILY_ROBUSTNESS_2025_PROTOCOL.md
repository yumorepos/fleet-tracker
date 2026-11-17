# Delta BTS 2025 — daily robustness and sample-selection protocol

**Research status:** Bounded extension of the already source-verified Jan/Jul 2025 Delta reporting-carrier study. No seasonal, causal or forecast claims. The original [departure-bank report](BTS_DEPARTURE_BANK_DESTINATION_MIX_2025_RESULTS.md) and its previously verified 25-flight selected comparisons remain the unchanged reference.

## Operational question

Are the previously reported ATL-origin versus other-origin arrival-punctuality differences stable to (a) the minimum matching count, (b) selecting weekday or weekend flying, and (c) omitting a single scheduled operating day? How much of the difference between the all-flight unadjusted gap and the selected destination-bank standardized gap comes from **selecting a different set of flights** versus **reweighting the selected cells**?

**Value:** Expose sensitivity and sample-composition risks before recommending deeper causal modeling, expanded history, or interventions.

## Fixed population, definitions, and methods

Use **only** the two previously independently checked official BTS ZIP archives for **January and July 2025**, records with \`Reporting_Airline=DL\`, and the original \`CRSDepTime\` origin-local four six-hour bins. Exactly revalidate archived SHA-256 values, all original monthly scheduled/canceled/diverted/eligible/on-time counts, and all eight monthly origin-bank counters against the existing frozen [bank report](BTS_DEPARTURE_BANK_DESTINATION_MIX_2025_RESULTS.md). Recheck the earlier 25-flight matched population, coverage and standardized gap **exactly** before advancing. Any mismatch is a failed research gate, not a correction to existing published results.

Denominator for arrival punctuality = **noncanceled, nondiverted flights with valid \`ArrDel15\`**. Numerator = \`ArrDel15=0\`. Never score a canceled or diverted flight as an on-time or late completed arrival.

### 1 — Threshold sensitivity

For the same **destination × scheduled local-bank** cells, compare minimum eligible arrivals per origin group = **10, 25 and 50**. Threshold is applied **within each January or July month**, separately, to both ATL-origin and non-ATL-origin counts. All matched cells are weighted by pooled valid completions (ATL + other-origin) as in the original study. Report matched stratum counts, flight coverage *for each group*, matched raw and pooled standardized gaps, and whether both coverages reach the pre-existing 50% descriptive-coverage gate. The threshold-25 result must reproduce the independently checked original.

### 2 — Sample restriction versus reweighting (descriptive arithmetic, not causal decomposition)

Define negative values as ATL's lower on-time rate, in **percentage points**.

- \`G_all\`: ATL minus other on-time rate among **all eligible** flights within the selected days.
- \`G_selected\`: ATL minus other on-time rate after filtering to matching destination-bank cells, with each origin population weighted by its own observed flights.
- \`G_pooled\`: previous standardization — average within-cell ATL-minus-other difference using **pooled matched-flight counts** as weights.
- **Selection shift:** \`G_selected - G_all\`.
- **Reweighting shift:** \`G_pooled - G_selected\`.
- Identity \`G_pooled = G_all + selection shift + reweighting shift\`, up to displayed rounding.

These shifts do not identify why particular flights are late and are **not causal effect estimates**. Destination matching still compares different origins and different routes.

### 3 — Day-type restrictions

Separate weekdays (Monday–Friday) and weekends (Saturday–Sunday) by **BTS FlightDate**, interpreted as the local operating-date label. Within **each** day type, reselect 25-minimum destination-bank cells. Do not reuse the full-month selected strata or weights. Report denominator coverage and identify sparse/empty matching subsets. Local flight dates and clock bins are not synchronized UTC exposure intervals.

### 4 — Daily and leave-one-calendar-day-out robustness

For each of the **31 operating-date labels** in each of the two months, report the ATL and other-origin valid-arrival counts and raw daily punctuality gap. This is a **daily descriptive trace**, not independent day-level randomized exposure.

For every possible omitted date, re-aggregate the other **30 days** and **recompute the 25-minimum matched cells and pooled weights from scratch**. Report all 31 exclusion results, their min/max, maximum absolute gap change versus the full month, and number of sign flips. A changed match set after omitting a borderline day is expected and must be tested.

These sensitivity checks **do not provide a formal confidence interval or significance test**. Shared aircraft, geography, airports, schedules, weather and operation patterns violate naive independent-flight assumptions. No multiplicity-corrected hypothesis testing or cross-month trend claim is proposed.

## Engineering and acceptance

- The primary implementation, \`bts_daily_robustness.py\`, streams ZIP rows into **daily aggregate counters only**; no raw flight rows, date-level route tables or tail numbers are persisted.
- The independent \`bts_daily_sql_verify.py\` rereads the original ZIPs and creates in-memory SQLite source rows (never on disk), then uses SQL aggregations, independent grouping and arithmetic to check all **three monthly thresholds, two day-type restrictions, and 31 single-day exclusions per month**, plus 31 daily population checks. Verify both months and their original ZIP SHA values.
- Offline synthetic tests include threshold monotonicity, a 25-flight cell that becomes unmatched after one day is excluded, decomposed sample-selection identity, missing matches, cancellation/diversion handling, source drift, and atomic no-clobber output.
- Research execution is only on pull requests changing the relevant files or explicit manual dispatch, not a recurring job. GitHub runner re-downloads the same two official source archives, executes the previous quality and independent bank SQL checks, then creates the new robustness report and independent verification.
- Only **aggregate JSON output** is archived for seven days; downloaded source ZIPs are deleted on the runner and never committed. The original 25-flight findings and limitations are preserved.
- **GO:** original source/KPIs, original month-bank and 25-flight comparisons, all 72 independent sensitivity comparisons, 62 daily source counts and offline tests pass. A changed direction or poor coverage in sensitivity results is a **valid negative robustness finding**, not a reason to rewrite the data or to hide it.
- **STOP/REVISE:** any source/provenance mismatch, incorrect denominator, unexpected missing-day interpretation, independent SQL discrepancy, invalid source fields, or failed regression.

No new dashboard, paid service, fleet monitoring schedule, causal conclusion or deployment is part of this bounded technical milestone.
