# T05 Git diff retrieval and content-filter preflight

- Plan: `docs/impl-plan.md` Section 2, T05 (amended 2026-10-22, Section 5a). Depends on: T04. AC-01, AC-05, AC-08; E2, E3, E12.
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved with three corrections and documented limitations.
- Evidence labels: see `README.md`.

## Attempt 1 (2026-10-22) [PS][BACKFILL]

### Changes
- Additions to `docsync/gitadapter.py`: `ContentFilterError`, `PreflightUnverifiedError`, `DiffResult`, `EMPTY_CHANGE_SET`, `check_config_listing`, `GitAdapter.preflight()`, `GitAdapter.retrieve_diff()`. The six templates and the environment were unchanged.
- New `tests/test_gitdiff.py` (60 tests).
- Stricter-than-plan preflight refusals added by the implementer (a filter key whose name contains `=` or whose origin has a tab; NUL bytes; repository record must come from a `file:` origin). They only add refusals; later confirmed to match plan conditions 2 to 4.

### Test results
- Full suite: 179 tests, OK, 1 skipped [IMPL]. Git 2.56.0.windows.2 only. Not re-run by the orchestrator.
- Hostile-fixture live controls fired for: external diff driver, textconv, `core.fsmonitor`, user-level configuration, inherited `GIT_*` variables, submodule `core.fsmonitor`/`diff.external`/driver, and all preflight fixtures.
- The smudge control used `git checkout-index` (shows the fixture is live, not that `diff` runs smudge).
- The pager control cannot fire: recorded as NON-EVIDENCE; protection rests only on `--no-pager` being in every vector.
- The older-Git branch of the user-level-configuration check was not exercised.

### Skipped tests
1. `ResolverTests.test_unreadable_directory_real` in `tests/test_input.py` (Windows chmod). T05 added no skips. [PS]

### Security findings [SG] (static)
- Verdict: Pass with one open **High (H1)**: a clean filter defined in a submodule's own configuration runs during `git diff HEAD` even with `--submodule=short`; the preflight reads only the superproject configuration and cannot see it. Found by the implementer with a live control; the known-gap test asserted the marker fires.
- No Medium. Low: error messages include redacted path data; a multi-line-value record can spoof condition 3 only as a false "inspected" signal and cannot hide a filter; `DiffResult.diff_text` is raw and unredacted (T06 onward and the CLI must redact before output).
- Disagreement: implementer said a value containing `x.filter.y.clean=z` is refused; guardian said not refused. Unresolved at the time.
- `docs/security-audit.md` not written.

### Limitations
- See attempt 2 for the final list.

### Verification status
- Unverified by the orchestrator.

### Human approvals
- None at this point. A repository-state discrepancy was noticed: the implementer saw `git log -1` = `2b20313` rather than `43ca0d5`. Something was committed outside the run (see Investigation).

## Investigation (2026-10-22, human request, read-only) [PS]

- Commit `2b20313` "Updated Artifcats" (Rashi Potey, 2026-10-22 16:33:57 +0530, parent `43ca0d5`) was made outside orchestrator and implementer runs, most likely manually (tool Not Found). It contains the five docs and the T01-level `docsync/` and `tests/` files (19 files). T02 to T05 changes were not committed. No content appears lost. No secret-like strings found in HEAD. No `.gitignore`.
- H1 reproduced. The submodule clean filter fires from the raw, numstat and text diff templates (3, 4, 5), not from `ls-files`, `rev-parse` or `config`; firing is timing/racy-stat dependent. `--ignore-submodules=untracked` does not help; `=dirty` and `=all` were quiet in every state tried (Git 2.56.0 for Windows only, not a general proof). `=all` removes the 160000 entry T06/D23 need.
- Preflight review: added refusals match plan conditions 2 to 4. One over-refusal found: a `filter.*` key whose value contains `.clean`, `.smudge` or `.process` followed by `=` or end of line (for example `filter.x.required=run.clean`). Rare, fails safe.
- Conflicting reports resolved: `core.note=x.filter.y.clean=z` is NOT refused; the test asserts `None` and passes (real-repository experiment). The test name and comment wrongly said "refused". Suite re-run by the investigator: 179 tests, OK, 1 skipped.
- T05 held, NOT approved.

## Attempt 2: corrections (2026-10-22) [PS][HUMAN][BACKFILL]

### Human decisions (2026-10-22)
1. H1: amend. Add `--ignore-submodules=dirty` to the shared diff group `D` (templates 3, 4, 5), keeping submodule pointer-change visibility. Limitation: a dirty submodule with an unchanged HEAD may be invisible; security claim qualified to the Windows/Git 2.56.0 evidence.
2. Keep the conservative preflight refusals unweakened; document the known over-refusal.
3. Rename the misleading config-value test and correct its comment.

### Changes
- `docsync/gitadapter.py`: `_D` includes the flag after `--submodule=short`; comments qualified.
- `tests/test_gitadapter.py`: expected `D`; new test that diff vectors without the flag, or with `=all`/`=untracked`, are rejected.
- `tests/test_gitdiff.py`: known-gap test replaced by a regression test (up to 5 fresh-fixture trials plus a live control; recorded as NON-EVIDENCE if the control never fires); new tests that a moved submodule pointer is still reported and that a dirty submodule with an unchanged HEAD is not; config-value test renamed to `test_value_text_that_looks_like_a_filter_key_is_accepted`; new test recording the known over-refusal.
- Approved documents amended by a separate agent on the human's explicit authorization (approval and sign-off text unchanged): `docs/impl-plan.md` (NF-2, T05 `D`, enforced protections, limitations (a) to (c), fixture list, Section 5a entry) and `docs/architecture.md` (Section 7.3, Section 9a).

### Test results
- Full suite: 183 tests, OK, 1 skipped (`test_unreadable_directory_real`) [IMPL]. Control fired in all 5 observed runs; trials needed per run not recorded, so flakiness is not quantified. Pager remains NON-EVIDENCE. `git diff --cached --name-only` empty; `git log -1` = `2b20313`.
- Orchestrator read-only re-confirmation: `--ignore-submodules` present in the five files; renamed test exists at `tests/test_gitdiff.py:616` (as then recorded) [PS]. Suite not re-run.

### Skipped tests
1. `test_unreadable_directory_real` (Windows chmod). No new skips.

### Security findings [SG] (static)
- Audit of corrections: Pass, no critical, high, or medium findings. H1 handled by the amendment, with the stated qualified limitation.
- Low document inconsistencies, listed for the human and not fixed: (1) impl-plan T04 rejected-variants list does not mention the new flag (the test exists); (2) architecture Section 9b still says the plan is "pending human approval" and its T05 row lacks the flag and limitations; (3) the label "over-refusal and over-acceptance" for limitation (c) is misleading; (4) impl-plan "stops Git from examining" submodule content rests on observation only; (5) the regression test passes without evidence if its control never fires in 5 trials; (6) the `gitadapter.py` docstring does not mention the submodule limitation.

### Limitations (final)
- Dirty-submodule invisibility; evidence only on Windows/Git 2.56.0; other execution-capable repository settings are not neutralized (NF-2); no behavioral pager test; conservative preflight over-refusal; raw `diff_text` unredacted until output stages redact it; mode-only change reported only if Git sees it (`core.filemode`); older-Git branch not exercised.

### Verification status
- Unverified by the orchestrator (no shell). Corrections confirmed present by read-only search only.

### Human approvals
- [HUMAN] Restated approval of the three corrections (same session).
- [HUMAN] Approved T05 (same session) with the three corrections and the documented limitations accepted. Uncommitted. T06 started on the human's instruction.
