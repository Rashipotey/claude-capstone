# T04 Git Adapter core

- Plan: `docs/impl-plan.md` Section 2, T04. Depends on: T01. AC-05, AC-08; NFR-02; E2, E11.
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved 2026-10-22.
- Evidence labels: see `README.md`.

## Attempt 1 (2026-10-22) [PS][BACKFILL]

### Changes
- `docsync/gitadapter.py` (only module that runs `git`; allow-list of exactly the six templates and the controlled environment; typed errors; root check).
- `tests/test_gitadapter.py` (38 tests).
- `"gitadapter"` added to the `implemented` set in `tests/test_module_boundaries.py`.
- Timeout: 30 seconds per call. Git tests ran against real temporary repositories (Git for Windows only).

### Test results
- Full suite: 119 tests, OK, 1 skipped [IMPL]. Not re-run by the orchestrator.

### Skipped tests
1. One skipped test, **not** in the Git Adapter tests. At the time its identity and reason were Not Found (the implementer did not check). Later records (T05) identify it as `tests.test_input.ResolverTests.test_unreadable_directory_real` (Windows chmod). [PS]
- Also `tests/test_gitadapter.py:307` contains a conditional skip when the temp directory is inside a Git repository [ORCH-READ]; whether it fired is Not Found.

### Security findings [SG] (static)
- Verdict: Pass, no critical, high, or medium findings.
- Low: the not-a-root message includes the redacted resolved path; `environment=` and `executable=` are injectable and must not be exposed by the CLI (check in T15); `__pycache__` untracked, `.gitignore` Not Found.
- `docs/security-audit.md` not written.

### Limitations
- No-HEAD surfaces only as `NoHeadError` from a failing `diff HEAD`, recognized from English Git stderr (`LC_ALL=C`). The repository path is the call's `cwd`, never an argument.
- No behavioral pager test is possible (plan).

### Verification status
- Unverified by the orchestrator.

### Human approvals
- [HUMAN] Approved T04 on 2026-10-22 with the current design and documented limitations accepted. Uncommitted. T05 started on the human's instruction.

## Corrections
- None recorded for T04 itself. (T05 later changed the shared diff group in this module; see T05.)
