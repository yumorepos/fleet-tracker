# Delta 2025: bounded origin segment and reported-delay cause results

**Status (2026-11-11):** The initial real-source study **passed** its quality gates on [GitHub Actions run #43101205867](https://github.com/yumorepos/fleet-tracker/actions/runs/43101205867). Its 16 offline tests passed, its population and on-time counts reconciled with the earlier independently audited BTS pilot, and the five cause minutes equalled the reported arrival delay within one minute on every delayed record with complete detail. An independent SQLite re-aggregation **passed** in [GitHub Actions run #43102105597](https://github.com/yumorepos/fleet-tracker/actions/runs/43102105597): **21 offline tests passed**, and SQLite exactly reproduced the primary segment denominators, late arrival counts, positive LateAircraftDelay incidence, reported minutes, missing cause counts, and mismatch checks in both official source archives.

Population: BTS Reporting Carrier On-Time Performance monthly archives for **January and July 2025**, filtered to \`Reporting_Airline=DL\`. U.S. reportable domestic operations, NOT all Delta-marketed, international or codeshare operations. These are two separate unadjusted monthly snapshots. Airport segment is **departure/origin airport ATL** versus **all other origin airports**. Rows belong to exactly one segment.

Source hashes:
- January \`868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf\`
- July \`74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19\`

## Descriptive departure-origin comparison

| Measure | Jan ATL origin | Jan other origins | Jul ATL origin | Jul other origins |
|---|---:|---:|---:|---:|
| Scheduled reporting-carrier records | 17,468 | 58,838 | 21,855 | 72,211 |
| Completed, nondiverted | 16,598 | 57,427 | 21,492 | 70,753 |
| On-time arrivals among completed | 12,777 | 46,946 | 14,993 | 54,334 |
| **Arrival on-time rate** | **76.98%** | **81.75%** | **69.76%** | **76.79%** |
| **Cancellation rate / scheduled** | **4.76%** | **2.22%** | **1.23%** | **1.46%** |
| Late arrivals >=15 minutes | 3,821 | 10,481 | 6,499 | 16,419 |
| Late arrivals with complete five-cause detail | 3,821 | 10,481 | 6,499 | 16,419 |
| Late arrivals with **positive carrier-reported LateAircraftDelay** | 1,172 | 4,454 | 2,419 | 8,184 |
| **LateAircraftDelay positive / complete late arrivals** | **30.67%** | **42.50%** | **37.22%** | **49.84%** |
| LateAircraftDelay minutes reported in delayed arrivals | 49,899 | 255,837 | 108,597 | 474,748 |

Rates use separate denominators on the same row. This is a *conditional percentage of qualifying late flights with positive reported cause minutes*, NOT a share of all scheduled flights, nor an allocation of all delay minutes. Multiple causes can be reported for a flight; the cause-positive counts overlap and should not be added together as distinct flights.

### Reconciliation to the population baseline

- January: 17,468 + 58,838 = **76,306 scheduled**, and 12,777 + 46,946 = **59,723 on-time completed**.
- July: 21,855 + 72,211 = **94,066 scheduled**, and 14,993 + 54,334 = **69,327 on-time completed**.
- The source study found **100% complete five-cause detail** among the 14,302 January and 22,918 July late-arriving DL reported flights. No invalid arrival flags, no arrival flag/delay contradictions, and **zero cause-minute sum mismatches** above one minute.
- The primary and independent SQL implementations independently check cause-field completeness, missingness, and source archive SHA. The independent SQLite verifier passed all population and cause metrics. These results are now internally accepted **within their limited observational study scope**; neither implementation establishes causal attribution.

## Finding and cautious operational interpretation

ATL-origin flights had **lower observed on-time arrival rates** than flights originating elsewhere by **4.77 percentage points in January** and **7.03 points in July**. They also had **lower incidence of positive carrier-reported late-aircraft cause minutes among their late arrivals** (30.67% vs 42.50% in January; 37.22% vs 49.84% in July).

This combination is useful because it shows why a naive "late inbounds explain ATL's performance" narrative is not supported. However, BTS cause fields are **carrier-reported attribution on late arriving flights**, not independent physical matching and NOT a causal estimate. A flight departing ATL can incur delay due to issues at its destination, en route, or other schedule factors. The separate actual-gate same-tail candidate association also uses a selected and incomplete aircraft sample; the two analyses **must not be numerically conflated or joined without a matching research contract**.

**Suggested analyst follow-up:** segment further by scheduled departure bank, destination, route and flight mix *using the same already verified source*, ideally in a transparent SQL view, before attributing the ATL-origin gap to local processes or proposing an intervention. No weather, seasonal, operational-financial or causal effect is identified by this study.

**Decision:** GO for carefully scoped descriptive comparison and candidate investigation priority; STOP short of causal delay-propagation claims, actual complete tail utilization, or management action based on unadjusted segment gaps.

## Authoritative definitions, code and verification

- BTS Technical Directive #39 (2025): https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time
- Original KPI source checks: \`docs/BTS_DELTA_PILOT_2025_RESULTS.md\`
- Original same-tail feasibility (independently verified): \`docs/BTS_TAIL_SEQUENCE_2025_RESULTS.md\`
- Profiling code: \`src/fleet_tracker/bts_driver_profile.py\`
- Independent SQLite verifier: \`src/fleet_tracker/bts_driver_sql_verify.py\`
- No raw BTS flight records are committed. Aggregate-only workflow outputs are short-lived.
