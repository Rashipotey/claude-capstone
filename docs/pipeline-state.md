# Pipeline State

**Current status (2026-10-26):** Steps 1-7 are Approved by the human. **Step 8 (pull request) is a draft, NOT approved; nothing is pushed and no PR exists.** Detail and history live in `impl-log/` (append-only); this file holds current status only, and wins on any disagreement. The earlier long version of this file is in Git history (HEAD) and, for 2026-10-25, `impl-log/archive/pipeline-state.full-2026-10-25.md`; the 2026-10-26 follow-up work is logged in `impl-log/step6-code-review-fixes.md`.

## Steps

| Step | Name | Status |
|------|------|--------|
| 1 | Requirements | Approved (2026-10-22) |
| 2 | Architecture | Approved (2026-10-22) |
| 3 | Design review | Approved (2026-10-21; re-approved 2026-10-22) |
| 4 | Implementation plan | Approved (2026-10-22) |
| 5 | Implementation (T01-T16, incl. T07b, T10b, T11b) | Approved / closed (2026-10-26); each task individually approved |
| 6 | Code review | Approved with documented limitations (2026-10-26) |
| 7 | Verification | Approved as "Pass with conditions" (2026-10-26) |
| 8 | Pull request | Human approved the description, the title and opening a DRAFT PR (2026-10-26), accepting that no `docs/security-audit.md` exists and F2/F3 are open (`docs/pr-description.md`). The PR is opened as a draft; merge is not approved. |

Task logs: `impl-log/T01-...` to `T16-...` (see `impl-log/README.md`). Approved planning documents were amended only on explicit human authorization (details in the T05 and T13 logs).

## Working tree (uncommitted; nothing staged)

- `.github/workflows/test.yml` (pull_request + workflow_dispatch; ubuntu/windows; Python 3.12/3.13; `python -B -m unittest discover -v`). Never run on GitHub; YAML parse Not Found.
- `.gitignore` ignores `output/`, `__pycache__/`, `*.pyc`; the 31 tracked `.pyc` files are deleted.
- M-1 size caps removed (human-confirmed); M-2 truthful rollback-failure line; narrow F1 fix in `docsync/output.py`.
- The 17 skipped tests (16 symlink, 1 chmod) were removed on the human's instruction, with no replacements. Real-symlink behavior is untested.
- `docs/codemie/` and `.claude/` are intentional deliverables and stay tracked.

## Test evidence

- Last full run (verifier-reported, once, before the test removal): 882 tests, OK, 17 skipped, 369.7 s; Python 3.15.0, Git 2.56.0.windows.2, Windows 11. Historical: it no longer matches the suite.
- After the removal only a focused run was done (verifier-reported): `test_input`, `test_mapping`, `test_validation_links`, `test_cli`, `test_orchestrator`, `test_output` -> 313 tests, OK, 0 skipped, 84.2 s. The full suite has not been re-run since.
- Evidence is Windows / Python 3.15.0 / Git 2.56.0 only; Linux and Python 3.12/3.13 are untested.

## Open items (none resolved or claimed compliant)

- **Security:** no complete audit exists (`docs/security-audit.md` does not exist). F1 (secret on the line after its name in a mixed hunk) is partially verified: a narrow form was reproduced and fixed, focused tests only, not re-audited. **F2 and F3 are open.** M-1 is resolved by the approved cap removal (trade-off: memory bounded only by input size). M-2 is implemented, not independently re-audited.
- RC-2: the T13 audit report (Fail; F1-F3, 6 Low, 5 Info) was never adopted, disproved or re-run.
- Requirements/design traceability (R1-R14, P1-P13) not compared with the code; E9 covered at unit level only; D30 partial; D12 has no dedicated test.
- Two `test_redact` wall-clock tests failed once in an earlier run (cause unexplained, not recurred).
- Remaining Lows, T13 implementer choices awaiting accept/reject, and R12/R14 limits are listed in `docs/code-review.md`, `docs/verification.md` and the task logs.
- Reporting "Not Found" when evidence is insufficient is intended runtime behavior, not a design gap.
