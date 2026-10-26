# T09 CLI argument handling and `--target`

- Plan: `docs/impl-plan.md` Section 2, T09. Depends on: T01, T08. AC-01, AC-04, AC-07; E6, E7, E14.
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved (`resolve_scope` in `docsync/cli.py` as a documented deviation).
- Evidence labels: see `README.md`. Exact date: Not Found ("same session").

## Pre-task: human clarification (same session) [HUMAN][PS]
`docs/impl-plan.md` was NOT modified; the pipeline state supplements the T09 text:
1. Check `has_ambiguity` before `has_candidates`.
2. If all changes are ambiguous, exit 8, not 7.
3. Ambiguity blocks patch generation with and without `--target`.
4. A regression test must verify an only-ambiguous run returns exit 8.

## Attempt 1 [PS][BACKFILL]

### Changes
- `docsync/cli.py`: stub replaced; imports only `os`, `dataclasses`, `docsync.contracts`. Contains `resolve_scope`.
- `tests/test_cli.py` (43 tests).
- `"cli"` added to the `implemented` set in `tests/test_module_boundaries.py`.
- Clarification applied: `resolve_scope` checks `has_ambiguity` first (exit 8, with or without `--target`, even for an invalid target), then `has_candidates` (exit 7). Regression test `AmbiguityTests.test_only_ambiguous_run_is_exit_8_not_7`.
- Target validation rejects empty/NUL, absolute, `..`, non-Markdown, non-candidate, and any path whose `realpath` differs from `<real root>/<target>`. Windows junction tests ran and passed.

### Test results
- `tests.test_cli`: 43 tests, OK, 2 skipped. Full suite: 322 tests, OK, 4 skipped [IMPL]. Python 3.15.0, Windows only. Not re-run by the orchestrator.

### Skipped tests (all four)
1. `tests.test_cli.LinkEscapeTests.test_symlinked_file_pointing_outside_is_rejected`: symlink creation unavailable; symlink escape handling unverified here.
2. `tests.test_cli.LinkEscapeTests.test_symlinked_docs_directory_pointing_outside_is_rejected`: same reason.
3. `tests.test_input.ResolverTests.test_unreadable_directory_real`: Windows chmod.
4. `tests.test_mapping.DiscoverCandidatesTests.test_symlinked_doc_is_not_a_candidate`: symlinks unavailable.
- [ORCH-READ] `tests/test_cli.py:360` and `:374` also contain junction-creation skips; the state says the junction tests ran and passed, so they were not among the four.

### Security findings [SG] (static)
- Verdict: Pass, no critical, high, or medium findings.
- Low: fixed message text is not redacted (user-derived parts are); TOCTOU gap in target validation (T15 must validate before generation, later readers re-check); an ambiguous run with an invalid target exits 8, not 2 (per the clarification); tests use `subprocess` for a local fixed `mklink /J`; `__pycache__` untracked, `.gitignore` Not Found; `docs/codemie/` not inspected.
- Open check: the guardian could not confirm `docs/impl-plan.md` is unmodified for T09.
- `docs/security-audit.md` not written.

### Limitations (preserved)
- Structured fields and paths in `Scope` and typed errors unredacted until output stages redact; `working_tree_reader` has no file-size limit; `main()` and process exit belong to T15 (no end-to-end exit run).

### Verification status
- Unverified by the orchestrator. `docs/impl-plan.md` unchanged for T09: **Not Found** (no shell; the file was already modified earlier by the T05 amendment, so a diff against `2b20313` would not isolate T09; the implementer states it did not edit it). The human can run `git diff docs/impl-plan.md`.

### Human approvals
- [HUMAN] Approved T09 (same session), with `resolve_scope` remaining in `docsync/cli.py` for this task.
- **Documented architectural deviation:** architecture 2.3 and 9a place the Target Resolver in `mapping`; for T09 it lives in `docsync/cli.py` (mapping belongs to approved T08). The approved plan is not reopened. Moving it later is a small change.
- Uncommitted. T10 not started; awaiting the human's authorization.

## Corrections
- None recorded.
