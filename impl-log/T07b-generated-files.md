# T07b Analyzer: generated and very large file rules

- Plan: `docs/impl-plan.md` Section 2, T07b. Depends on: T07. AC-01; E4 (D13, D14).
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved.
- Evidence labels: see `README.md`. Exact date: Not Found ("same session").

## Attempt 1 [PS][BACKFILL]

### Changes
- `docsync/analysis.py`: `_generated_pattern`; `classify` returns GENERATED; `analyze` skips generated files with a `SkippedFile` reason and a limitation line, with no evidence or symbol work.
- `tests/test_analysis.py`: the T07 test that pinned `yarn.lock`, `dist/app.js`, `a.min.js` as SOURCE was replaced (the only existing test changed). New tests per pattern, lookalike controls, generated `.py`, deleted generated file, a 5,000-line source file stopped by `check_size`, a 1,500-line `dist/` file counted by `check_size`.
- `tests/test_module_boundaries.py` unchanged.

### Test results
- Full suite: 248 tests, OK, 1 skipped [IMPL]. An earlier run had one import error in `tests/test_analysis.py` caused by the implementer's own test code, fixed. Not re-run by the orchestrator.

### Skipped tests
1. `test_unreadable_directory_real` (Windows chmod). [PS]

### Implementer choices beyond the plan (all four accepted by the human)
- `*.lock` and `*.min.*` match the file name at any depth; `dist/**` and `build/**` match only from the repository root (nested `src/dist/x.py` stays SOURCE).
- Matching is case-sensitive and path-only; a bare file named `dist` or `build` does not match.
- Precedence: DELETED and UNSUPPORTED, then GENERATED, then DOCUMENTATION and TEST.
- The skip reason names the matched pattern.
- The plan and requirements give no rules for these (Not Found).

### Security findings [SG] (static)
- Verdict: Pass, no critical, high, or medium findings.
- Low: `*.min.*` is at worst quadratic on a file name (negligible); the comment in `tests/test_module_boundaries.py` line 111 does not mention T07b; untracked `docs/codemie/` (not inspected) and `__pycache__`, `.gitignore` Not Found.
- `docs/security-audit.md` not written.

### Limitations
- Structured fields still unredacted (only limitation lines redacted); `working_tree_reader` has no file-size limit (`MemoryError` not caught).

### Verification status
- Unverified by the orchestrator.

### Human approvals
- [HUMAN] Approved T07b (same session), accepting all four implementer choices. Limitations preserved. Uncommitted. T08 started on the human's instruction.

## Corrections
- None recorded.
