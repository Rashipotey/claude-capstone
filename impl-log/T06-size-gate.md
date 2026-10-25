# T06 Size Gate

- Plan: `docs/impl-plan.md` Section 2, T06. Depends on: T01. AC-01, AC-05; NFR-02; E3, E5.
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved.
- Evidence labels: see `README.md`. Exact date: Not Found ("same session" as the T05 approval, 2026-10-22 per context).

## Attempt 1 [PS][BACKFILL]

### Changes
- `docsync/sizegate.py`: `check_size(files, *, redactor)`.
- `tests/test_sizegate.py` (28 tests).
- `"sizegate"` added to the `implemented` set in `tests/test_module_boundaries.py`.
- Behavior: empty set raises `NoChangesError` (exit 4); over 50 files or over 2,000 added-plus-deleted lines raises `OverCapError` (exit 5); binary, mode-only, submodule and unknown-line-count entries raise `UnsupportedEntryError` (exit 6), checked before the cap.
- Implementer choices beyond the plan: a fourth unsupported kind "unknown line counts"; a rename/copy with a mode change and no content change is refused as mode-only.

### Test results
- Full suite: 211 tests, OK, 1 skipped [IMPL]. Not re-run by the orchestrator.

### Skipped tests
1. `test_unreadable_directory_real` (Windows chmod); not a T06 skip. [PS]

### Security findings [SG] (static)
- Verdict: Pass, no critical, high, or medium findings.
- Low: structured attributes (`.path`, `.entries`, `not_analyzed`) are not redacted, so T15 and report stages must redact them; rename/copy mode-only and status "T" (type change) coverage is a plan gap (fail-closed); `__pycache__` untracked, `.gitignore` Not Found.
- `docs/security-audit.md` not written.

### Limitations
- Unredacted structured fields until output stages redact.
- Plan gap for rename/copy mode-only and type change (fails closed).

### Verification status
- Unverified by the orchestrator.

### Human approvals
- [HUMAN] Approved T06 (same session), accepting both implementer choices. Uncommitted. T07 started on the human's instruction.

## Corrections
- None recorded.
