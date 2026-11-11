# BTS Delta aircraft-sequence feasibility: Jan and Jul 2025

This is a bounded research gate, not a full aircraft utilization dashboard.
It reuses official BTS Reporting Carrier On-Time Performance monthly archives with
the exact source SHA-256 checksums validated by the preceding flight-level pilot.
The reported carrier selection is DL and is not all Delta-marketed services.

## Clock reconstruction

BTS 2025 Technical Directive #39 (BTS public website) states that reported gate
departure/arrival clock times are local to each airport; actual and CRS elapsed
minutes compensate for timezone differences. FlightDate belongs to the scheduled
operation date, and operations that cross a month boundary are reported in
the month they begin.

This pilot maps IATA airport codes to IANA zones with pinned
airportsdata==20261103 (MIT license). Mapping is a reference to be tested,
not an official BTS airport mapping.

For each completed (not canceled, not diverted) DL record:
1. Scheduled departure UTC is FlightDate plus CRSDepTime in the origin timezone.
   A clock time 2400 is the next local midnight.
2. Scheduled arrival UTC is scheduled departure UTC plus CRSElapsedTime;
   cross-check the destination local CRSArrTime.
3. Reconstruct actual gate UTC timestamps by adding DepDelay and ArrDelay
   independently to the corresponding scheduled UTC times.
4. Check the published local DepTime and ArrTime (1-minute tolerance)
   and ActualElapsedTime against the difference in reconstructed gate UTC.
5. Explicitly count and exclude missing/ambiguous or contradictory clocks,
   time zones, elapsed minutes, and tails. No guessed repairs.

## Candidate same-tail connection

Group valid completed flights by reported tail within January and July
separately. Sort by actual gate departure UTC. Pair *consecutive observed*
departures of a given tail and classify:
- Airport mismatch between prior destination and next origin.
- Overlap (next departure before prior arrival).
- Same-airport gap shorter than 20 minutes.
- Candidate same-airport nonoverlapping gap 20 to 360 minutes.
- Same-airport gap 6 to 24 hours, or longer than 24 hours.

The 20- and 360-minute bounds are *analyst-selected screening filters*,
not published airline legal minimum turns or operating policy. A
candidate matching pair is an observed partial-flight-record relationship,
not proof of all intermediate flights or a complete physical rotation.
The rate denominators must always refer to the sample of DL flights.

Predefined timestamp acceptance requires >=98% of completed DL rows pass
source-clock/timezone/actual-elapsed consistency checks in EACH month;
candidate-only link screening requires >=500 candidate pairs and <=0.5%
overlap among same-airport observed consecutive pairs in each month.

## Limitations and claims

BTS reporting excludes many international, transborder and otherwise
nonreportable segments, and completed-only filtering removes cancellations
and diversions. An aircraft may operate additional unobserved flights.
January and July are distinct samples, never one continuous sequence;
first and last observations in each month are left/right-censored.
Tail codes and reference timezone mapping can be incomplete or erroneous.
Do not claim full fleet use, actual maintenance, causal delay propagation,
verified operational minimum turns, or complete rotations.

Only per-month aggregated quality statistics and counts may appear in
this repository; original flight/tail rows stay in ephemeral CI storage.
Review the artifact and draft PR before any publish/merge decision.

Sources:
- https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time
- https://transtats.bts.gov/PREZIP/
- https://pypi.org/project/airportsdata/20261103/
