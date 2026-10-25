# DOCSYNC Code Review (Step 6)

**Status: Approved by the human on 2026-10-26, with documented limitations (see Section 10).** Date of the review: 2026-10-26.

**Provenance of this document.** The `code-reviewer` agent ran the review on 2026-10-26 but has no write tool, so it returned its report as text. At the human's instruction (2026-10-26) the orchestrator transcribed that report into this file. The review content below (findings, severities, evidence lines, test results, limitations, reconsideration candidates) is the reviewer's, transcribed without changes to findings or severities; the orchestrator added only this provenance note, Section 0 (what is not verified) and the "Recommended fix, not implemented" labelling for M-1 and M-2. The orchestrator did not verify any finding, did not run any test and has no shell. Evidence labels: `[CR]` code-reviewer; `[ORCH]` orchestrator.

## 0. What is NOT verified (read this first)
- **Full requirements and design traceability remains UNVERIFIED.** `[CR]` did not read `impl-log/T*.md`, `docs/requirements.md`, `docs/architecture.md`, `docs/design-review.md` or `docs/impl-plan.md`; it relied on module docstrings, `docs/pipeline-state.md` and the test-side tables. Requirements D1-D31 and edge cases E1-E14 were NOT checked one by one against the code, and the architecture and design review were NOT compared with the implementation. The only traceability evidence is the `AC_TABLE` in `tests/test_e2e.py` (AC-01..AC-08 mapped to existing tests, with a self-test), and the file-level observation that every task T01-T16 and T10b has a module and a test file.
- `redact.py` internals were not re-reviewed, and the T13 audit finding F1 was not re-checked.
- Whether every `os.chdir` in the tests is restored in `tearDown`/`finally` was not checked.
- The exact 17 skipped tests were not listed (the suite was not run with `-v`).
- Test results are the reviewer's one run plus earlier implementer-reported results; the orchestrator re-ran nothing.

## 1. Verdict `[CR]`
**Pass with conditions: 0 Critical, 0 High, 2 Medium, 7 Low, 3 Info, plus 2 reconsideration candidates (not counted as defects).**
- The `main` pipeline in `docsync/cli.py` is sound. Expected failures keep their designated exit code, unexpected ones return 12, and rollback after a late failure is implemented and tested.
- No path traversal, command injection or secret leak was found in the code that was read.
- The Mediums are an unbounded-resource gap (M-1) and a misleading stdout claim when rollback fails (M-2).

## 2. Verification performed `[CR]`
- **Read in full:** `cli.py`, `output.py`, `proposal.py`, `input.py`, `gitadapter.py`, `report.py`, `docs/pipeline-state.md`.
- **Read in part:** `analysis.working_tree_reader`, `mapping.discover_candidates`, `contracts.ExitCode`; `redact.py` (function and pattern index only; internals not re-reviewed; T13 audit F1 not re-checked); `validation.py` (I/O grep only: it reads no files, it takes text from the caller; the `realpath` calls at lines 476 and 549 are the link check).
- **Test sources:** grepped for skips, timing, `chdir` and the AC mapping.
- **Not read:** `impl-log/T*.md`, `requirements.md`, `architecture.md`, `design-review.md`, `impl-plan.md` (see Section 0).
- **Test run (once):** `python -B -m unittest discover`, about 324 s. **Ran 841 tests, OK, skipped=17, 0 failures, 0 errors.** This matches the T16 report of 840 plus one.
- **After the run:** `git status` showed only `docs/pipeline-state.md` modified, and there was no `output/` directory.
- **Skips:** the skip reasons in the sources are symlink or junction creation unavailable (about 14), root permissions, file identity reuse, a POSIX-only held-open case, and guards for git not being available. Not run with `-v`, so the exact 17 are not listed.
- **Evidence limits:** Windows, Python 3.15.0, Git 2.56.0 only.

## 3. Traceability `[CR]` (partial; see Section 0)
- `tests/test_e2e.py` has an `AC_TABLE` mapping AC-01..AC-08 to existing tests (lines 958-1096), plus a self-test that fails on an unmapped AC or a nonexistent test. It passed.
- Every task T01..T16 and T10b has a module and a test file. No gap at file level was found.
- Not Found and missing-field cases are covered: no target (AC-04), insufficient evidence (AC-03), proposal skips, and validation not-checked.

## 4. Findings `[CR]`

### M-1 (Medium). Unbounded memory on large Git output and large files.
- `gitadapter.py:397-405` uses `capture_output=True` with no limit. The size gate (`cli.py:541`) runs only after the full `diff HEAD` text was fetched and decoded (`gitadapter.py:508`).
- `analysis.py:336` does `read_bytes()` with no size limit. `proposal.py:287-294` checks `MAX_ORIGINAL_CHARS` only after the whole document was read.
- The reader-side limit (T07, "no file-size limit") is a documented limitation. The Git-side and proposal-ordering parts are not recorded in what the reviewer read (Not Found).
- **Impact:** memory exhaustion before the AC-05 cap (exit 5) can apply. A `MemoryError` would be caught and give exit 12 if memory allows.
- **Recommended fix (NOT implemented; the human decides):** run `--numstat` first and apply the size gate before fetching the diff text; stat the file or read a bounded number of bytes in the reader. (Alternative: record as a documented limitation.)

**M-1 status update (2026-10-26, `[ORCH]`, after the review; the findings above are unchanged):** implemented on the human's instruction and corrected once after a bounded static audit (details: `impl-log/step6-code-review-fixes.md`). Git output is now read in chunks with a 64 MiB cap on stdout (over the cap: the owned child is killed by handle and the run exits 5 with a fixed message) and a 64 KiB cap on stderr; `working_tree_reader` returns None above 4,000,000 bytes. A follow-up correction avoids a possible hang when a descendant process holds the pipe (unbuffered pipes; pipes with a live drain thread are left to the daemon thread; a still-running drain thread after exit fails closed as a timeout). Implementer-reported focused tests: 133 OK (bounds, gitadapter, gitdiff, module boundaries), 74 OK with 1 skip (orchestrator, e2e); the full suite was not re-run; the correction was not re-audited. Known limits that remain: the diff text is still fetched in full up to 64 MiB before the size gate; descendant processes are not killed; peak memory is several times the bound; a Python source above 4,000,000 bytes is read as None; the new descendant tests are timing-based. This update does not change the verdict or approvals.

### M-2 (Medium). The stdout report can say "no patch was written" while a patch remains.
- `cli.py:614-622` ignores the boolean result of `_rollback(token)` and returns `_stop(...)`. That report always says "Run stopped: no patch was written." (`report.py:320`).
- If the delete fails (for example a file held open on Windows), the only warning is a stderr note (`cli.py:498`).
- Exit 12 is correct, but all-or-nothing is not met and the primary output is false.
- This is not a documented limitation.
- **Recommended fix (NOT implemented; the human decides):** when `_rollback` returns False, add a fixed phrase to the report detail ("patch may remain at <path>", the path redacted). Cheapest within approved modules: a change in `cli.py` only, using the existing `message` field of `ReportInput`; the fixed text "Run stopped: no patch was written." in `report.py:320` (approved T14) would still print unless the outcome path is changed, so the human should confirm whether a T14 text change is acceptable. `[ORCH]` note on this last point; the reviewer did not address `report.py:320` beyond citing it.

**M-2 status update (2026-10-26, `[ORCH]`, after the review; the finding above is unchanged):** fixed on the human's instruction with Option A, in `docsync/cli.py` only. When the second report render fails after publish and the rollback also fails, the ordinary report is not printed; one fixed line is emitted instead (`Run stopped: UNEXPECTED. All-or-nothing outcome NOT achieved: a patch may remain at output/docsync.patch.`), the exit code stays 12 and the stderr warning is kept; with a successful rollback the behavior is unchanged. Approved T14 wording and tests are untouched. Implementer-reported focused tests: `test_orchestrator` + `test_cli` + `test_module_boundaries` 99 OK, 3 skipped (symlink); `test_e2e` 32 OK; the full suite was not re-run; the fix was not audited. Details: `impl-log/step6-code-review-fixes.md`. Remaining limit: the emit-failed branches still rely on the stderr note (see L-4).

### L-1 (Low). The git executable is resolved by bare name `git` (`gitadapter.py:369, 398`).
- On Windows, `CreateProcess` also searches the parent's current directory, which is also where `output/` is written. A planted `git.exe` there would run. The environment is scrubbed, but the executable is not pinned.
- Fix: resolve once with `shutil.which` and use the absolute path, or document it.

### L-2 (Low). The document path rule exists in three places with no parity test.
- Copies: `output.py:220-229`, `proposal.py:70-80`, `cli.py:185-214`. The `cli.py` copy is looser: it normalizes backslashes first, while the others reject them.
- A grep of `tests/` finds no test that runs the same inputs through both `ProposedDocument` and `DocumentChange`. Today `DocumentChange` re-checks (`cli.py:577`), so the effect is only a stricter or looser early reject.
- Fix: add a table-driven parity test.

### L-3 (Low). `_groups` (`cli.py:502-510`) repeats the loop in `_mapped_groups` (`cli.py:236-242`). Maintainability only.

### L-4 (Low). Partial stdout write followed by rollback.
- At `cli.py:624-632`, if `write` partly succeeds and `flush` fails, the patch is rolled back but the user may already have seen a "Patch written" report. Exit 12 stands. Very rare.

### L-5 (Low). `working_tree_reader` follows links between in-tree files (`analysis.py:332-337`).
- For example, `docs/x.md` pointing at `src/secret.py` would be read. It is confined to the root.
- In `main` the leak path is closed by three things: `validate_target` and `discover_candidates` exclude links, and the redactor runs on every hunk.
- The helper is public. Document that it is not link-aware, or reject link components. The check-to-read TOCTOU is not closed (a documented class).

### L-6 (Low). `_PHRASES[code]` (`cli.py:442`) would raise `KeyError` if a new `ExitCode` is added.
- `_stop` catches it and falls back (`cli.py:482`), so the exit code is kept. Fix: add a test that `_PHRASES` covers all non-OK codes.

### L-7 (Low). git stderr classification relies on English text (`gitadapter.py:424-431`).
- `LC_ALL=C` is set and this is documented. An unrecognized message becomes a generic `GitCommandError` (exit 3), which is still the designated code.

### I-1 (Info, positive). Patch writer controls.
- Seals: `ApprovedPatch` and `RenderedPatch` are keyed-digest sealed. File creation: exclusive create with `O_EXCL`, `O_NOFOLLOW` and `O_NOINHERIT`. After writing, the guard is re-checked and a misplaced file is removed by identity. Rollback deletes only a regular file whose device, index, size and SHA-256 match (`output.py:885-935`). All of this is tested, including the held-open Windows case.

### I-2 (Info, positive). Git adapter controls.
- Allow-list: exact vector equality (`gitadapter.py:154-163`). Process: `shell=False`, `stdin=DEVNULL`, a timeout, and an environment built from scratch. The repository path is only a `cwd`, never an argument. Options: `--no-ext-diff`, `--no-textconv` and `core.fsmonitor=false` are set, and the content-filter preflight fails closed. No command injection path was found.

### I-3 (Info, positive). Report handling.
- The reporter never receives document text. Free text is capped, control characters are replaced, and secret-like names are replaced whole (`report.py:247-264`). Exception text is never shown (`cli.py:401-422`).

## 5. Documented limitations restated (not counted, not reopened) `[CR]`
- T13 audit Fail record (1 High F1: next-line secret missed in a mixed removed/added hunk; F2, F3), never adopted or re-run. Attempt 8 is unaudited by an accepted audit.
- The unexplained 135 s timing reading.
- T14 Lows F3-F11; T10b Lows; T15 Lows L1-L5 and M2; T16 notes.
- Empty `output/` after rollback; R12 and R14; single-platform evidence.
- Implementer-reported test results. The reviewer re-ran the suite once: 841 OK, 17 skipped.
- The reviewer did not re-verify the redactor against F1.

## 6. Reconsideration candidates (not defects) `[CR]`
- **RC-1.** Wall-clock timing assertions in tests: `test_redact.py:591` (5 s), `test_output.py:1287` (5 s) and `test_validation_links.py:502` (2 s) plus `BOUND`. They use `perf_counter` and may be fragile on a loaded machine. The logs already note "harden the helper (CPU time)" as a recommendation not taken. Evidence here: one clean run.
- **RC-2.** The T13 audit Fail record is the only independent audit of the final redactor and writer. The human may want to decide which record stands before Step 7 relies on AC-08. This is a process question.

## 7. Test quality `[CR]`
- **Isolation:** tests use temp directories and the `tests/helpers/gitrepo.py` fixture. `os.chdir` is used in 5 files: `test_e2e`, `test_gitadapter`, `test_input`, `test_orchestrator`, `test_output`. The run left no stray files. Whether every `chdir` is restored in `tearDown` or `finally` was not checked; a mid-test failure could leak the working directory. A quick audit is recommended.
- **Skips:** they have platform or capability reasons. Real-symlink behavior is untested on this platform, as already known.
- **Mocks:** the Git adapter tests use an injected runner for argument and environment checks. `test_gitdiff`, `test_orchestrator` and `test_e2e` use real Git repositories, so mocks do not hide the integration path.

## 8. Remaining risks `[CR]`
Single-platform evidence; the redactor's known-form limits; TOCTOU windows on `output/` and the target; untested real symlinks; M-1 resource exhaustion; M-2 false report on rollback failure. `[ORCH]` Also: full requirements/design traceability unverified (Section 0).

## 9. Recommendation `[CR]`
Resolve M-2, and decide whether to fix M-1 or record it as a limitation, before Step 8. The Lows can be recorded as limitations. Stop for the human's approval; do not proceed to Step 7 without it.

## 10. Sign-off

**Human approval (2026-10-26, `[HUMAN]`, recorded by the orchestrator):** the human approved Step 6 (Code Review) with documented limitations. The approval does not close, fix, or re-verify any of the items below; they are preserved exactly as stated:
- **RC-2 / T13 audit discrepancy:** a complete audit report with verdict Fail (1 High F1, 2 Medium F2 and F3, 6 Low, 5 Informational) on the T13 Attempt 8 code was never adopted, disproved or re-run; the human described it as interrupted; T13 was approved on 2026-10-25 with this open. Unresolved.
- **Requirements and design traceability remains UNVERIFIED** (Section 0): D1-D31, E1-E14, the architecture and the design review were not compared with the code one by one; the only evidence is the `AC_TABLE` in `tests/test_e2e.py` and the file-level check.
- **M-1 and M-2 fixes were NOT re-audited**, and **the full test suite was NOT re-run after those fixes** (the last full run was the reviewer's 841 tests, OK, 17 skipped, before M-1 and M-2; the post-fix results are the implementer's focused runs only, not independently re-run by the orchestrator).
- All other findings stay as recorded: the seven Low findings (L-1 to L-7), the three Info items, reconsideration candidate RC-1 (wall-clock timing assertions), and every documented limitation of Section 5 and Section 8, including the known limits of the M-1 and M-2 fixes, the unexplained 135-second timing reading, R12 and R14, the single-platform evidence (Windows, Python 3.15.0, Git 2.56.0) and untested real symlinks.
- Step 7 (Verification) is NOT started and needs the human's explicit instruction. Nothing is staged or committed; `docs/codemie/` and `.claude/skills/` must not be committed.

Earlier status line (before the approval): Ready for human sign-off — NOT approved. M-1 has been fixed after the review (see the M-1 status update; correction not re-audited); M-2 has been fixed with Option A (see the M-2 status update; not audited). The seven Low and three Info findings are unchanged and recorded as documented limitations unless the human decides otherwise. The T13 audit discrepancy (a complete Fail report, never adopted or re-run, described by the human as interrupted; T13 approved 2026-10-25 with it open) is documented and unchanged (RC-2). Nothing is staged or committed. `docs/codemie/` and `.claude/skills/` must not be committed.
