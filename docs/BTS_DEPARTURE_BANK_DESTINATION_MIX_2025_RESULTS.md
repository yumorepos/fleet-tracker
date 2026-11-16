# Delta 2025 scheduled departure-bank and shared-destination mix — verified results

**Status (November 16, 2026):** Official-source research **GO for descriptive screening**, not causal interpretation. Both source archive hashes and Jan/Jul baseline totals reconciled, and a **second in-memory SQLite implementation reproduced all 16 origin × scheduled-local-bank rows and every reported destination-bank matching summary**. [Source and independent SQL run #43971192642](https://github.com/yumorepos/fleet-tracker/actions/runs/43971192642) passed, as did the standard offline test workflow for PR #16.

**Question:** For Delta reporting-carrier domestic flights, does the observed ATL departure-origin punctuality gap vary with scheduled departure period, and what happens in a common **destination × local departure-bank** comparison?

**Population:** Official BTS Jan and Jul **2025**, `Reporting_Airline=DL` domestic reportable flights. January: **76,306 scheduled**, **74,025 completed nondiverted with valid arrival flags**, **59,723 on time**. July: **94,066 scheduled**, **92,245 valid completed**, **69,327 on time**. Both sources match the existing [quality pilot](BTS_DELTA_PILOT_2025_RESULTS.md) and [origin-segment audit](BTS_DELTA_SEGMENT_2025_RESULTS.md). These are distinct selected calendar months, not all Delta-marketed flights, not complete network coverage, and not a seasonal experiment.

## Results 1 — origin-local scheduled departure bins

BTS `CRSDepTime` is the **scheduled origin-airport-local** clock; banks below are prespecified six-hour analytical bins, **not** independently verified airline scheduling bank definitions. `2400` is treated as midnight, in the 00–05 bin. Rates = `ArrDel15=0` / completed noncanceled, nondiverted rows with a valid arrival-delay flag. Difference = ATL minus other, in percentage points.

| Month | Scheduled local bin | ATL on-time / valid | ATL rate | Other origins on-time / valid | Other rate | ATL − other |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Jan 2025 | 00–05 | 0 / 0 | N/A | 1,796 / 2,055 | 87.40% | N/A |
| Jan 2025 | 06–11 | 4,334 / 5,601 | 77.38% | 20,715 / 24,637 | 84.08% | −6.70 pp |
| Jan 2025 | 12–17 | 4,320 / 5,597 | 77.18% | 16,178 / 20,315 | 79.64% | −2.45 pp |
| Jan 2025 | 18–23 | 4,123 / 5,400 | 76.35% | 8,257 / 10,420 | 79.24% | −2.89 pp |
| Jul 2025 | 00–05 | 0 / 0 | N/A | 2,515 / 2,729 | 92.16% | N/A |
| Jul 2025 | 06–11 | 6,028 / 6,957 | 86.65% | 25,900 / 29,839 | 86.80% | −0.15 pp |
| Jul 2025 | 12–17 | 5,013 / 7,594 | 66.01% | 16,816 / 23,632 | 71.16% | −5.15 pp |
| Jul 2025 | 18–23 | 3,952 / 6,941 | 56.94% | 9,103 / 14,553 | 62.55% | −5.61 pp |

**Reconciliation:** Across all four banks, ATL and other-origin scheduled, canceled, diverted, valid-completed and on-time counts exactly reconstruct both original monthly BTS KPI totals. ATL had **no scheduled flights in the 00–05 bin** in either sampled month; this is **absence of a comparison group**, not a zero-percent on-time result.

**Descriptive reading:** The gap is not uniform across these coarse bins: January's largest observed gap is in the 06–11 period; July's gap is near zero in 06–11 but larger in 12–17 and 18–23. Differences in aircraft, airports, routes, scheduled flight mix, local time zones, congestion, weather, reporting, and selection remain unresolved. Nothing here shows that one bank or the ATL airport caused another flight to run late.

## Results 2 — selected shared destination × local departure-bank comparison

Within **each month separately**, use only destinations and local departure bins where **both ATL-origin and other-origin** records have at least **25 valid completed arrivals**. Pool the matched-cell counts to make a *common-weight descriptive standardization*; detailed formula and controls are defined in [the preregistered method](BTS_DEPARTURE_BANK_DESTINATION_MIX_2025.md).

| Measure | January | July |
| --- | ---: | ---: |
| Matched destination × bank cells | 150 | 174 |
| Valid ATL departures in matched cells | 10,087 | 13,542 |
| Valid other-origin departures in matched cells | 37,999 | 46,266 |
| Fraction of all ATL valid arrivals covered | 60.77% | 63.01% |
| Fraction of all other-origin valid arrivals covered | 66.17% | 65.39% |
| Matched subset observed ATL on-time | 74.86% | 68.00% |
| Matched subset observed other-origin on-time | 81.82% | 75.04% |
| **Pooled-standardized ATL on-time** | **76.10%** | **71.80%** |
| **Pooled-standardized other-origin on-time** | **81.37%** | **74.32%** |
| **Pooled-standardized ATL − other** | **−5.28 pp** | **−2.52 pp** |
| Predeclared coverage gate | Exploratory subset | Exploratory subset |

**Interpretation:** The matched standardized difference remains negative in both selected samples, but the gap magnitude changes. The all-flight unadjusted gap from the preceding study was **−4.77 pp in January and −7.03 pp in July**. These numbers are **not a controlled before/after test**, because matching excludes approximately one third to two fifths of valid flights and deliberately changes the distribution of destinations and periods. Comparing ATL→destination with other-origin→destination does **not** hold the same origin–destination route fixed. Neither destination mix nor local departure bank can be isolated as the causal reason for a change.

## Validation record and retained limitations

- **Source provenance:** Official 2025 BTS monthly ZIP SHA-256 digests and original total counts were checked again by the research runner. January `868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf`; July `74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19`.
- **Independent verification:** Separate SQLite ingestion and grouping passed source hash, all bank totals and the matched standardization metrics on both monthly source archives. Reproducible job evidence: [GitHub Actions #43971192642](https://github.com/yumorepos/fleet-tracker/actions/runs/43971192642). The short-lived job artifact contains **aggregate-only** `bank_mix.json` and `bank_mix_sql.json`.
- **No model or effect estimate:** Two selected months and unadjusted reporting data cannot quantify seasonal effects, forecast new disruption risk, recommend staffing changes, or calculate avoidable delay.
- **No route-level causal control:** Destination-only matching differs from holding origin–destination route fixed; bank bins are coarse and based on local airport clocks. Overnight ATL is missing, so that direct comparison is undefined.
- **Reproducibility and privacy:** No raw flight rows or tail-number records are committed. [Primary code](../src/fleet_tracker/bts_bank_mix.py), [independent SQL verification](../src/fleet_tracker/bts_bank_sql_verify.py), and [offline tests](../tests/test_bts_bank_mix.py) are linked for reruns.

**Operational decision:** Use the verified descriptive bank results to prioritize further investigation of period-specific route/destination mix and scheduling conditions—**especially why July's two later bins differ from the July morning comparison**—before selecting a causal study, a broader baseline, or any intervention. Do **not** infer an intervention solely from this report.
