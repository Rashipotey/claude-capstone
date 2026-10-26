# T08 Doc Mapper

- Plan: `docs/impl-plan.md` Section 2, T08. Depends on: T01, T07. AC-01, AC-04; E6, E7.
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved (MEDIUM-1 corrected).
- Evidence labels: see `README.md`. Exact date: Not Found ("same session").

## Attempt 1 [PS][BACKFILL]

### Changes
- `docsync/mapping.py`: `discover_candidates(repo_root)`, `map_changes(files, candidates)`, `MappingOutcome`, `module_name`, `NO_SUITABLE_TARGET_MESSAGE`.
- `tests/test_mapping.py` (25 tests).
- `"mapping"` added to the `implemented` set in `tests/test_module_boundaries.py`.
- Only SOURCE files are mapped; T09 owns the exit 7 decision (the mapper exposes `has_candidates`).

### Test results
- Full suite: 273 tests, OK, 2 skipped [IMPL]. Not re-run by the orchestrator.

### Skipped tests
1. `test_unreadable_directory_real` (existing, Windows chmod).
2. `tests.test_mapping.DiscoverCandidatesTests.test_symlinked_doc_is_not_a_candidate`: symlink creation unavailable here, so the symlink-skip behavior is untested in this environment. [PS; ORCH-READ: `tests/test_mapping.py:223`]

### Implementer choices beyond the plan
1. Categories come from `ChangedFile.category` (no import of `analysis`); an UNCLASSIFIED file raises `ValueError`.
2. DELETED and UNSUPPORTED files also get a skipped result.
3. Several docs sharing one lowercased stem: first by code-point order picked silently. **Rejected, see MEDIUM-1.**
4. A root-level `__init__.py` has module name `__init__`.
5. `map_changes` raises `ValueError` for a candidate that is not `README.md` or `docs/<name>.md`, and `TypeError` for wrong types.
6. `docs/*.md` requires a name longer than `.md`.
7. A symlinked `docs` directory is skipped.
8. Result paths stay unredacted (documented limitation).

### Security findings [SG] (static)
- Verdict: Pass, no critical or high findings, **one MEDIUM (MEDIUM-1)**: choice 3 silently selects among several matching docs (`by_stem.setdefault`; test `test_docs_differing_only_by_case_pick_lowest_path_deterministically` locks it in). This conflicts with the plan's "Never select among several", "at most one candidate per change" and T09's "the tool never selects a target" (E7). It can occur only on case-sensitive filesystems.
- Low: a Windows junction `docs` directory is not detected by `os.path.islink` (T09 target validation must resolve paths); small TOCTOU gap between `islink` and `scandir`; `README.md` matching is case-sensitive per the plan; exceptions echo unredacted candidate strings via `%r`; `__pycache__` untracked, `.gitignore` Not Found.
- `docs/security-audit.md` not written.
- The orchestrator could not diff the T08 change set (no shell).

### Verification status
- Unverified by the orchestrator. Status at end of attempt: Ready for sign-off, NOT approved, with MEDIUM-1 awaiting the human.

### Human approvals
- None yet at this point.

## Human decision on MEDIUM-1 (same session) [HUMAN]
- Option (b): when several documentation candidates match the same lowercased stem, the mapper must report the ambiguity and never select among them; tests must prove ambiguous matches are not silently resolved; change limited to T08 and its tests.
- Choices 1, 2, 4, 5, 6, 7 and 8 accepted. T08 not approved yet; correction run and re-audit started.

## Attempt 2: MEDIUM-1 correction [PS][BACKFILL]

### Changes
- `docsync/mapping.py` and `tests/test_mapping.py` changed; `docsync/contracts.py` not changed (per implementer; the guardian could not diff).
- `MappingOutcome` gains `ambiguous` (tuple of `(source_path, sorted tuple of matching docs)`, sorted by source path) and `has_ambiguity`. An ambiguous change gets a `MappingResult` with no candidate and no skip reason, is excluded from `unmapped`, its docs are not added to `candidates`, and there is no README fallback for it.
- Docstring updated; stale "T09 not yet implemented" line fixed.
- The test that locked in silent selection was removed. Seven new tests: shared stem; no README fallback; input-order independence; non-ambiguous neighbours unaffected; different stems; duplicate candidate entry is not ambiguous; several ambiguous changes.

### Test results
- `tests.test_mapping`: 31 tests, OK, 1 skipped (symlink creation unavailable). Full suite: 279 tests, OK, 2 skipped [IMPL]. The second skip was not identified by the implementer; most likely the existing Windows chmod skip, not confirmed. Not re-run by the orchestrator.

### Skipped tests
1. `tests.test_mapping...test_symlinked_doc_is_not_a_candidate` (symlinks unavailable).
2. A second skip, not identified (probably `test_unreadable_directory_real`).

### Security findings [SG] (static, re-audit)
- Pass; MEDIUM-1 resolved; no critical, high, or medium findings. Limitations preserved.
- Unverified: no git diff was possible, so "only `mapping.py` and `test_mapping.py` changed in this correction" rests on the implementer's report.

### Note carried to T09
- `has_ambiguity` must map to the E7 refusal (exit 8) and be checked before `has_candidates`; `docs/impl-plan.md` T09 text did not say so. Recorded as a human clarification in the pipeline state (see T09).

### Human approvals
- [HUMAN] Approved T08 (same session) with MEDIUM-1 option (b) and the seven accepted choices. Preserved limitations accepted: unredacted structured fields and result paths; junction `docs` directory not detected by `islink` (T09 must resolve paths); exceptions echo candidate strings via `%r` (CLI must redact); TOCTOU gap between `islink` and `scandir`; `README.md` matching case-sensitive; `working_tree_reader` still without a file-size limit; symlink test skipped where unavailable. Uncommitted.
