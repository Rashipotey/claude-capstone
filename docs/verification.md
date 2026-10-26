# DOCSYNC Verification (Step 7)

**Status: Approved by the human on 2026-10-26 as "Pass with conditions" (see Section 11).** Date of the verification run: 2026-10-26.

**Provenance.** The `verifier` agent ran Step 7 on 2026-10-26 but has no write tool, so it returned its report as text. At the human's instruction (2026-10-26) the orchestrator transcribed it into this file and added (a) this provenance note, (b) Section 9 (the follow-up checks of D12, E9 and E7 made by the orchestrator by reading, with no test run), and (c) Section 10 (corrections to stale documentation statements). The verifier's content in Sections 1-8 is transcribed with its verdict, counts, file/line references and labels unchanged, except that two items are annotated `[ORCH]` where the follow-up check changed the picture (E7, E9). Evidence labels: `[VER]` verifier-reported (not independently re-run by the orchestrator, which has no shell); `[ORCH-READ]` read-only reading by the orchestrator; `[ORCH]` orchestrator note. No test was re-run for this follow-up and no code was changed.

## Verdict `[VER]`: Pass with conditions
- The full suite passed on its single run.
- Markdown and relative links are clean (custom check).
- Two documentation claims were contradicted by what the verifier observed (HEAD hash; "untracked" status of `docs/codemie/` and `.claude/skills/`), plus one stale test count. Corrected in Section 10.
- The known limitations stay open. **Requirements/design traceability is only partly verified: R1-R14 and P1-P13 (architecture and design review items) were NOT compared with the code.**

## 1. Test run (run once, not repeated) `[VER]`
- **Command:** `python -B -m unittest discover -v`, from the repo root, timeout 900 s.
- **Result:** `Ran 864 tests`, `OK (skipped=17)`, 0 failures, 0 errors, exit code 0.
- **Elapsed:** 363.790 s reported by unittest, about 365 s wall.
- **Versions:** Python 3.15.0, git version 2.56.0.windows.2, Windows 11 Enterprise 10.0.26200.
- **Failures:** none.
- **Skipped tests (17):**
  - 16 skipped because symlink creation is unavailable or lacks privilege: `test_cli.LinkEscapeTests.test_symlinked_docs_directory_pointing_outside_is_rejected`; `test_cli.LinkEscapeTests.test_symlinked_file_pointing_outside_is_rejected`; `test_mapping.DiscoverCandidatesTests.test_symlinked_doc_is_not_a_candidate`; `test_orchestrator.StopPathTests.test_dangling_symlink_counts_as_existing_patch`; `test_output.DestinationRaceTests.test_dangling_symlink_to_a_non_docs_target_creates_nothing`; `test_output.ExistingPatchTests.test_dangling_symlink_appearing_between_precheck_and_write`; `test_output.ExistingPatchTests.test_dangling_symlink_counts_as_existing`; `test_output.GuardTests.test_output_symlink_to_docs_is_refused`; `test_output.OutputLinkPolicyTests.test_dangling_symlink_and_symlink_to_a_non_existent_target_are_refused`; `test_output.OutputLinkPolicyTests.test_symlink_to_a_non_docs_directory_elsewhere_is_refused_and_target_unchanged`; `test_output.OutputLinkPolicyTests.test_symlink_working_directory_is_still_resolved`; `test_output.RollbackAndErrorTests.test_rollback_does_not_follow_a_symlink`; `test_validation_links.SecurityTests.test_root_itself_may_be_reached_through_a_symlink`; `test_validation_links.SecurityTests.test_symlink_dir_escape`; `test_validation_links.SecurityTests.test_symlink_file_escape`; `test_validation_links.SecurityTests.test_symlink_inside_root_is_allowed`.
  - 1 skipped with the recorded reason "chmod does not remove read access for directories on Windows": `test_input.ResolverTests.test_unreadable_directory_real`.
- **Consequence:** the symlink guards are not exercised on this machine (policy B for `output`, dangling-symlink handling, `--target` symlink escape). Junction tests that were not skipped did run.
- `[ORCH]` This run supersedes the "full suite NOT re-run after the M-1/M-2 fixes" caveat in the sense that a full run (864 OK) now exists; it is NOT an audit of those fixes, which remain unreviewed.

## 2. Markdown and link validation `[VER]`
- **Tool:** no standard Markdown linter was available (Not Found). A throwaway read-only Python script (`python -B -I`, kept outside the repo) checked UTF-8 decoding, NUL and CR characters, code-fence balance, unterminated or empty link targets, relative links resolved against each file's directory, trailing newline, and exactly one H1.
- **Scope:** 27 files: `docs/requirements.md`, `architecture.md`, `design-review.md`, `impl-plan.md`, `pipeline-state.md`, `code-review.md`, and all 21 `impl-log/*.md` at the time. `impl-log/archive/` was out of scope. (`docs/verification.md` itself did not exist then and was not checked.)
- **Findings: none.** Only `impl-log/README.md` contains links (18 relative links, all resolve). No external links in link syntax; nothing was fetched.
- **Limits:** a purpose-written check, not a CommonMark validator: no table-column, heading-order, reference-style link, anchor or HTML checks.

## 3. Unsupported-claims check `[VER]`

### 3a. SHA-256 values (latest hash quoted in the logs vs the current file; all 12 match)
| File | Log line compared | Result |
|---|---|---|
| `docsync/output.py` `0e1ebf1c…` | `T16-e2e-traceability.md:36` | match |
| `docsync/redact.py` `950d02f4…` | `T13-patch-writer.md:40` (no later value) | match |
| `docsync/contracts.py` `b818ff41…` | `T16:36`, `T14:32` | match |
| `docsync/report.py` `d86461bd…` | `T16:36`, `T15:16` | match |
| `docsync/proposal.py` `8560553f…` | `T16:36` | match |
| `docsync/cli.py` `2db7fdd1…` | `step6-code-review-fixes.md:38` | match |
| `docsync/gitadapter.py` `fb401d19…` | `step6-code-review-fixes.md:43` | match |
| `docsync/analysis.py` `17851021…` | `step6-code-review-fixes.md:26` | match |
| `docs/impl-plan.md` `8557c077…` | `T16:36`, `T15:16` | match |
| `tests/test_e2e.py` `55bc8083…` | `T16:36` | match |
| `tests/test_bounds.py` `8e7bb185…` | `step6-code-review-fixes.md:43` | match |
| `tests/test_orchestrator.py` `354e89a2…` | `step6-code-review-fixes.md:38` | match |

- The older `cli.py` value `75cc6a9a…` that `T16:18,36` call "unchanged" was true when written; the M-2 fix changed the file afterwards (documented in the step 6 log).
- A match shows the file equals the logged value. It does not show the content was reviewed or is correct.

### 3b. Other claims
| Claim | Label |
|---|---|
| `pipeline-state.md:3` said HEAD is `bbe7f4f`; actual HEAD is `fb5dd00` "Step 6: Code Review Completed". | **Contradicted** (stale); corrected in Section 10 |
| `pipeline-state.md:59`, `code-review.md:119`, `T13-patch-writer.md:94` said `docs/codemie/` and `.claude/skills/` are untracked; `git ls-files` shows 19 tracked files under them, added in commit `f0df48b`. | **Contradicted**; corrected in Section 10 |
| `pipeline-state.md:57-58` gave "695 tests, 16 skipped" as the latest full run. | **Contradicted** as the current state (historical T13 figure; current 864 / 17); corrected in Section 10 |
| "Full suite not re-run after M-1/M-2" (`code-review.md` Section 10, `pipeline-state.md` line 3). | Verified as written; superseded by this run (864 OK), which is not a re-audit |
| `code-review.md` says 841 tests, OK, 17 skipped. | Not verifiable here as a historical figure; the suite now has 864 tests (the 23-test increase is consistent with tests added by the M-1/M-2 fixes, not enumerated); skips unchanged at 17 |
| Implementer focused-run counts (133, 74 with 1 skip, 99 with 3 skips, e2e 32). | Consistent indirectly (those tests are inside the 864 run with 0 failures); not re-run separately |
| "Nothing staged." | Verified: `git diff --cached --name-only` empty |
| "Nothing committed." | Not verifiable here: commits exist and the verifier cannot tell who made them |
| `requirements.md:471` and `impl-plan.md:360` say no Git commit records the approval. | Not verifiable here (commits not examined for it) |
| Human "Approved" statements. | Not verifiable here (human acts recorded in text) |
| Evidence limited to Windows, Python 3.15.0, Git 2.56.0. | Verified for this machine; the plan says Python 3.12, which was not tested |
| Line references in `code-review.md` Section 4 (e.g. `cli.py:614-622`). | Not verifiable here (files changed after the review, lines may have moved) |
| The `AC_TABLE` self-test and "mapped earlier tests pass, not skipped" (`code-review.md` Section 3). | Verified: `TraceabilityTests` ran inside the 864 and passed |

## 4. Traceability matrix `[VER]`
- **Method and limits:** evidence from reading `requirements.md`, `impl-plan.md` and `tests/test_e2e.py` (AC_TABLE, EDGE_TABLE, scenarios) and greps of `tests/`. Test references are `file:line` of the `def test_` line. "Covered" means a test exists, asserts the behavior as read, and passed in this run (skips noted). **Most test bodies were not read in full. Architecture and design-review items (R1-R14, P1-P13) were NOT compared with the code.**
- **Modules:** under `docsync/`: `cli`, `input`, `gitadapter`, `sizegate`, `analysis`, `mapping`, `generation`, `proposal`, `validation`, `output`, `report`, `redact`, `contracts`.

### Acceptance criteria
- **AC-01 — Covered.** Modules: gitadapter, analysis, mapping, cli. `test_e2e.py::AcceptanceE2ETests::test_ac01_changed_source_and_affected_documentation_are_reported` (:834); `test_gitdiff.py:641` (staged and unstaged); `test_sizegate.py:30` (50/51 file cap); `test_orchestrator.py::HappyPathTests::test_success_call_order` (:178).
- **AC-02 — Covered.** Modules: generation, proposal. `test_e2e.py::AcceptanceE2ETests::test_ac02_proposal_uses_only_inspected_symbols_and_reports_the_consistency_item` (:844); `test_generation.py::GenerateTests::test_python_function_gives_one_minimal_edit`; `test_e2e.py::RoundTripTests::test_hunks_reproduce_the_proposed_text_from_the_original` (:662). Limit: the text is only a reason line plus symbol names (D20); consistency is Not Found by design (D28).
- **AC-03 — Covered.** Modules: analysis, generation. `test_e2e.py::AcceptanceE2ETests::test_ac03_insufficient_information_is_not_found_and_not_invented` (:856); `test_generation.py:30`; `test_orchestrator.py:224`.
- **AC-04 — Covered.** Modules: mapping, cli. `test_e2e.py::AcceptanceE2ETests::test_ac04_no_documentation_target_creates_no_files` (:870); `test_cli.py::NoCandidateTests::test_zero_candidates_exit_7_without_target`.
- **AC-05 — Covered.** Modules: input, gitadapter, sizegate, cli. `test_e2e.py::AcceptanceE2ETests::test_ac05_empty_unavailable_and_over_cap_inputs_give_a_clear_status_and_no_patch` (:880); `test_input.py:64`; `test_gitadapter.py:344` (no HEAD); `test_sizegate.py:38`, `:187`; e2e scenarios `s_over_cap`, `s_unsupported_entry`.
- **AC-06 — Covered.** Modules: validation, report, cli. `test_validation.py:30`, `:44`; `test_validation_links.py:56-61`; `test_orchestrator.py::StopPathTests::test_failed_validation_exit_9_validates_but_does_not_publish`; `test_e2e.py:894`. A "not checked" result in e2e is produced only by mocking the validator result (`test_e2e.py:322-327`); `test_validation.py:150-173` also covers it.
- **AC-07 — Covered, except the symlink and junction destination variants, which were skipped here.** Modules: output, cli, report. `test_e2e.py::AcceptanceE2ETests::test_ac07_patch_is_the_only_output_and_can_be_inspected_before_accepting` (:901); `test_output.py:557`, `:973`; `test_e2e.py::ReadOnlyTests` (:401, :430).
- **AC-08 — Covered, with the open RC-2 caveat.** Modules: redact, output, report, cli. `test_output.py:319`, `:399`; `test_e2e.py:920`, `:782`, `:819`; `test_redact.py:119`; `test_analysis.py:240`; `test_orchestrator.py:244`. The T13 audit Fail report (F1-F3) was never adopted or re-run; passing tests do not disprove it, and the redactor was not re-reviewed.

### Edge cases
- **E1 — Covered.** `test_input.py:64`, `:71` (simulated unreadable); e2e scenario `s_input_missing_path` (`ReadOnlyTests` :430, expects exit 3). The real unreadable-directory test (`test_input.py:79`) was skipped.
- **E2 — Covered.** `test_gitadapter.py:159`, `:175`, `:344`; e2e scenarios no HEAD, not a repo, content filter (`test_e2e.py:272-285`).
- **E3 — Covered.** `test_gitdiff.py:729`; `test_empty_set_is_no_changes` in `test_sizegate.py`; e2e scenarios `s_no_changes`, `s_untracked_only`.
- **E4 — Covered.** `test_sizegate.py:68`, `:187`; `test_analysis.py:160`, `:190`; `test_e2e.py:937`; e2e scenario `s_unsupported_entry`.
- **E5 — Covered.** `test_sizegate.py:30`, `:38`; e2e scenario `s_over_cap` (`test_e2e.py:299`); `test_bounds.py:85`.
- **E6 — Covered.** `test_e2e.py:870`; `NoCandidateTests` in `test_cli.py`.
- **E7 — Covered `[VER]`; mapping weakness confirmed `[ORCH-READ]`.** `test_cli.py:153`, `:205-234`; e2e scenario `s_unresolved_candidates` (`test_e2e.py:312`). The verifier noted the `EDGE_TABLE` maps E7 to an instructions-as-data test, which is not the real evidence for multiple candidates; see Section 9.
- **E8 — Covered.** `test_validation.py:30`, `:44`; `test_validation_links.py:56-61`; `test_e2e.py:894`.
- **E9 — `[VER]` Partially covered** (no test of conflicting sources was found). **`[ORCH-READ]` Corrected: conflicting sources ARE covered at unit level** by `test_generation.py:42`, `:50`, `:58` (see Section 9); not covered end to end. Other evidence: `test_generation.py:30`, `test_e2e.py:856`, e2e scenario `s_empty_output`.
- **E10 — Covered.** `test_orchestrator.py::UnexpectedFailureTests`; e2e scenarios (`test_e2e.py:346-359`) cover stage, validation and report failures with exit 12 and no patch.
- **E11 — Covered, with the RC-2 caveat for the secret half.** `test_output.py:319`; `test_e2e.py:782`, `:819`; `test_analysis.py:240`.
- **E12 — Covered.** `test_gitdiff.py:707`; `test_e2e.py:929`.
- **E13 — Covered.** `test_output.py:973`; `test_orchestrator.py:314`, `:624`; `test_e2e.py:337`. The dangling-symlink variants were skipped.
- **E14 — Covered.** `test_cli.py:300`, `:306`, `:312`, `:317`, `:338`; `test_e2e.py:261`. The symlink-escape variants (`test_cli.py:380`, `:392`) were skipped.

### Decisions
- **D1** Covered (`test_e2e.py:430`, `test_orchestrator.py:456`). **D2** Covered (failed-validation test; `test_validation.py:30`, `:44`). **D3** Covered (`test_output.py:557`, `:973`, `test_e2e.py:662`); the ".gitignore excludes output/" repo-setup statement has no test (Not Found). **D4** Covered (`test_cli.py:153`, `:108`). **D5** Covered (`test_validation.py:150-173`). **D6** Covered (`test_sizegate.py:44`). **D7** Covered (`test_orchestrator.py:224`, `test_output.py:273`). **D8** Covered, RC-2 caveat (`test_output.py:319`, `:375`). **D9** Covered (`test_report.py:243`, `:266`, `test_validation_links.py:105`). **D10** Covered (the suite is `unittest`; `test_module_boundaries.py:157` rejects third-party imports). **D11** Covered (`test_cli.py:300-338`).
- **D12 — Not covered `[VER]` (Step 7 time; the M-1 caps below were removed 2026-10-26, see the update in Section 9).** No test asserts the absence of a repository-size limit. The M-1 caps (64 MiB Git output, 4,000,000-byte reader) are resource bounds and their relation to D12 is not stated. See Section 9.
- **D13** Covered (`test_analysis.py:160`). **D14** Covered (`test_analysis.py:190`, `test_sizegate.py:68`); the M-1 reader cap mentioned in Section 9 was removed 2026-10-26 (historical at Step 7 time). **D15** Covered for the minimum categories (`test_output.py:64-67` PEM, AWS; key/token/password forms in `test_redact.py`); the final list was left to the T13 tests and RC-2 is open. **D16** Covered (`test_analysis.py:240`, `test_redact.py:119`, `test_mapping.py:170`). **D17** Covered (`test_analysis.py:205`, `test_generation.py:30`). **D18** Covered, imports only (`test_module_boundaries.py:157`; installed packages not checked). **D19** Covered (`test_mapping.py:36-61`). **D20** Covered on one platform (`test_generation.py:80`; `test_e2e.py:558` two fresh fixtures give an identical patch and report); R14 open.
- **D21** Covered (`test_gitdiff.py:641`, `:707`, `:729`). **D22** Covered for the enforced list only (`test_gitadapter.py:58`, `:132`, `:233`; `test_gitdiff.py:125`, `:159`, `:205`, `:214`, `:239`, `:312`); other execution-capable settings are not neutralized per the plan, and the pager has no behavioral test by design. **D23** Covered (`test_sizegate.py:108-120`, `:187`; `test_gitdiff.py:690`, `:697`). **D24** Covered (`test_cli.py:78`, `:408`, `:419`; `test_e2e.py:708`). **D25** Covered (`test_cli.py:152-280`). **D26** Covered (`test_output.py:557`, `:589`, `:604`, `:905`, `:919`; symlink variants skipped). **D27** Covered (`test_validation_links.py:56-148`). **D28** Covered (`test_orchestrator.py:169`). **D29** Covered (`test_orchestrator.py:314`). **D30 — Partially covered** (absolute, `..`, non-Markdown and non-candidate tests ran; the two symlink-escape tests `test_cli.py:380`, `:392` were skipped). **D31** Covered (`test_orchestrator.py:178`, `:244`).

## 5. Git state `[VER]`
- At the time of the verifier's run (historical; documentation files were edited afterwards by the orchestrator, so the current `git status` is not known to the orchestrator, which has no shell): `git status --short` showed only ` M docs/pipeline-state.md`; `git diff --cached --name-only` empty (nothing staged). No `output/` directory. No ignored files.
- **HEAD:** `fb5dd00 Step 6: Code Review Completed`. `[ORCH-READ]` `.git/logs/HEAD` confirms the commit sequence `bbe7f4f` -> `f0df48b` "Step 5: Implementation completed" -> `fb5dd00` "Step 6: Code Review Completed", with the repository owner recorded as author.
- **`docs/codemie/` and `.claude/skills/`:** not untracked; 19 tracked files (for example `.claude/skills/docsync-workflow/SKILL.md`, `docs/codemie/analytics/*.json`), added in `f0df48b` `[VER]`. Whether to untrack them is the human's decision; nothing was done.

## 6. Contradictions and unsupported claims found `[VER]`
1. `pipeline-state.md:3`: HEAD `bbe7f4f`, actual `fb5dd00`. Contradicted. (Corrected, Section 10.)
2. `pipeline-state.md:59`, `code-review.md:119`, `T13-patch-writer.md:94`: `docs/codemie/` and `.claude/skills/` called untracked; they are tracked. Contradicted. (Corrected in the first two; the append-only logs are not edited, Section 10.)
3. `pipeline-state.md:57-58`: "695 tests / 16 skipped" as the latest; current figure 864 / 17. Stale. (Corrected.)
4. Gaps, not contradictions: D12 has no test; E9 "conflicting sources" was not located by the verifier (**located by the orchestrator, Section 9**); the symlink variants of D30/E14/E13/AC-07 could not run here; the EDGE_TABLE mapping for E7 points at a test that does not test multiple candidates.

## 7. Results per acceptance criterion `[VER]`
AC-01 to AC-06: Pass. AC-07: Pass with condition (the symlink and junction destination variants were not exercised on this machine). AC-08: Pass with condition (RC-2 unresolved; the redactor was not re-reviewed).

## 8. Remaining risks and what could not be verified `[VER]`
- **Known limitations, restated and not reopened:** RC-2 (the T13 audit Fail report was never adopted or re-run); the unexplained 135 s timing reading (this run took about 365 s total, no timing test failed); T14 Lows F3-F11, T10b Lows, T15 Lows L1-L5 and M2, T16 notes; the empty `output/` after rollback; the M-1/M-2 fixes are not re-audited (one passing full run is not an audit); R12 and R14; evidence limited to Windows, Python 3.15.0 and Git 2.56.0; real symlinks untested (16 symlink skips).
- **Not verified in this run:** no standard Markdown linter (Section 2 comes from a custom check); the architecture and design review were not compared with the code (**R1-R14 and P1-P13 traceability was NOT verified**); most test bodies were not read, so "Covered" rests on test names, the e2e scenarios and assertions read, and a passing run; the redactor was not checked against the T13 audit findings F1-F3; the wall-clock tests (RC-1) passed once, so flakiness is unknown; Python 3.12, other Git versions and other operating systems are Not Found; side effects outside the repo were not checked beyond `git status` and the absence of `output/`; human approvals cannot be verified from files.

## 9. Follow-up checks by the orchestrator (read-only, no test run, 2026-10-26) `[ORCH-READ]`
- **(HISTORICAL at Step 7 time; the tension below was resolved 2026-10-26 by removing the M-1 caps, see the update at the end of this section.)** **D12 — genuine coverage gap, plus a possible tension.** `docs/requirements.md` C-4 (line 140) and Section 6b.3 (line 174) state there is no repository-size limit and the diff cap is the only limit; Section 6b.3 also states there is no per-file threshold (D14). No test asserts the absence of a repository-size limit (a search of `tests/` for such a test found none). Separately, the Step 6 fix M-1 (human-authorized) introduced a 64 MiB cap on Git output (exit 5) and a 4,000,000-byte cap on `working_tree_reader` (a larger file reads as None and gets no symbol names). These are resource bounds, not repository-size limits, but the reader cap behaves like a per-file threshold and C-4 says "the diff cap is the only limit". No requirement text, plan text or test records this as an accepted deviation of D12/D14; the M-1 caps are documented only in `docs/code-review.md` and `impl-log/step6-code-review-fixes.md`. **Decision for the human:** accept the caps as a documented deviation from C-4/D12/D14 (and say so in the requirements), or revisit. Nothing was changed.
- **E9 (conflicting sources) — covered at unit level; the verifier's "Not Found" is corrected.** `tests/test_generation.py:42` `test_conflicting_sources_list_both_files_and_get_no_edit`, `:50` `test_conflict_does_not_block_unrelated_pairs`, `:58` `test_disagreeing_records_for_one_path_conflict` exist (found by search; the orchestrator did not read their bodies or run them; they were part of the verifier's passing 864-test run). The `docsync/generation.py` module docstring implements the rule (two source files reporting the same symbol for one document give one Not Found item listing all files and no edit). Gap that remains: no END-TO-END test of conflicting sources, and `tests/test_e2e.py` `EDGE_TABLE["E9"]` maps only to the insufficient-information AC-03 test (line 1029) while an e2e scenario with `edges=("E9",)` exercises `s_empty_output` (line 331).
- **E7 — real coverage exists; the `EDGE_TABLE` mapping is weak.** `tests/test_e2e.py:1027` maps E7 to `InstructionsAsDataTests.test_instruction_text_cannot_pick_the_target`, which tests that instruction text cannot select a target, not the multiple-candidates behavior. Real coverage: `tests/test_cli.py:153` `test_two_distinct_docs_listed_exit_8` and `:167`, `:205`, `:217`, `:262`, and the e2e scenario `s_unresolved_candidates` (labelled `edges=("E7",)` at `test_e2e.py:316`, exit 8). Gap: documentation of coverage only (the traceability table points at an unrelated test). Not changed (no tests may be added or edited in this follow-up).
- None of the above implemented any code or added any test.

- **Update (2026-10-26, `[ORCH]`, after this verification; the Step 7 verdict and approval are unchanged):** the M-1 caps discussed in this section, in Section 4 (D12, D14) and in Section 11 were REMOVED on the human's instruction (details: `impl-log/step6-code-review-fixes.md`). Those statements describe the code as the verifier saw it and are historical; the conflict with C-4/D12/D14 is resolved in code (removal confirmed by the human). D12 still has no dedicated test asserting "no repository-size limit" beyond the new no-cap tests in `tests/test_bounds.py` (Not verified by the verifier). Latest runs (implementer-reported, not re-run by the orchestrator or the verifier): focused 288 tests OK (1 skipped); full suite `Ran 882 tests`, `OK (skipped=17)`, about 1790 s. The 864-test figure in this document is the Step 7 run.

## 10. Corrections to stale documentation statements (made 2026-10-26) `[ORCH]`
- `docs/pipeline-state.md`: HEAD `bbe7f4f` replaced by the verified `fb5dd00` (with the commit sequence); the "695 tests, 16 skipped" latest-run line replaced by the Step 7 figures (864 / 17) with the historical figures labelled historical; the "untracked" statement for `docs/codemie/` and `.claude/skills/` replaced by a dated correction; the skip count in the evidence line updated (17: 16 symlink-related, 1 chmod); the Step 7 row and the current-step line updated.
- `docs/code-review.md` Section 10: the statements that Step 7 was not started and that the two directories must not be committed now carry a dated correction; the review's findings and verdict are unchanged.
- `impl-log/*.md` (append-only): the earlier statements that the two directories are untracked (T07, T07b, T09, T13, T14, T15, T16 and README entries) and the historical HEAD `bbe7f4f` references (T11, T11b, T12, T13, T14) were TRUE when written and are NOT edited; they are superseded by commit `f0df48b` / HEAD `fb5dd00` as stated in this section and in `docs/pipeline-state.md`.
- No file was untracked, staged or committed by the orchestrator.

## 11. Sign-off

**Human approval (2026-10-26, `[HUMAN]`, recorded by the orchestrator):** the human approved Step 7 (Verification) as **Pass with conditions**, preserving all documented limitations and the unresolved RC-2. Conditions and open items recorded with the approval (none is closed by it):
- **(Historical, as recorded at the Step 7 approval; resolved 2026-10-26: the M-1 caps were removed and the removal confirmed by the human. The approval itself is unchanged.) D12 / M-1 cap conflict remained OPEN** pending explicit human resolution (Section 9): the M-1 caps (64 MiB Git output, 4,000,000-byte reader) versus requirements C-4, D12 and D14 (the diff cap is the only limit; no per-file threshold). Requirements and implementation were not modified.
- **Tracking discrepancy recorded (since decided 2026-10-26: `docs/codemie/` and `.claude/` are intentional deliverables and stay tracked):** `docs/codemie/` and `.claude/skills/` are tracked (19 files, commit `f0df48b`) although earlier documents called them untracked and asked that they not be committed; they were left unchanged (not untracked, not edited) at the human's instruction.
- **RC-2** (the T13 audit Fail report never adopted or re-run) remains unresolved; the M-1/M-2 fixes remain unreviewed; the 16 symlink-related tests and the chmod test remain skipped on this machine; R1-R14 / P1-P13 traceability remains unverified; E9 has no end-to-end test; the E7 mapping in `EDGE_TABLE` remains weak; D30 is partially covered; all earlier Low/Info findings and limitations stand.
- Step 8 (pull request) is NOT started and needs the human's explicit instruction. Nothing was staged, committed or pushed by the orchestrator; no Git history was changed.

Historical status (superseded by the approval above, kept only for the record): "Ready for human sign-off — NOT approved." It is NOT the current status.

Current status, stated once: Step 7 is approved as Pass with conditions. Nothing in this document or in the approval closes RC-2, the D12 / M-1 cap conflict, the tracking discrepancy, the unreviewed M-1/M-2 fixes, the skipped symlink tests, the unverified R1-R14 / P1-P13 traceability, or any other listed limitation. Step 8 (pull request) is NOT started and needs the human's explicit instruction.
