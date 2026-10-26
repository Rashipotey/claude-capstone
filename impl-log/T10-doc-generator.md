# T10 Doc Generator

- Plan: `docs/impl-plan.md` Section 2, T10. Depends on: T07, T08, T09. AC-02, AC-03; NFR-04, NFR-05; E9.
- Current status: see `docs/pipeline-state.md`. At log creation: **Not started**; awaits the human's authorization.
- Evidence labels and update protocol: see `README.md`. Append only; never delete earlier attempts.

## Carried-forward obligations (from earlier logs) [PS]
- Structured fields (paths, evidence, symbol names) are unredacted upstream; output stages must redact before printing.
- `working_tree_reader` has no file-size limit.

## Entries
### Attempt 1

**Start (2026-10-23)**
- `[HUMAN]` Instruction: implement T10 only, following the approved plan and dependencies; update `impl-log/` at start, after implementation/audit, and after sign-off; run relevant tests and the full suite and report every skip; update `pipeline-state.md` and this log; do not modify unrelated files, start T11, stage or commit; mark T10 "Awaiting sign-off" and stop; stop and ask on any genuine conflict with approved requirements or architecture.
- `[ORCH-READ]` Dependencies T07, T08, T09 are recorded as approved in `docs/pipeline-state.md`. Plan section: `docs/impl-plan.md` T10 (NF-5, D17, D20; AC-02, AC-03; NFR-04, NFR-05; E9).
- Carried-forward T09 note `[PS]`: ambiguous changes (`MappingOutcome.has_ambiguity`) carry no candidate and must not receive an edit.
- Delegated to: implementer (one run, T10 only).

**After implementation and audit (2026-10-23) — status: Awaiting sign-off**
- `[ORCH-READ]` Output files exist: `docsync/generation.py`, `tests/test_generation.py`. The orchestrator has no shell and did not re-run tests or diff.
- Changes `[IMPL]`: `docsync/generation.py` (stub replaced; exports `generate(evidence, mapping_results, target=None)`, `GenerationOutcome(edits, not_found, has_edits)`, `REASON_TEMPLATE`; imports only `dataclasses` and `docsync.contracts`); `tests/test_generation.py` (new, 12 tests); `tests/test_module_boundaries.py` (one edit: `"generation"` added to the `implemented` set).
- Tests `[IMPL]`: new tests 12, OK. Full suite (`python -m unittest discover`) 334 tests, OK, 4 skipped. Unverified by the orchestrator.
- Skipped tests `[IMPL]` (all from earlier tasks; none in T10):
  1. `tests.test_cli.LinkEscapeTests.test_symlinked_docs_directory_pointing_outside_is_rejected` — symlink creation unavailable on this platform.
  2. `tests.test_cli.LinkEscapeTests.test_symlinked_file_pointing_outside_is_rejected` — same reason.
  3. `tests.test_input.ResolverTests.test_unreadable_directory_real` — chmod does not remove read access for directories on Windows.
  4. `tests.test_mapping.DiscoverCandidatesTests.test_symlinked_doc_is_not_a_candidate` — symbolic links not available.
- Coverage `[IMPL]`: Python function gives one minimal edit (reason, symbol, source file); non-Python and missing-evidence sources give Not Found; conflicting sources give one Not Found listing all files and no edit (unrelated sources for the same target still get edits); ambiguous/unmapped/skipped changes get neither edit nor item; empty input gives empty outcome; determinism and input-order independence; inputs not mutated; edits carry only the four `ProposedEdit` fields; bad types raise `TypeError`.
- Security `[SG]` (static review; no tests run, no diff): **Pass**, no critical, high or medium findings. No secrets, no injection text, no external calls or filesystem use, stage-import rule holds, determinism/no-free-text claims hold. Low: (1) reasons, subjects and symbol names embed unredacted paths and identifiers, so T13/T15 need a test that redaction covers `ProposedEdit.reason`, `symbol_names` and `NotFoundItem` fields; (2) the conflict rule treats any shared symbol name (e.g. `main`, `__init__`) as a conflict, suppressing both edits (fails safe). Info: duck-typed evidence is type-checked. `docs/security-audit.md` not written (the guardian has no write tool).
- Implementer choices the plan does not specify, **for the human to accept or reject** `[IMPL]`:
  1. "Conflicting evidence" is undefined in requirements; defined as two files mapped to one target reporting the same changed symbol name, or one path with several evidence records whose symbol sets differ.
  2. One edit per (source, target) pair; fixed reason template `"Source change in <src>: update <target> for the changed symbols"`; symbols sorted and deduplicated.
  3. Evidence is duck-typed (`path`, `symbol_names`) because stages may not import `analysis`; tests use a local stand-in.
  4. Not Found subjects "insufficient evidence for <file>" and "conflicting evidence for <file or target>", sorted by subject then files.
  5. Optional `target=` filters pairs; out-of-scope reporting left to T09/T16.
  6. `generate` does not take `MappingOutcome.ambiguous`; ambiguous changes arrive with no candidate and get no edit.
- Limitations `[IMPL][SG]`: edits carry no file contents or line ranges, so "no unrelated lines" (NFR-05) holds by construction and is checked only as the four-field test; T13 must still confirm it. Structured fields are unredacted (carried forward). `working_tree_reader` still has no file-size limit. `generate` is not wired into `cli` and was not run against real `analysis.analyze` output; compatibility with `FileEvidence` is by attribute names only, so T11/T15 integration is unverified.
- Verification status: tests implementer-reported, not re-run by the orchestrator; security review static only; the claim that only the three listed files changed rests on the implementer's report (no diff possible). Blockers: none. No conflict with approved requirements or architecture was reported.
- Nothing staged or committed. T11 not started.

**Human sign-off (2026-10-23) — status: Approved** `[HUMAN]`
- Decision: T10 approved, with all six implementer choices accepted as documented above, including the fail-safe conflict handling and its potential to suppress valid edits (any shared symbol name between two files mapped to one doc suppresses both edits and lists them as Not Found).
- Limitations preserved and accepted as stated: edits carry no file contents or line ranges (NFR-05 holds by construction; T13 must confirm); structured fields (paths, symbol names, reasons, Not Found subjects) are unredacted until output stages redact them, and T13/T15 need a redaction test covering them; `working_tree_reader` has no file-size limit; `generate` is not wired into `cli` and integration with real `analysis` output is unverified (T11/T15).
- Verification status at sign-off: unchanged from the entry above. Tests (12 new; full suite 334, OK, 4 skipped) are `[IMPL]` only, not re-run by the orchestrator. The security review is `[SG]`, static only. The list of changed files rests on the implementer's report (no diff). The human's approval does not make these independently verified.
- T10 is uncommitted. T11 is not started and needs the human's separate authorization.

<!-- Per attempt: Start (date, human instruction) / Changes / Test results [IMPL] / Skipped tests (each, with reason) / Security findings [SG] / Limitations / Verification status / Human sign-off / Corrections -->
