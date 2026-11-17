# Delta 2025 paired-day resampling — preregistered analysis protocol

**Status:** Bounded technical extension of the official-source January/July 2025 Delta robustness study. The existing source/KPI and 25-flight matched results are frozen reference checks.

## Decision question

How widely do ATL-origin versus other-origin on-time differences move when **complete operating dates** are resampled rather than treating individual flights as independent? How does retaining short groups of adjacent operating dates change that sensitivity? Which previously identified days have the largest leave-one-date-out influence?

**Expected value:** Defensible resampling design and limitations, data lineage, independently recomputed SQL checks, deterministic algorithms, explicit sample-coverage diagnostics and testable failure behavior.

## Population and definitions

- Only the two previously verified official 2025 BTS January and July ZIP archives, filtered to Reporting_Airline=DL, using the existing SHA-256 source contracts.
- Denominator: noncanceled/nondiverted records with a valid ArrDel15 flag. Numerator: ArrDel15=0.
- Match within destination × scheduled origin-local six-hour departure bank with at least **25 eligible arrivals in each origin group**. Weight matched within-cell rate differences by pooled ATL + other-origin valid arrivals, recalculated after each new date draw.
- Each month is evaluated **separately**. Do not mix the two historical samples.
- Resampling inputs are in-memory daily aggregate counts by FlightDate label, origin group, destination and bank. No individual flights, tails or passenger records in artifacts.

## Prespecified resampling scenarios

Each month has 31 operating-date labels, 1 through 31. Use exactly **300 replicates per month per method**, with deterministic seed **20261116**, totaling **1,200 resamples** across two months and two methods.

1. **iid_day:** draw 31 operating-date labels with replacement from 1–31. Apply exactly the same day multiplicities to both ATL and non-ATL origin groups, maintaining their observed same-day co-variation. Inter-day exchangeability is a methodological assumption, not established by this two-month sample.
2. **moving_block3:** choose overlapping **noncircular length-three consecutive day blocks** uniformly from starts 1–29 with replacement, concatenate until reaching 31 labels and truncate to 31. Some adjacent-date patterns are preserved within blocks; block joins break dependence, the length three is unoptimized, and end-of-month dates receive less sampling weight.

For each replicate, with duplicate-date weights retained, recompute overall valid on-time rates, qualifying destination-bank matched cells, group-specific coverage, matched-cell count, and the pooled-standardized ATL-minus-other gap. If a replicate has no qualifying matched cells, the standardized gap is NULL, not zero.

## Output and interpretation

For each month and method, retain deterministic date draw, SHA-256 fingerprint, and aggregate-only metric values for every replicate. Report empirical nearest-rank **5th, 50th and 95th percentiles**, the number of undefined matched results, counts of positive/negative/zero results, number failing the preexisting 50% coverage gate, and the 5th-percentile group-specific coverage.

These percentile ranges are **conditional resampling stability bands, NOT formal 90% confidence intervals** or p-values. With only 31 dates per month, strong intra/interday operating dependencies, untested stationarity, a purposively selected two-month sample and an arbitrary three-day block length, frequentist confidence coverage is not established. The block method is included as a sensitivity axis, not a validated correction.

The top three influential days are ranked using the **previously independently audited** 31 leave-one-day-out matched comparisons, by absolute shift in the full-month standardized gap. Include both group denominators, each affected day's unadjusted difference and matched-cell counts after its omission. No attributed cause, airport effect, weather event or operational intervention is inferred.

**Research method background:** Künsch-style moving blocks preserve some local temporal structure; formal validity depends on stationarity/short-range dependence and selecting suitable block size. References: https://www.stat.cmu.edu/~cshalizi/ADAfaEPoV/ADAfaEPoV.pdf and https://doi.org/10.1016/S0167-9473(99)00014-6 . These sources do not validate the assumptions of this pilot.

## Engineering, validation and stop gates

- Primary code uses the existing verified daily aggregate ingestion and confirms historical SHA/KPI, bank and standardized 25-flight reference outcomes before publishing.
- A separately implemented SQLite verifier re-reads both official sources, independently recomputes **every one of the 1,200** day-weighted comparisons, regenerates and checks every seeded draw/fingerprint, recalculates every percentile and rechecks influential-date ranking. The source archive is in-memory/transient only.
- Offline synthetic ZIP tests cover duplicated days, missing matched cells, the borderline 25-arrival threshold, day blocks and boundary validity, reproducibility, source drift, output no-clobber safety and detection of deliberate tampering.
- Only PR-scoped or manual GitHub Actions checks; no schedule, secrets, new dependencies, paid services or deployment. Use a 30-minute CI limit, and retain **aggregate-only** outcome artifacts for seven days.
- **GO:** original source/KPI and matched results preserved; all original daily independent SQL tests pass; the new 1,200 independently checked draws, values and summaries match; source and test CI green; full negative and low-coverage cases retained.
- **REVISE/STOP:** any mismatch, incomplete daily source evidence, inconsistent day draws, invalid denominator, impossible on-time/coverage values or unexplained CI failure. No selective removal of inconvenient resamples.

**Explicit limits:** No causal or predictive conclusions; no inference about complete Delta-marketed operations, actual weather/dispatch mechanisms, annual seasonality, staffing requirements, or real monetary savings.
