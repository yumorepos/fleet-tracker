# Delta 2025 operational reliability: aircraft connection feasibility audit

Date: 2026-11-11. **Current source status:** Merged in
[PR #11](https://github.com/yumorepos/fleet-tracker/pull/11), with independent
window-SQL verification. Presented in the
[public portfolio](https://yumorepos.github.io/airline-operations.html)
as a *limited descriptive, noncausal historical case study*, not a
production or complete-fleet data product. Sections describing early
pre-verification checkpoints remain historical snapshots. 
Actual-source run: https://github.com/yumorepos/fleet-tracker/actions/runs/43086211150
PR: https://github.com/yumorepos/fleet-tracker/pull/11

## Question and population

Can January and July 2025 public BTS Delta reporting-carrier records support carefully limited historical aircraft connection analysis? Each monthly archive contains reporting-carrier domestic flight operations with Reporting_Airline=DL (NOT the full Delta-marketed network). Exclude canceled and diverted flights for gate arrival/aircraft sequence analysis. Never treat unobserved international or otherwise unreported legs as proof of inactivity.

Data snapshot hashes (unchanged from independently checked KPI pilot):
- January: 868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf
- July: 74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19

## Real-source timestamp and candidate-pair findings

| Quality check | January | July |
|---|---:|---:|
| Scheduled DL records | 76,306 | 94,066 |
| Completed, nondiverted records | 74,025 | 92,245 |
| Valid UTC/local gate reconstructions | 74,022 (99.996%) | 92,245 (100%) |
| Excluded clock contradictions | 3 | 0 |
| Unique reported tails among valid legs | 905 | 891 |
| Consecutive observed same-tail pairs | 73,117 | 91,354 |
| Pairs with matching connecting airport | 72,625 | 90,604 |
| Airport discontinuities | 492 | 750 |
| Negative elapsed ground intervals/overlaps | 0 | 2 |
| Candidate 20-360-minute same-airport ground intervals | 53,047 | 71,881 |
| Median candidate ground interval | 77 min | 74 min |
| Timestamp acceptance | GO | GO |
| Observed connection feasibility | CANDIDATE ONLY | CANDIDATE ONLY |

Method: interpret FlightDate and scheduled gate departure clock in the origin's IANA time zone; add CRS elapsed to obtain scheduled arrival UTC; independently apply DepDelay and ArrDelay to scheduled gate UTC times; check both actual local gate clocks and ActualElapsedTime within one minute. Each reported tail's flights are sorted within each sample by *actual gate departure UTC*. Only consecutive **observed** flights with prior Dest == next Origin and actual ground time 20-360 min are candidate links.

**Unresolved risk:** three January source records still disagree with their expected local scheduled arrival clock and remain rejected; two July same-tail pairs imply physical overlap, and their individual causes were not diagnosed or corrected. Neither should be silently discarded from audit accounting.

## Concrete historical-code quality issue

The uncorrected current-version airport reference omitted historical PBI. This excluded 1,200 January and 1,163 July completed rows from clock validation. The airport's official 2026 notice documents its airport identifier transition from PBI to DJT after our 2025 study dates. A single, fail-on-conflict, 2025-only PBI time-zone exception (America/New_York) recovers those records and passes the same local clock and elapsed cross-checks. No BTS flight or airport code was rewritten. Do not generalize this fix into unspecified code mappings.

Evidence:
- https://www.pbia.org/articles/post/president-donald-j-trump-international-airport-name-change-takes-effect/
- https://www.faa.gov/air_traffic/publications/atpubs/aip_html/part3_ad_2.0_florida.html

## Descriptive delay association — not causal propagation

Among candidate same-tail/same-airport, 20-360-minute observed ground intervals, compare prior flight arrival delayed >=15 minutes versus <15 minutes and the next flight's departure delayed >=15 minutes. Denominators are **candidate paired observations only**.

| Measure | January | July |
|---|---:|---:|
| Candidate pairs with late prior arrival | 9,845 | 15,991 |
| Next departure late in that group | 6,560 (66.63%) | 10,961 (68.54%) |
| Candidate pairs without late prior arrival | 43,202 | 55,890 |
| Next departure late in that group | 4,506 (10.43%) | 8,215 (14.70%) |
| Unadjusted risk difference | +56.20 percentage points | +53.85 percentage points |

Important sensitivity check: among longer **120-360-minute** July candidate gaps, next departures were late in 948/3,280 (28.90%) late-inbound cases versus 3,185/7,885 (40.39%) not-late-inbound cases — the aggregate pattern **reverses** in this selected subgroup. This is a warning against simple 'late inbound causes late outbound' claims.

The comparison is neither a causal estimate nor a whole-airline prediction: airport and route mix, common bad weather, hub congestion, scheduled buffers, changing planned assignments and the **selection of candidate pairs using actual realized ground intervals** can distort associations. No matched counterfactual, regression controls, or external recovery evidence has been established. No estimate of preventable delays or monetary savings is justified.

## Verification and boundaries

The successful GitHub Actions run listed above passed **22 offline tests**, the original independently recomputed SQLite baseline KPI counts, the 2025 source ZIP hash checks, and both timestamp feasibility thresholds. Candidate pair identities and delay-association quadrants were calculated by one transparent implementation with synthetic unit tests; at this earlier checkpoint they had **not yet** had a separate independent real-data SQL reconstruction (completed in the later section). The report preserves counts and denominators for subsequent verification. No raw record, individual tail activity or inferred aircraft location was committed or uploaded.

**Decision:** GO for a *limited descriptive aircraft connection study*, but remain CANDIDATE ONLY for actual rotation completeness and STOP short of causality. Continue with interview-ready SQL/KPI reporting using this evidence rather than a new data pipeline, UI, or ML model. Revisit the 3 clock contradictions, the 2 overlaps and selection limitations before upgrading claims. That preliminary draft was only merged following separate source-data and SQL verification; see final independent section below.

Sources:
- https://transtats.bts.gov/PREZIP/
- https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time
- https://pypi.org/project/airportsdata/20261103/


## Independently reproduced aircraft pairs and delay-association counts

**Verification complete (2026-11-11):** [GitHub Actions run #43092083056](https://github.com/yumorepos/fleet-tracker/actions/runs/43092083056) passed **27 offline tests**, the original independent SQLite flight-level KPI reconciliation, the primary tail-sequence audit, and a **separate actual-source SQLite window-function verifier**.

This independent implementation does NOT call the original tail-pair matching function. It reconstructs gate arrival UTC from observed departure UTC **plus ActualElapsedTime**, cross-checks ArrDelay and destination local clock, sorts same-tail records using SQL `LEAD` within each calendar month, and independently produces candidate-pair counts and all four late-inbound/next-departure quadrants. The verifier fails closed if any original counts, source ZIP hashes, clock exclusions, pair classifications, per-gap-band rates, or medians differ.

| Independently matched count | January 2025 | July 2025 |
|---|---:|---:|
| Valid reconstructed gate records | 74,022 | 92,245 |
| Same-airport candidate connections, 20–360 minutes | 53,047 | 71,881 |
| Candidate pairs with late inbound arrival | 9,845 | 15,991 |
| Next departure late among late-inbound pairs | 6,560 | 10,961 |
| Candidate pairs without late inbound arrival | 43,202 | 55,890 |
| Next departure late among not-late-inbound pairs | 4,506 | 8,215 |

All counts matched the primary implementation exactly for both months. Source ZIP checksums also matched the first BTS data-quality pilot. Only aggregate JSON was retained from the workflow; no individual flight/tail records were committed.

**Interpretation remains bounded:** this is independent arithmetic and pairing validation, NOT independent observation of complete Delta aircraft itineraries, evidence of causal delay transfer, or a validated ability to predict disruption. Descriptive correlations remain susceptible to common conditions, aircraft reassignment, and the actual-ground-gap selection.
