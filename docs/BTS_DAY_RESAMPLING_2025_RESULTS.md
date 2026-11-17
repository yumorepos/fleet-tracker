# Delta 2025 paired operating-day resampling — independently verified results

**Research status (November 16–17, 2026 UTC):** **GO for bounded descriptive stability diagnostics; no formal inferential claim.** The original January and July 2025 official BTS source hashes, population/KPI totals, departure-bank matching and preceding daily robustness checks all passed. A **separate SQLite implementation recomputed all 1,200 resampled comparisons**, their seeded date draws and fingerprints, the summary percentiles, and the influential-date rankings with **zero disagreements**. [Source and independent SQLite verification: GitHub Actions #43994081776](https://github.com/yumorepos/fleet-tracker/actions/runs/43994081776). [Predefined method and assumption checks](BTS_DAY_RESAMPLING_2025_PROTOCOL.md).

## Operational question and population

How much does the observed **ATL-origin minus other-origin arrival on-time gap** shift when the *composition of historical operating days* is resampled rather than treating every flight as an independent observation?

Official BTS January/July **2025** reporting-carrier data with Reporting_Airline=DL only, **not** the complete Delta-marketed network. The population retains **74,025** eligible January arrivals and **92,245** eligible July arrivals with valid arrival-15-minute flags, excluding canceled and diverted flights. Each destination and origin-local scheduled departure bank must have **at least 25 eligible arrivals in both origin groups** before being included in the descriptive, pooled-cell-weighted standardization. This selected population covers **60.77% of ATL and 66.17% of other-origin eligible January arrivals**, and **63.01% and 65.39% in July**.

The original source archives' verified SHA-256 digests begin **868387dcedae** (January) and **74309a3a734d** (July). Every archived month, KPI and previously verified matched gap is preserved.

## Fixed methods

Two resampling procedures, **300 replicates in each month and method**, fixed seed **20261116**:

- **Individual-day paired sampling:** draw 31 FlightDate labels with replacement; resample ATL and other-origin aggregates together for each selected label, preserving within-day joint variation but not serial dependence.
- **Noncircular moving blocks of 3 days:** draw consecutive three-day windows (start dates 1–29) with replacement until 31 labels are accumulated, then truncate. This retains short neighboring-date sequences but breaks dependence at block joins and underweights month-end days.
- **Full recomputation:** aggregate the drawn days with multiplicities, then recompute which destination-bank groups satisfy the 25-flight threshold, each group's coverage, and the pooled standardized gap. A replicate with no matched groups would remain undefined, not be set to zero.
- **Reported bands:** nearest-rank empirical 5th to 95th percentile of the 300 resampling outputs, **not** confidence limits. The standardization still matches a destination and *origin-local* departure period, **not the same route or UTC clock**.

No historical airline activity was synthesized, and repeating the label of one observed date does not create independently observed flights.

## Main verified observations

**Negative gaps indicate lower observed ATL-origin punctuality in the matched selected sample.** All reported differences are percentage points, and every percentile is conditional on the stated resampling method and the two selected months.

| Month | Method | Full-month matched gap | Resampled median | 5th percentile | 95th percentile | Positive draws / 300 |
|---|---|---:|---:|---:|---:|---:|
| **January 2025** | Individual-day paired | **−5.276** | −5.343 | **−10.581** | **−1.386** | **2** |
| January 2025 | Noncircular 3-day blocks | −5.276 | −5.656 | −12.004 | −0.712 | **8** |
| **July 2025** | Individual-day paired | **−2.518** | −2.402 | **−5.226** | **+0.644** | **32** |
| July 2025 | Noncircular 3-day blocks | −2.518 | −2.205 | −5.347 | +0.263 | **26** |

**Key negative robustness finding:** The July *standardized matched* comparison is **not sign-stable across the full predeclared resampling distribution** under either method; its central empirical ranges extend above zero. January remains negative in the middle 90% of draws under both methods but has a few positive extreme draws. In contrast, the **July unadjusted full-population gap** stays negative even at the 95th empirical percentile under both procedures (individual-day **−9.559 to −4.200 pp**, blocks **−9.699 to −4.269 pp**). These differences are descriptive changes induced by selecting and weighting different sample compositions, not causal effects.

### Sample coverage and undefined results

| Month / method | Defined matched gaps | Draws missing the 50% coverage gate | 5th-percentile ATL coverage | 5th-percentile other-origin coverage | Median matched destination-bank cells |
|---|---:|---:|---:|---:|---:|
| January / individual days | 300 / 300 | 0 | 59.97% | 65.54% | 150 |
| January / three-day blocks | 300 / 300 | 0 | 59.62% | 65.42% | 149 |
| July / individual days | 300 / 300 | 0 | 62.19% | 64.97% | 174 |
| July / three-day blocks | 300 / 300 | 0 | 62.12% | 64.83% | 174 |

The **50% gate is only a minimum descriptive-coverage check**, not proof of representativeness. At the original full-month resolution roughly one-third to two-fifths of eligible flights remain outside the selected destination-bank population.

## Influential operating dates from the separately audited leave-one-day-out checks

The previously verified 31 single-day exclusions per month were ranked by absolute movement in the full-month matched standardized gap. No new weather or airport data were added, and no cause was assigned to a flagged day.

| Month | Excluded FlightDate label | Valid ATL arrivals that day | Valid other-origin arrivals that day | That day's *unadjusted* gap | Matched standardized gap after exclusion | Change from full month |
|---|---|---:|---:|---:|---:|---:|
| January | **22** | 444 | 1,726 | −45.631 pp | −3.476 pp | **+1.800 pp** |
| January | 12 | 539 | 1,857 | −28.742 pp | −4.024 pp | +1.252 pp |
| January | 11 | 419 | 1,413 | −38.848 pp | −4.206 pp | +1.070 pp |
| July | **21** | 754 | 2,423 | −32.074 pp | −1.516 pp | **+1.002 pp** |
| July | 11 | 727 | 2,393 | −23.636 pp | −1.870 pp | +0.648 pp |
| July | 16 | 689 | 2,296 | +4.231 pp | −3.037 pp | **−0.519 pp** |

**Caveat:** These day-level *unadjusted* figures and monthly *matched standardized* figures use **different populations and weights**, so they must not be combined mechanically or interpreted as disruption severity. The change after removing one day can reflect that day's own outcomes **and** re-selection/reweighting of other destination-bank strata. The detected influence is **not evidence of weather causality, dispatch action or preventable delay**.

## Verification record

- **Historical evidence retained:** original Delta 2025 source ZIP SHA-256 and original monthly KPI/denominator checks; unchanged origin-bank source aggregation and independent bank SQL; prior **72 threshold/day-type/leave-one-day-out and 62 daily SQL checks** all passed before this stage.
- **New independent checks:** the separate in-memory SQLite verifier read the same hashed BTS ZIPs, independently applied all 1,200 weighted date schedules to its source-derived cells and reconstructed standardized and unadjusted gaps, coverage, matched-cell counts, 5th/50th/95th percentile statistics and rank-ordered influential dates. It returned **INDEPENDENT_SQL_PARITY_PASS** with 600 reaggregations for each month. [Exact audited run](https://github.com/yumorepos/fleet-tracker/actions/runs/43994081776).
- **Artifact reproducibility:** raw 2025 ZIPs are runner-only and deleted after use. The seven-day GitHub Actions artifact retains aggregate-only paired date-label arrays, SHA-256 draw fingerprints, resampled summary statistics and an independent SQL audit JSON. No raw per-flight, tail-number or passenger records are included.
- **Offline tests:** synthetic ZIP ingestion, deterministic and replicated-date draws, source quality, matched-cell threshold changes, noncircular block boundaries, undefined rates, deliberate corruption, and atomic no-overwrite output.
- **No new inferential proof:** 31 observed dates per month, purposively chosen months, potential serial dependence, shared airport/weather/aircraft exposure and boundary effects of the chosen block method prevent defensible nominal confidence-interval or significance claims. Resampling frequencies are **conditional simulation diagnostics**, not probabilities of a true airport effect.

## Research decision

**Retain the original descriptive findings with narrower interpretive confidence.** The raw ATL-origin punctuality shortfall is repeatedly observed in these two snapshots; the matched/standardized **July sign is sensitive to date composition** and both resampling mechanisms, despite the previous single-day leave-one-out procedure having no sign reversals. Do not interpret a negative full-month matched figure as an established stable effect, and do not use these selected two months to recommend staffing, ground-handling, schedule changes, aircraft positioning or weather controls.

**Most useful next research question:** Is the matched and day-weighted pattern replicated across additional independently quality-gated months or alternative population definitions? Do not expand data solely to create a wider sample; predefine historical coverage, quality thresholds, computational effort and acceptance/negative-result criteria before any such extension.
