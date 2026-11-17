# Aviation Portfolio AI Manager v2 — Pilot 01

**Repository:** `yumorepos/fleet-tracker`  
**Setup branch:** `chore/portfolio-manager-v2-pilot-20261116`  
**Pilot purpose:** test whether guided AI review improves the portfolio's evidence clarity and interview usability without extra subscriptions or new infrastructure.

## Authorization and status

The owner approved adding `AGENTS.md`, this pilot plan, and a **read-only** audit on a new branch. No research implementation, README edit, CI dispatch, merge, or public deployment has been approved. Nothing from this pilot should silently change `main`.

## The question

Can a prospective airline operations analyst interviewer understand, reproduce, and defend the strongest Delta BTS results without mixing the validated January/July 2025 reporting-carrier research with the older exploratory OpenSky fleet collector?

## Stage A — read-only audit (approved)

1. Inspect the current `README.md`, `docs/BTS_DELTA_PILOT_2025_RESULTS.md`, `docs/BTS_DELTA_SEGMENT_2025_RESULTS.md`, `docs/BTS_TAIL_SEQUENCE_2025_RESULTS.md`, `docs/BTS_DEPARTURE_BANK_DESTINATION_MIX_2025_RESULTS.md`, and `docs/BTS_RELIABILITY_SQLITE_MART.md`.
2. Inspect the existing test paths and, where accessible, the recruiter-facing case-study source. Compare what is discoverable, independently validated, and feasible to reproduce without collecting more raw data.
3. Identify **one** actual comprehension/reproducibility gap; check whether it is already resolved before proposing a change.
4. Record inspected paths, evidence, limits, proposed next change, tests **not run**, and remaining questions in `docs/AGENT_PILOT_01_AUDIT.md`.
5. Stop and ask for explicit owner approval of the proposed improvement.

## Stage B — implementation (NOT authorized yet)

After owner approval of *specific scope*, prepare one narrowly scoped doc/test change in a new or existing feature branch. Use committed, source-derived aggregates and the existing SQLite validation tests where suitable. Do not alter verified source metrics, claim raw-BTS re-verification from committed fixtures, run paid services, or fetch private data.

Run relevant tests, capture observed output, and prepare a reviewable diff. The current CI entry point is `.github/workflows/tests.yml` (`uv run pytest -v`), but a historical pass is not a substitute for a new run.

## Stage C — independent review (NOT authorized yet)

A fresh review context checks exact code/doc changes against sources, denominators, limitations, and actual test logs. If appropriate, propose a draft PR for human review. **No merge or deployment without owner approval.**

## Acceptance criteria

- Improve one precise recruiter-relevant question, e.g. how to reproduce a verified descriptive KPI locally.
- Preserve Jan/Jul 2025 Delta-reporting domestic scope; do not imply complete fleet history, seasonality, forecasts, causal delay propagation, or savings.
- Clearly separate the aggregate-fixture regression check from original raw-source validation.
- All commands and tests are actually executed or visibly labeled **NOT RUN**.
- No new recurring costs and no changes to `main`.

## Pilot scorecard

| Check | Initial status |
| --- | --- |
| Current source/documentation evidence reviewed | See read-only audit |
| Tests run for this setup | NOT RUN (documentation-only setup) |
| Implementation authorized | NO |
| Independent review of an implementation | NOT PERFORMED |
| Merge / deployment authorized | NO |
| Next decision | Owner approves one bounded improvement or chooses STOP |
