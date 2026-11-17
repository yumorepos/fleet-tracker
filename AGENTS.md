# Fleet Tracker — Evidence-first AI agent instructions

These instructions apply to AI coding assistants working in `yumorepos/fleet-tracker`. They are workflow guidance, **not** a trained model or an autonomous background service.

## Goal and boundaries

Make the existing airline operations analytics portfolio easier to inspect, reproduce, and defend in interviews. Prefer a small, verifiable change over a new dashboard, new dataset, speculative forecast, or additional agent infrastructure.

- The flagship study uses **January and July 2025 BTS U.S. domestic Reporting Carrier On-Time Performance records**, filtered to `Reporting_Airline=DL`. It is **not** the full Delta-marketed network or a continuous fleet history.
- For population, exclusions, source hashes, denominators, and validations consult `docs/BTS_DELTA_PILOT_2025_RESULTS.md` and `docs/BTS_DELTA_SEGMENT_2025_RESULTS.md`.
- For aircraft timing and connection claims consult `docs/BTS_TAIL_SEQUENCE_2025_RESULTS.md`. Observed same-tail/same-airport links are **candidates**, never certified rotations. Delay association is **not** causal propagation.
- For scheduled departure periods and selected shared-destination comparison consult `docs/BTS_DEPARTURE_BANK_DESTINATION_MIX_2025_RESULTS.md`. Its six-hour bins are analytical bins, not verified airline-defined hub banks; its standardized subset is not a controlled causal comparison.
- For aggregate-to-SQL reproducibility consult `docs/BTS_RELIABILITY_SQLITE_MART.md`. Committed aggregate fixtures are not a new independent rehash of raw BTS records.
- The older OpenSky/aircraft collection prototype is a separate exploratory surface, not a production fleet-monitoring service.
- Do not edit or describe results for other repositories without separate authorization. In particular, preserve the frozen conclusions in `network-lab`.

## Workflow: normally sequential, four roles

1. **Portfolio manager:** define one interview-relevant question, source of truth, acceptance criteria, and a STOP decision; request approval for the *specific* implementation.
2. **Evidence auditor:** inspect current repo files and historical validation evidence. Track sample, data grain, definitions, denominators, units, missingness, source vintage, caveats, and possible contradictory statements. Initial audit is strictly read-only.
3. **Implementer:** only after scope approval, work on an isolated feature branch. Keep the diff small. Run relevant tests and provide exact commands, exit codes, and limitations.
4. **Independent reviewer:** preferably use a fresh context to compare the source evidence, actual diff, and tests. Report PASS / CHANGES REQUIRED / INSUFFICIENT EVIDENCE; do not rubber-stamp an implementer's description.

## Hard safeguards

- **Never change `main` directly. Never merge, deploy, trigger paid services, publish new material, or enable automated collection without explicit owner approval.**
- Initial Pilot 01 permits agent configuration and audit notes only. It **does not** authorize edits to research code, validated numbers, README, the public case study, or workflows.
- Do not download large raw BTS archives in an initial audit, start collectors, or request OpenSky/API credentials.
- Do not expose proprietary employer data, passenger records, personal data, credentials, tokens, or ignored/raw flight datasets.
- Do not invent test results, independent verification, source evidence, financial savings, operational interventions, or predictive benefit.
- Do not confuse an existing documentation claim of CI PASS with tests actually executed in this session.
- Existing published results are evidence with stated scope, not permission to generalize to new months, airlines, or operational decisions.

## Required handoff

- Business question and why recruiters should care
- Evidence reviewed (exact files/paths, denominators, verified scope, limitations)
- One proposed change and acceptance criteria, or STOP
- Files changed (or **NONE** for read-only audit)
- Tests run: exact command and observed result, or **NOT RUN**
- Independent review verdict and unresolved questions
- Explicit next human approval needed

Pilot: `docs/AGENT_PILOT_01.md`.
