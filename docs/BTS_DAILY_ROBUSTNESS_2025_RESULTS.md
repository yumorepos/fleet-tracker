# Delta BTS January/July 2025 — daily robustness and selection sensitivity

**Evidence status:** Official-source **GO for descriptive sensitivity screening**. Original BTS ZIP checks, month-level KPIs, all four matched on-time rates and the 25-flight departure-bank findings are preserved. The complete strengthened source audit and independent SQL verification passed in [GitHub Actions #43991663523](https://github.com/yumorepos/fleet-tracker/actions/runs/43991663523). [Predeclared analytical protocol](BTS_DAILY_ROBUSTNESS_2025_PROTOCOL.md).

**Decision question:** Does the previously verified ATL-origin versus other-origin arrival-punctuality comparison remain descriptively similar when analysts change the number of flights required per matched destination-bank cell, restrict operations to weekday/weekend, or exclude an individual BTS FlightDate?

**Source and population:** Official monthly 2025 BTS Reporting Carrier On-Time Performance ZIPs, filtered to \`Reporting_Airline=DL\`, January **76,306** and July **94,066** scheduled DL domestic reported flights. Arrival on-time denominator excludes canceled/diverted flights and requires valid \`ArrDel15\`. The ZIP SHA-256 values match [the previously source-verified BTS bank study](BTS_DEPARTURE_BANK_DESTINATION_MIX_2025_RESULTS.md). January SHA starts \`868387dcedae\`, July \`74309a3a734d\`; complete hashes live in \`bts_driver_profile.EXPECTED_SHA\`. These are **two separate historical snapshots**, not full airline network coverage or a seasonal experiment.

All differences below are **ATL-origin minus other-origin arrival on-time rate, percentage points**. A negative gap indicates lower punctuality among the selected ATL-origin flights. \`CRSDepTime\` bins are local to each departure origin, not common UTC windows or airline-defined schedule waves.

## 1. Matching threshold sensitivity

The destination × origin-local departure-bin comparison is reconstructed from scratch for each candidate minimum **valid completed arrivals per origin in each matched cell**, at 10, 25, or 50. Both groups must meet the minimum in a given cell. Each selected cell receives a pooled \`ATL valid + other valid\` weight; the reported difference is the resulting pooled-standardized *descriptive* difference.

| Sample | Min. valid per origin/cell | Matched cells | ATL eligible coverage | Other eligible coverage | Pooled-standardized ATL − other | Predeclared 50% coverage gate |
|---|---:|---:|---:|---:|---:|---|
| Jan 2025 | 10 | 164 | 63.68% | 67.06% | **−5.231 pp** | Exploratory subset |
| Jan 2025 | **25** | **150** | **60.77%** | **66.17%** | **−5.276 pp** | Exploratory subset |
| Jan 2025 | 50 | 97 | **47.29%** | 58.48% | **−5.603 pp** | **Low coverage** |
| Jul 2025 | 10 | 182 | 64.73% | 65.67% | **−2.433 pp** | Exploratory subset |
| Jul 2025 | **25** | **174** | **63.01%** | **65.39%** | **−2.518 pp** | Exploratory subset |
| Jul 2025 | 50 | 121 | 50.39% | 61.66% | **−2.250 pp** | Exploratory subset |

**Interpretation:** Within the predefined thresholds, all standardized matched comparisons retain a negative sign, but the magnitudes and selected populations change. January at a 50-flight minimum does **not** meet the study's coverage gate for ATL arrivals; its estimate is retained as a low-coverage diagnostic, not presented as a broadly representative network value. July's ATL coverage at 50 is only just above the 50% gate: coverage passing that threshold does not confer causal validity.

## 2. What changes when we select a different population and reweight it?

The all-flight comparison and the 25-flight matched/standardized comparison use **different denominator populations and weights**. This previously mattered especially in July.

| Arithmetic comparison | Jan 2025 | Jul 2025 |
|---|---:|---:|
| Full-month unadjusted ATL − other (\`G_all\`) | −4.770 pp | −7.033 pp |
| Matched-subset unadjusted ATL − other (\`G_selected\`) | −6.964 pp | −7.044 pp |
| Selected-subset pooled standardized (\`G_pooled\`) | **−5.276 pp** | **−2.518 pp** |
| **Selection shift** (\`G_selected - G_all\`) | **−2.194 pp** | **−0.011 pp** |
| **Reweighting shift** (\`G_pooled - G_selected\`) | **+1.688 pp** | **+4.526 pp** |

The arithmetic identity \`G_pooled = G_all + selection shift + reweighting shift\` holds within displayed rounding. **This is a descriptive identity, not a causal decomposition.** In July, the change from approximately −7.0 to −2.5 percentage points is driven mostly by how eligible destination-bank cells are weighted, not by removing a large raw sample gap. That does **not** demonstrate that destination mix explains the underlying operational gap; the comparison still pools flights with different origins and routes.

## 3. Weekday versus weekend subset sensitivity

Using each BTS FlightDate's calendar weekday, the 25-minimum matching process and pooled weights were **recomputed within the weekday or weekend data only**.

| Month | FlightDate group | Days | Matched cells | ATL coverage | Other coverage | Pooled gap | Coverage decision |
|---|---|---:|---:|---:|---:|---:|---|
| Jan | Weekdays | 23 | 111 | 51.54% | 61.82% | −4.493 pp | Exploratory subset |
| Jan | Weekends | 8 | 18 | **13.19%** | **16.58%** | −8.092 pp | **Low coverage** |
| Jul | Weekdays | 23 | 128 | 52.60% | 62.25% | −3.296 pp | Exploratory subset |
| Jul | Weekends | 8 | 32 | **18.04%** | **27.69%** | −2.149 pp | **Low coverage** |

The weekend estimates cover only a small fraction of weekend arrivals and must **not** be generalized to weekend performance. These are reselected flight populations, so differences cannot be interpreted as isolated day-of-week effects. The weekday sample also remains selected and observational.

## 4. Daily concentration and leave-one-day-out robustness

For each sample month, all 31 local scheduled operating-date labels were analyzed. A fresh 25-flight destination-bank match was built 31 times, excluding one FlightDate at a time. **Each exclusion can change which cells qualify.** These leave-one-day-out values are *sensitivity diagnostics*, not a bootstrap confidence interval.

| Leave-one-day-out at 25 minimum | Jan 2025 | Jul 2025 |
|---|---:|---:|
| Complete reconstructions | 31 / 31 | 31 / 31 |
| Full-month standardized reference | −5.276 pp | −2.518 pp |
| Minimum gap among omissions | −5.915 pp | −3.037 pp |
| Maximum gap among omissions | −3.476 pp | −1.516 pp |
| Largest absolute shift versus original | **1.800 pp** | **1.002 pp** |
| Gap sign reversals | **0** | **0** |

- **January 22** is the most influential removed date for the standardized gap: omitting it moves the estimate from −5.276 to **−3.476 pp**. This is sensitivity to a dated subset, **not** evidence of an identifiable underlying cause.
- **July 21** is the most influential omission: the gap moves to **−1.516 pp**. The matching rule is recalculated, not held fixed.
- Daily *unadjusted* gaps vary even more sharply: e.g. **January 10** reports 0 ATL on-time arrivals among **99** valid ATL arrivals, against 960 / 1,487 other-origin on-time arrivals that day (raw ATL-minus-other gap −64.560 pp). That unusually small and adverse ATL daily subgroup can dominate a day's raw difference; no explanation such as weather, schedule recovery or airport causation was tested here.

**Interpretation:** None of the 31 single-day exclusions reverses the sign of the pooled gap in either month, but omitting one date can change its magnitude meaningfully. The sample remains historically narrow and observational. These diagnostics cannot establish uncertainty beyond the two chosen monthly samples and do not provide a formal confidence interval.

## Engineering checks and evidence limits

- **Historical parity:** previously verified month source ZIP hashes and Delta KPI denominators, all eight origin-bank group counts per month and **the original 25-flight matched composition/rates** are checked before daily analysis can publish.
- **Independent verification:** a separate SQLite source ingestion and aggregation independently reconstructs **3 matching thresholds + 2 day-type restrictions + 31 omitted days per month = 72 comparison checks**, plus **62 day-group count/rate checks** across the two official source archives. The initial run returned \`INDEPENDENT_SQL_PARITY_PASS\`. Research aggregate outputs are retained in the run for seven days; source ZIPs are not committed or uploaded as artifacts.
- **Fail-closed:** incorrect archive hash, malformed flight status, unexpected date, bad origin/destination, missing source field, invalid minute clock, changed original 25-flight report, unexpected month totals, or independent SQL mismatch aborts the run.
- **No independence claim:** flight-level rates share departure airports, dates, weather exposure, schedule choices and possible aircraft dependencies. The 31 daily exclusions do **not** imply 31 independent experiments, statistical significance or treatment effects.
- **No operational savings or intervention:** this study doesn't include all Delta-marketed operations, measured controllable airline delay mechanisms, a new predictive model, a causal airport effect or a seasonality analysis.

**Research decision:** Retain the negative ATL-origin gap as a *bounded descriptive finding*, explicitly downgrade weekend matched interpretations due to coverage, and recognize the influence of individual disrupted dates. Any proposed follow-up should first investigate the small-sample days and alternative route/composition definitions with independently verified source evidence. No staffing, dispatch, schedule or weather-intervention claim is warranted.
