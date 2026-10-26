# T07 Change Analyzer

- Plan: `docs/impl-plan.md` Section 2, T07. Depends on: T01. AC-01, AC-03; NFR-04; E4, E9, E11.
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved.
- Evidence labels: see `README.md`. Exact date: Not Found ("same session").

## Attempt 1 [PS][BACKFILL]

### Changes
- `docsync/analysis.py`: `analyze(files, diff_text, *, redactor, read_text=None)`, `classify`, `parse_diff_sections`, `extract_python_symbols`, `working_tree_reader(repo_root)`.
- `tests/test_analysis.py` (33 tests).
- `"analysis"` added to the `implemented` set in `tests/test_module_boundaries.py`.

### Test results
- Full suite: 244 tests, OK, 1 skipped [IMPL]. Not re-run by the orchestrator.
- The interpreter was reported as Python 3.15.0 while the plan says 3.12; no 3.12 check was made. Git 2.56 on Windows only; `diff.noprefix` and `diff.mnemonicPrefix` tested only as parsing, not against a real repository.

### Skipped tests
1. `test_unreadable_directory_real` (Windows chmod); not a T07 skip. [PS]
- `tests/test_analysis.py:313` has a class-level `skipUnless(git_available())` guard [ORCH-READ]; whether it fired is Not Found.

### Implementer choices beyond the plan (all seven accepted by the human)
1. The Analyzer also assigns DOCUMENTATION, TEST and DELETED; GENERATED not assigned until T07b, so `yarn.lock`, `dist/app.js`, `a.min.js` came out as SOURCE for now.
2. Any unclassified text file is SOURCE; non-`.py` files get generic evidence plus a limitation; UNSUPPORTED means status `T` or a binary/NUL section.
3. Symbols from `ast` over an injected `read_text`; `working_tree_reader` is read-only, UTF-8, root-confined, and T15 must pass it; symbols of deleted-only functions are not found.
4. Missing evidence yields empty symbols plus a note, not an exception.
5. Header paths tolerate one-segment prefixes and C-style quoting.
6. `has_source_files` is exposed; T15 maps it to exit 4.
7. Only `limitations` pass through the redactor.

### Security findings [SG] (static)
- Verdict: Pass, no critical, high, or medium findings.
- Low: structured fields (`path`, `evidence`, `skipped`, symbol names) unredacted, so T15 and report stages must redact; `working_tree_reader` has no byte limit; `ast.parse` handling omits `MemoryError`, `_definitions` recursion is outside the try block (an uncaught `RecursionError` could abort `analyze`), and `SyntaxWarning` text could reach stderr unredacted; small TOCTOU gap between resolve and read; symlink-escape and absolute-path cases untested; `__pycache__` untracked, `.gitignore` Not Found.
- `docs/codemie/` untracked and not reviewed (relation Not Found).
- `docs/security-audit.md` not written.

### Limitations
- As listed under security findings; accepted by the human as stated.

### Verification status
- Unverified by the orchestrator.

### Human approvals
- [HUMAN] Approved T07 (same session), accepting all seven implementer choices. Documented limitations preserved and accepted, especially unredacted structured fields and no file-size limit in `working_tree_reader`. Uncommitted. T07b started on the human's instruction.

## Corrections
- None recorded. (T07b later replaced one T07 test; see T07b.)
