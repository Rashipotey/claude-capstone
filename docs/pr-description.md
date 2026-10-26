# PR: DOCSYNC documentation-impact tool

**Status: Draft PR. The human approved this description, the title and opening a draft PR (2026-10-26), accepting that no security audit exists and F2/F3 are open. Merge is NOT approved.** Detailed history is in `impl-log/`; current step status is in `docs/pipeline-state.md` (it wins on any disagreement).

**Proposed title (needs approval):** `Add DOCSYNC: read-only documentation-impact tool`

## Summary
DOCSYNC reads a Git repository's working-tree and staged changes, finds the documentation files the changed source affects, and proposes documentation edits as one reviewable patch.
- Read-only toward the repository. The only output is `output/docsync.patch`, never overwritten.
- Prints a report and uses distinct exit codes (0 patch written; 2 usage; 3 input/Git error; 4 no changes; 5 over cap; 6 unsupported entry; 7 no doc target; 8 unresolved candidates; 9 validation failed; 10 secret-like hunk withheld; 11 existing patch/write failure; 12 other failure). Values are "Proposed (OQ-2)" in `docs/requirements.md`.
- Generated text is a reason line plus symbol names; insufficient evidence is reported as "Not Found" by design.

## Contents
- `docsync/` package, `tests/` (unittest, standard library only), pipeline documents under `docs/`, `impl-log/`, `.claude/`, `docs/codemie/`.
- `.github/workflows/test.yml`: runs `python -B -m unittest discover -v` on pull requests and manually (ubuntu and windows; Python 3.12 and 3.13).
- `.gitignore` ignores `output/`, `__pycache__/`, `*.pyc`; the 31 previously tracked `.pyc` files are deleted in the working tree.
- All of this is uncommitted at the time of writing.

## Testing evidence
- Last full run (verifier-reported, before the test removal below): 882 tests, OK, 17 skipped, 369.7 s; Python 3.15.0, Git 2.56.0.windows.2, Windows 11. That figure is historical and no longer matches the suite.
- After that run, the 17 skipped tests (16 symlink-dependent, 1 chmod-dependent) were removed at the human's instruction, with their skip-only helpers. No replacement tests were added. The full suite has NOT been re-run since; only a focused run was done (verifier-reported): the six edited test modules, 313 tests, OK, 0 skipped, 84.2 s.
- The symlink-escape guards in the code (`output`, `cli`, `mapping`, `validation`) therefore have no symlink tests; junction and simulated-link tests remain. Linux and Python 3.12/3.13 are untested. The workflow has never run on GitHub (YAML parse Not Found).

## Known limitations and unresolved security findings
- **No complete security audit exists** (`docs/security-audit.md` does not exist). No verification of security is claimed.
- **F1** (secret on the line after its name missed in mixed hunks): partially verified — a narrow form was reproduced and fixed in `docsync/output.py`; focused tests only; not re-audited.
- **F2, F3** (hunk starting on a value line; lowercase run-together names such as `dbpassword`): OPEN, not addressed, no tests. A static read of the code (security-guardian, nothing executed) derived a possible leak for each: F2 needs a name alone on its line, a bare single-token value on the next line, and an edit 4+ lines below; F3 needs a lowercase run-together name whose value has no known token form. Rated Medium by the earlier audit; the reviewer did not rule out High. Both can write a secret value into the patch (AC-08). Neither was reproduced.
- Static review of F1 and M-2 (same reviewer, nothing executed): F1 is handled for the reproduced arrangements, not proven closed for every shape; M-2 is handled for its targeted branch.
- **M-1** resolved by the human-approved removal of size caps; trade-off: memory is bounded only by the input size.
- **M-2** (rollback-failure message) implemented, not independently re-audited.
- Real-symlink behavior is untested (tests removed). Evidence is Windows, Python 3.15.0, Git 2.56.0 only.
- Requirements/design traceability (R1-R14, P1-P13) was not compared with the code. Other Lows are listed in `docs/code-review.md` and `docs/verification.md`.
- Two `test_redact` wall-clock tests failed once in an earlier run (cause unexplained) and have not recurred.

## Human decisions before merge
1. Accept or fix F2/F3 and decide whether F1/M-2 need an audit.
2. Accept the evidence environment, or run the CI workflow.
3. Commit scope (code, docs, `.pyc` deletions, workflow).
4. Approve or change this title and description.
