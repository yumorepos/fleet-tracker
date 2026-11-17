# Aviation Portfolio AI Manager v2 — Pilot 01

**Repository:** `yumorepos/fleet-tracker`  
**Setup branch:** `chore/portfolio-manager-v2-pilot-20261116`  
**Pilot purpose:** test whether guided AI review improves the portfolio's evidence clarity and interview usability without extra subscriptions or new infrastructure.

## Authorization and status

The owner first approved `AGENTS.md`, this pilot plan, and a **read-only** audit on a feature branch. On November 16, 2026, the owner separately approved **one README quick-start for the Delta aggregate-to-SQL tests, relevant test execution, and independent diff review**, still on the isolated branch. A draft PR (#18) may be used to run the pre-existing pull-request test workflow. No research implementation, merge, or public deployment is approved; `main` must remain untouched.

## The question

Can a prospective airline operations analyst interviewer understand, reproduce, and defend the strongest Delta BTS results without mixing the validated January/July 2025 reporting-carrier research with the older exploratory OpenSky fleet collector?

## Stage A — read-only audit (approved)

1. Inspect the current `README.md`, `docs/BTS_DELTA_PILOT_2025_RESULTS.md`, `docs/BTS_DELTA_SEGMENT_2025_RESULTS.md`, `docs/BTS_TAIL_SEQUENCE_2025_RESULTS.md`, `docs/BTS_DEPARTURE_BANK_DESTINATION_MIX_2025_RESULTS.md`, and `docs/BTS_RELIABILITY_SQLITE_MART.md`.
2. Inspect the existing test paths and, where accessible, the recruiter-facing case-study source. Compare what is discoverable, independently validated, and feasible to reproduce without collecting more raw data.
3. Identify **one** actual comprehension/reproducibility gap; check whether it is already resolved before proposing a change.
4. Record inspected paths, evidence, limits, proposed next change, tests **not run**, and remaining questions in `docs/AGENT_PILOT_01_AUDIT.md`.
5. Stop and ask for explicit owner approval of the proposed improvement.

## Stage B — narrow README implementation (approved November 16, 2026)

Under the specific owner approval, make one narrowly scoped README quick-start addition on the existing feature branch. Use committed, source-derived aggregates and the existing SQLite validation tests where suitable. Do not alter verified source metrics, claim raw-BTS re-verification from committed fixtures, run paid services, or fetch private data.

Run relevant tests, capture observed output, and prepare a reviewable diff. The current CI entry point is `.github/workflows/tests.yml` (`uv run pytest -v`), but a historical pass is not a substitute for a new run.

## Stage C — review (authorized for this single README change)

Review the exact documentation diff against sources, denominators, limitations, and actual test logs; if a separate model/reviewer is unavailable, explicitly state that limitation. Draft PR #18 is for test execution and human review. **No merge or deployment without owner approval.**

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
| Tests run for original setup | NOT RUN (read-only audit phase); Stage B CI to be checked on PR #18 |
| README verification quick-start authorized | YES, narrow scope only |
| Review verdict | Pending CI and diff evidence |
| Merge / deployment authorized | NO |
| Next decision | Human decides whether to approve any merge; no automatic merge or deployment |
