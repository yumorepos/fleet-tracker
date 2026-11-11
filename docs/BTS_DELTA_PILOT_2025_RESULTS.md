# BTS Delta Jan/Jul 2025 read-only pilot — verified checkpoint (2026-11-11)

**Status: core KPI source-quality GO for two bounded months; no public case study claim or model released.**

Official data: [BTS Reporting Carrier On-Time Performance](https://transtats.bts.gov/PREZIP/), Jan and July 2025 all-field monthly ZIPs. [2025 BTS reporting directive #39](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time). Filter `Reporting_Airline=DL`; this is **not** all Delta-marketed operations or a certified continuous fleet dataset.

| Metric | January 2025 | July 2025 |
|---|---:|---:|
| All reporting-carrier source rows | 539,747 | 631,428 |
| DL scheduled rows | 76,306 | 94,066 |
| Flight dates | 31 | 31 |
| Cancelled | 2,137 (2.80%) | 1,320 (1.40%) |
| Diverted | 144 (0.19%) | 501 (0.53%) |
| Non-canceled, non-diverted | 74,025 | 92,245 |
| Eligible valid ArrDel15 | 74,025 (100%) | 92,245 (100%) |
| Within 15 minutes of scheduled arrival | 59,723 / 74,025 (80.68%) | 69,327 / 92,245 (75.16%) |
| Tail number present among eligible | 74,025 (100%) | 92,245 (100%) |
| Provisional duplicate flight keys | 0 | 0 |
| ArrDel15/ArrDelay inconsistencies | 0 | 0 |
| **Core KPI quality gate** | **GO** | **GO** |
| **Tail field gate** | **CANDIDATE ONLY** | **CANDIDATE ONLY** |

**Metric definitions:** Cancellation rate = canceled / scheduled DL rows; diversion = diverted / scheduled DL rows; arrival punctuality = ArrDel15=0 / non-canceled, non-diverted DL rows with a valid ArrDel15. The two observed monthly counts each satisfy scheduled = canceled + diverted + eligible. These are analysis-specific KPI definitions and **not necessarily exactly BTS's separately published score**.

**Source ZIP SHA-256**
- Jan: `868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf`
- Jul: `74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19`

**Verification:** [Actual-data GitHub Actions run](https://github.com/yumorepos/fleet-tracker/actions/runs/43081981445) completed successfully, including six offline regression tests and an aggregate-only JSON artifact (14-day retention). Data were downloaded in ephemeral CI storage, not committed. An initial REVISE was caused by a parser that rejected BTS `0.00`/`1.00` formatted flags; it was fixed and regression tested before this successful run. Do not interpret the initial zero valid-record counts as true source measurements.

**Limitations:** July's descriptive arrival rate is 5.52 percentage points below January, but the traffic/route/schedule mix differs; **no causal or weather/seasonal effect is identified**. Complete nonblank tail fields in two months do not prove tail continuity, actual daily utilization, maintenance, delay propagation or valid turnarounds. U.S. domestic reporting rules exclude international/transborder segments and do not certify complete Delta-marketed network coverage.

**Next gated task:** Independent calculation with SQL or a separate implementation; source flight-grain/codeshare semantics review; cross-midnight gate-time and tail continuity assessment. Freeze the source snapshot and do not add a UI or merge this exploratory PR until reviewed.
## Independent SQL validation — completed November 11, 2026

A separate [SQLite audit workflow](https://github.com/yumorepos/fleet-tracker/actions/runs/43082988191) re-read the same official two ZIPs, normalized binary flags independently with Decimal, and recomputed the eligible flight denominators and status counts in SQL. **PASS:** 12 count metrics per month exactly match the primary Python analysis, source SHA-256 hashes match, and no duplicate-key disagreements were detected.

The verified DL scheduled counts remained **76,306** (January) and **94,066** (July). The independent audit's offline suite passed **8/8 tests**. This verifies a deliberately narrow set of arithmetic/data-contract measures, not BTS-published airline score parity, countrywide operational coverage, tail sequence validity, or causal conclusions.

The temporary branch-only Actions workflow should be retired or converted to non-scheduled reproducibility guidance before any merge. The PR remains draft and unmerged.
