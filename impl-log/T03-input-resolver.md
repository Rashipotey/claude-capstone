# T03 Input Resolver

- Plan: `docs/impl-plan.md` Section 2, T03. Depends on: T01. AC-05; NFR-02; E1.
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved 2026-10-22.
- Evidence labels: see `README.md`.

## Attempt 1 (2026-10-22) [PS][BACKFILL]

### Changes
- `docsync/input.py`: `resolve_input(repo_path=None, target=None, *, redactor)`.
- `tests/test_input.py` (15 tests).
- `"input"` added to the `implemented` set in `tests/test_module_boundaries.py`.
- Design choice: the redactor is injected by the caller (no default), because stages may not import each other; T15 or the CLI must pass `docsync.redact.redact`. The repository-root check is left to T04.

### Test results
- Full suite: 81 tests, OK, 1 skipped [IMPL]. Not re-run by the orchestrator.

### Skipped tests
1. `tests.test_input.ResolverTests.test_unreadable_directory_real`: real chmod unreadable-path test, skipped on Windows because chmod does not remove read access for directories. A simulated variant runs everywhere. [PS; ORCH-READ: `tests/test_input.py:77` has `skipIf(sys.platform == "win32")`; line 81 also has a runtime skip "running as root".]

### Security findings [SG] (static)
- Verdict: Pass, no critical, high, or medium findings.
- Low/informational: `ChangeRequest.repo_path` holds the unredacted absolute path, so downstream stages must redact it before printing; `__pycache__` untracked, `.gitignore` Not Found.
- `docs/security-audit.md` not written.

### Limitations
- Unredacted `repo_path` in the contract until output stages redact.
- Root check deferred to T04.

### Verification status
- Unverified by the orchestrator.

### Human approvals
- [HUMAN] Approved T03 on 2026-10-22, including the injected redactor and the assignment of the repository-root check to T04. Uncommitted. T04 started on the human's instruction.

## Corrections
- None recorded.
