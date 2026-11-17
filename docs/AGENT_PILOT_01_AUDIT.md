# Pilot 01 — Read-only evidence audit

**Audit date:** November 16, 2026 (North America)  
**Scope:** inspection of existing GitHub files and recruiter-facing site source. No source-code changes, raw-data downloads, credentials, collector jobs, or tests were run in this audit.

## Current evidence verified through repository documents

- `README.md` clearly separates **verified Delta domestic reporting-carrier research** from the older **exploratory OpenSky collector**, but its **Running locally** section is centered on `uv sync`, `uv run pytest`, and the credential-requiring OpenSky collector.
- `docs/BTS_DELTA_PILOT_2025_RESULTS.md` records **76,306** January and **94,066** July 2025 scheduled DL-reporting rows, with descriptive arrival punctuality **80.68%** and **75.16%**, respectively. These are non-canceled/non-diverted records with valid arrival flags; cancellations have scheduled-record denominators. The source document reports independent SQLite count reconciliation and source-archive hash checks.
- `docs/BTS_TAIL_SEQUENCE_2025_RESULTS.md` reports **53,047** January and **71,881** July same-tail/same-airport candidate links, within a 20–360 minute observed ground gap. Its published results explicitly identify 3 January clock contradictions and 2 July physical overlaps; reported independent SQL reproduction does not establish true complete aircraft rotations or causal delay propagation.
- `docs/BTS_DEPARTURE_BANK_DESTINATION_MIX_2025_RESULTS.md` (November 16) reports independently reproduced analytical 6-hour origin-local bins and a selected shared-destination × bin standardization. Its matched subset excludes material portions of flights and cannot support route-level causal conclusions.
- `docs/BTS_RELIABILITY_SQLITE_MART.md` documents a validated **aggregate-to-SQL** reporting layer and an existing committed `tests/fixtures/bts_dl_2025_verified_aggregates.json` fixture. It warns that comparing saved hashes is **not** independently rehashing the original BTS ZIP archives.
- Repository tree includes `tests/test_bts_reliability_accepted_aggregates.py`, `tests/test_bts_reliability_mart.py` and `.github/workflows/tests.yml`. Their presence was inspected; they were **not run**.
- The source for `yumorepos.github.io/airline-operations.html` already contains Jan/Jul KPIs, denominator explanations, candidate-connection warnings, the selected departure-bank follow-up, and its caveats. **Do not propose duplicating that existing content.**
- Public GitHub PR #16 for the departure-bank follow-up is **merged**. PR #10 for airline-press collection is **closed and unmerged**, consistent with the README's warning not to call it production-ready.

## Finding — one narrow opportunity

**Recruiter reproducibility gap (documentation discoverability, not a demonstrated numerical defect):** The repository promotes the Delta/SQLite evidence first, but the first local command example after `uv run pytest` is an **OpenSky collector requiring credentials**, rather than a clear **credential-free verification path for the flagship Delta aggregate reporting layer**. A reviewer may mistake the OpenSky collector for the way to reproduce the historical KPI work.

This is a navigation/first-impression risk, not evidence that the analysis fails to reproduce. The existing SQLite docs and tests appear to offer a lower-friction route, but an exact working command must be established during the approved implementation rather than guessed.

## Single proposed follow-up (NOT YET APPROVED)

Add a small **'Verify the Delta reporting case study offline'** block near the top of `README.md`, linking the already validated source reports and providing a tested command for the existing accepted-aggregate/SQLite tests (only after a real local run). Explain:

1. what the committed aggregate fixture verifies;
2. that it does **not** re-download/re-verify the raw BTS archives; and
3. where manual official-source rebuild/verification lives for analysts seeking full reproducibility.

No new dashboard, no new KPI, no new dataset, no editing of site or source calculations.

**Provisional definition of done:** A fresh clone can follow an accurately tested, credential-free verification step and see precise limitations without mistaking it for raw-source independence. Existing suite still passes, with observed command output logged.

## Constraints / open items

- This audit inspected repository source and documentation remotely. It **did not** execute `uv sync`, `uv run pytest`, any SQLite builder, or a source-archive validation workflow. The docs report past successful runs; no new passing CI result is claimed.
- No independent re-computation of the published data was done in this pilot audit.
- Before implementing, inspect the exact tests to choose the shortest working offline command; then seek explicit owner approval for the README-only change and any necessary test-only support.
- **Current status: STOP at proposal. Await owner approval.**
