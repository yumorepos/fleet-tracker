# Delta 2025 — source-verified timestamp anomaly triage

**Status: PASS for bounded, aggregate-only description; root causes remain UNRESOLVED.** This is a narrow follow-up to the already independently verified [historical same-tail study](BTS_TAIL_SEQUENCE_2025_RESULTS.md). Do not overwrite the published results or infer operational or causal effects.

## Question

How large are the **three January scheduled-arrival clock contradictions** and **two July observed same-tail overlaps** retained in the original study? Do two independent timestamp reconstructions classify them consistently?

## Data, population and source gates

Official U.S. BTS January and July 2025 Reporting Carrier On-Time Performance ZIPs, filtered to `Reporting_Airline=DL`. Only scheduled DL domestic reportable operations count toward source population totals; canceled and diverted rows are excluded from gate-time reconstruction.

- January ZIP SHA-256: `868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf`
- July ZIP SHA-256: `74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19`
- Actual-source [GitHub Actions run #43993894049](https://github.com/yumorepos/fleet-tracker/actions/runs/43993894049): **PASS** for original source SHA gates, historical count contracts, and primary/independent gate-clock plus tail-pair parity.
- [Full PR test run #43993894054](https://github.com/yumorepos/fleet-tracker/actions/runs/43993894054): **214 tests passed**, including the 14 new synthetic triage tests.
- Audit artifact: `bts-delta-2025-anomaly-triage-aggregates`, artifact ID **14289380324**, containing only `bts_anomaly_triage.json` (7-day retention). Downloaded aggregate JSON SHA-256: `89cb8ab90f844946e87c252bc4f9d7f94da44faa09bddad555bc20b5a10239d1`.

## Original denominator and candidate-pair reconciliation

| Measure | Jan 2025 | Jul 2025 |
|---|---:|---:|
| Scheduled DL domestic reporting-carrier rows | 76,306 | 94,066 |
| Completed nondiverted rows | 74,025 | 92,245 |
| Valid reconstructed gate-time records | 74,022 | 92,245 |
| Observed candidate pairs, 20–360-minute ground gap | 53,047 | 71,881 |

**The original numbers were not revised or reclassified.** The two implementations agreed on accepted versus rejected gate rows and their derived candidate-pair/association summaries. This is verification against the same official source, not independently observed complete aircraft history.

## Newly classified anomalies

| Retained anomaly | Jan 2025 | Jul 2025 |
|---|---|---|
| Scheduled-arrival local-clock contradictions | **3** | **0** |
| Scheduled clock disagreement magnitude | **2** over 1–5 minutes; **1** over 5–15 minutes | None |
| Same-tail, same-airport observed pairs with negative gate gap | **0** | **2** |
| Negative ground-gap magnitude | None | **1** over 15–60 minutes; **1** over 60 minutes |

**Interpretation:** The three January local scheduled-clock discrepancies are small in absolute minute terms, but exceed the original ±1-minute clock tolerance. The two July observed overlaps exceed 15 minutes, including one exceeding an hour; neither can be dismissed as a one-minute clock-rounding artifact. The results do **not** identify a mistaken BTS field, a real simultaneous aircraft operation, a changed aircraft assignment, or the source of either inconsistency.

No individual flight/date, airport pair, flight number or aircraft tail appears in the report; original archives and SQLite rows were ephemeral on the GitHub runner. Coarse categories are data minimization, not a guarantee of anonymity.

## Decision

**GO:** Preserve original rejects and same-tail overlap exclusions; describe their severity and verified method parity transparently in the historical case study. The official [BTS 2025 Technical Directive No. 39](https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time) specifies local clock times and time-zone adjustment when interpreting elapsed fields.

**STOP at causal/root-cause attribution.** Without an independently authoritative per-operation event or schedule record, the small residuals and negative gate gaps cannot explain *why* the source fields disagree. Do not change the original 2025 KPI, candidate links, denominator rules, selected date population, or delay-association results. In particular, do not infer real airline fleet utilization, a physical aircraft conflict, preventable delays, or cost savings.

**Next decision:** No follow-up data collection is justified solely by five already excluded anomalies. Reconsider if new trusted source records, an unrecognized structural error, or an operational question requiring tail-level certainty become available. Future work should preserve the existing analytic baseline and be separately approved.
