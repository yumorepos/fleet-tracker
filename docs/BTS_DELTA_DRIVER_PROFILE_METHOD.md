# Delta BTS origin-segment and reported-delay-cause audit — exploratory

Purpose: make Case Study 2 more operationally useful by comparing ATL-origin
flights with other origins, and using the **carrier-reported LateAircraftDelay**
field to contextualize the separate same-tail gate connection study.

Data contract: official BTS 2025 Reporting Carrier On-Time Performance ZIPs,
Reporting_Airline=DL, January and July separately, original SHA-256 checks.
Use existing Delta KPI pilot to independently verify source totals. No raw
flight-level data are committed. Use only aggregate, non-identifying counts.

Source: BTS Technical Directive #39:
https://www.bts.gov/explore-topics-and-geography/modes/aviation/number-39-technical-directive-reporting-time

Measures:
- Scheduled count; cancellation and diversion / scheduled denominator.
- Arrival on-time = ArrDel15=0 / completed nondiverted with valid ArrDel15.
- Late-arrival population = ArrDel15=1 among completed nondiverted flights.
- Among those late arrivals ONLY, count positive carrier-reported
  LateAircraftDelay and the five reported cause minutes.
- Missing cause detail remains missing, never silently zero.
- Segments: ATL departure/origin airport vs all other domestic
  reported origins. Segments sum to the complete DL population.
- No weather or causal inference and no claim about complete rotations.

Exploratory gate: at least 95% of late arrivals with all five numeric delay
cause fields, 100% reconciliation to original source KPIs, no invalid status
or contradictory arrival delay flags. Rejected source or missing columns
means REVISE, not a repaired estimate.

This is a one-time research step on the existing Fleet Tracker repository,
not a data pipeline, airline forecast, or interactive dashboard.
