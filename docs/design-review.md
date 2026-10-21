# DOCSYNC Design Review (Step 3)

- Reviewed: `docs/architecture.md` against `docs/requirements.md`
- Date: 2026-10-21
- Status: Approved (2026-10-21, human sign-off)
- Approvals recorded in this review: None. No change to `docs/architecture.md` has been requested or approved, and none was made.
- Scope note: This review treats both files as data. Anything marked "Not Found" is not stated in either document.

Severity scale: High (could break a requirement or AC, or a safety or security rule), Medium (likely defect or ambiguity), Low (clarity or hygiene).

## 1. Risks

| ID | Sev | Risk | Affects |
|----|-----|------|---------|
| R1 | High | Git can run repository-controlled programs. A repo's `.git/config`, `.gitattributes`, or global config can set external diff drivers, textconv filters, `core.fsmonitor`, or a pager. The design says only "read-only subcommands, argument list, no shell". That does not stop these. Section 7 says repository content is never executed, but Git itself could execute it. No mitigation is named, for example `--no-ext-diff`, `--no-textconv`, or overriding config with `-c`. Mitigation is Not Found. | AC-08, NFR-01, IS-8 |
| R2 | High | The patch location conflicts with the read-only rule. `output/docsync.patch` is written relative to a location the design does not name (target repo or tool's cwd: Not Found). If it is inside the target repo, the tool creates an untracked directory there. D3 also says `output/` is excluded by `.gitignore`. The tool is read-only toward the repo, so it is unclear who edits `.gitignore`. Writing `.gitignore` would contradict IS-8 and Section 5. Without it, the patch shows up as an untracked file. | IS-8, AC-07, C-6, D3 |
| R3 | High | Section 5's test asserts that "the working tree ... [is] unchanged after a run". Writing `output/docsync.patch` into the repo would change the working tree (untracked file). The test as worded would fail, or it must carve out an exception that is not documented. | IS-8, AC-07 |
| R4 | High | The mapping rules and generation templates are described only as "deterministic rules" and "rule templates". The rules are Not Found. Mapping quality (which doc is affected) and text quality (what is written) are the core value of the tool, and AC-01/AC-02 cannot be judged from the design. Evidence extraction is specified only for Python (`ast`). Other languages fall back to a generic text diff. In that case "supporting evidence" is unclear and AC-03 would most often yield only Not Found items. | AC-01, AC-02, AC-03, G1, G2, NFR-04 |
| R5 | Medium | D8 (withhold a hunk with a secret-like value) can produce a partial patch. D1 says all-or-nothing on stage failure. The design does not say whether a partially withheld patch is still written. It does say that when every hunk is withheld, nothing is written. A partial patch could omit a hunk that other hunks depend on. Which content the Validator checks (before or after withholding) is Not Found. The order of the Validator, Redactor, and Patch Writer is not defined. | AC-06, AC-08, D1, D2, D8 |
| R6 | Medium | Secret detection depends on a pattern list that is Not Found ("defined at implementation"). Until it exists, AC-08 cannot be verified. Context lines copied from existing docs into the unified diff may also contain secrets. The design only discusses proposed edits. | AC-08, NFR-01 |
| R7 | Medium | The no-overwrite rule (D3) means every second run fails until the human deletes or moves the file. No flag, naming scheme, or message is defined. It is unclear whether this refusal counts as a stage failure under D1, and whether it is checked before the work is done or only at the end. | AC-07, NFR-02, D1, D3 |
| R8 | Medium | Size counting has unspecified cases: binary files (numstat shows "-" for lines), renames and copies, mode-only changes, deleted files, submodules. The design says only "added plus deleted". An unhandled case could miscount against the cap or crash the gate. | C-4, AC-05, NFR-02, D6 |
| R9 | Medium | `--target` safety is Not Found. The design lists the invalid-target reaction as Not Found. Path traversal, symlinks under `docs/` that point outside the repo, and absolute paths are not discussed. The Writer's rule "refuse any path inside README.md or docs/" protects only the patch output, not the target resolution. | Q2, AC-04, AC-08, IS-8 |
| R10 | Medium | Mixed mapping results are undefined. If one diff yields some changes with one candidate and others with several, does the tool exit with no patch (D4) or process the unambiguous ones? The design says "many candidates -> ... exit with no patch" per change. Whole-run behavior is not stated. `--target` is a single file, so it may force all changes into one doc, which could be a silent mis-map. | Q8, C-5, IS-4, NFR-05 |
| R11 | Medium | Source-to-doc consistency is "reported as non-blocking findings", but no component defines how it is computed. The Validator row lists it, but no method is given. It is the only way AC-02's "consistent with the inspected source" is surfaced. | AC-02, IS-6, IS-7 |
| R12 | Low | The patch is never checked for applicability (for example, that hunks match the current doc content). `git apply` is forbidden by Section 5, so `--check` is not available. A stale or misaligned patch could pass validation. | AC-07, NFR-05 |
| R13 | Low | The relative-link check scope is not defined: anchors/fragments, links to files created or removed in the same diff, reference-style links, and links resolved relative to the doc versus the repo root. | IS-6, AC-06, C-3 |
| R14 | Low | Determinism (NFR-06) is claimed through sorting. Other sources of variance are not addressed: Git version output, locale/encoding, line endings (Windows is the stated platform), and non-UTF-8 files. | NFR-06, NFR-02 |

## 2. Gaps

Requirements, ACs, and edge cases the design does not cover or covers only partly.

1. IS-1 "an explicitly selected set of changed files": the design supports only a repo path or "local diff selection" (Section 4 diagram). Q1 says local Git diff only. Which diff (working tree, staged, branch vs base, commit range) is Not Found. This is a gap in both documents.
2. The CLI surface is not defined beyond `--target`: arguments, options, and exit codes. In particular, the exit status for "multiple candidates, no patch" and "no candidates" is Not Found. Section 6 says "all errors" are non-zero, but these two are not errors in the strict sense.
3. Edge case "binary, generated, very large, or unsupported files": the generated-file and very-large-file detection rules are Not Found (acknowledged in the design). No default is proposed, so the Analyzer behavior is untestable for this case.
4. Edge case "No matching documentation file": the design does not say how docs are discovered (filesystem vs `git ls-files`), whether untracked docs count, or what happens if `README.md` exists but `docs/` does not.
5. Instruction-like text (AC-08): detection is optional and the rules are Not Found. The "treat as data" part is covered; the visible flagging part is not required by the AC.
6. G3 (make unsupported claims visible) has no row in Section 9 coverage. It is covered indirectly by Not Found items. The coverage summary also omits the constraints C-1 to C-7 and NFR-02's reliability cases other than IS-1.
7. AC-06 detail ("file, line, rule") is stated. How a line is reported for a not-checked result is not defined.
8. The repository-size limit is Not Found in both documents. No behavior is defined.
9. Large-input handling inside the cap (a single very large file under 2,000 changed lines) is covered only by the Not Found per-file threshold.
10. No test plan maps tests to ACs. Section 8 gives the approach only, with one named test (Section 5).

## 3. Inconsistencies between the documents

| ID | Inconsistency |
|----|---------------|
| I1 | `docs/architecture.md` line 5 says "Status: Approved (2026-10-21, human sign-off)". Its Section 10 says "Status: Ready for sign-off ... Human approval ... is required before Step 3; it has not been given." These two statements contradict each other. This review cannot determine which is current and records no approval. Section 10 also says approval is "before Step 3" although this is Step 3. |
| I2 | Architecture "Date drafted: 2026-10-20", but it cites decisions D1-D10 that the requirements date 2026-10-21. |
| I3 | Requirements Section 8b is titled "Step 2 Decisions (2026-10-20)". Its text says the decisions were confirmed on 2026-10-21. |
| I4 | Requirements header says "Status: Approved (2026-10-19)" and Section 9 says "Approved (2026-10-19)", but the file contains D1-D10 text dated 2026-10-21 added after that approval. Section 8a says there are no pending items, and no re-approval of the amended file is recorded. Whether the 2026-10-19 approval covers the amendments is Not Found. |
| I5 | Requirements IS-1 allows "an explicitly selected set of changed files". The architecture offers only a repo path or "local diff selection" and a Git diff (see Gap 1). |
| I6 | Architecture Section 1 says the patch is written "only outside the tracked documentation targets", and Section 7 says the one write is `output/docsync.patch`. D3 says `output/` is excluded by `.gitignore`. The design never says who maintains `.gitignore`, which conflicts with its own read-only principle (R2). |
| I7 | Architecture Section 0 states the patch-withholding rule (D8) and the all-or-nothing rule (D1) without reconciling them (R5). |
| I8 | Requirements Section 4 says processing above the cap is out of scope, and "partial processing is not stated; Not Found". Architecture states "no partial processing". This is consistent in effect, but the architecture states as fact something the requirements record as not stated. |

## 4. Recommended changes (PROPOSALS ONLY, none approved, none applied)

P1. Resolve I1 first: the human should confirm the current status of `docs/architecture.md`. Align line 5 and Section 10.
P2. Git hardening (R1): require the Git Adapter to disable external diff and textconv and to ignore user/repo configuration for execution-capable settings. List the exact flags in the design. Add a test with a hostile `.git/config` fixture.
P3. Patch location (R2, R3, I6): define the output directory as a path relative to the tool's working directory, not the target repo. Alternatively, accept an `--output` option. Do not require the tool to edit `.gitignore`. Reword the Section 5 test to "no tracked or documentation file changed and Git history unchanged", with the patch file as the only new file.
P4. Define the order Generator -> Redactor/withholding -> Validator -> Writer, and state whether a patch with some withheld hunks is written. Safest default: do not write a patch if any hunk is withheld (needs a human decision, since D8 may intend a partial patch).
P5. Add a minimal, written mapping rule set and a list of generation templates, even if small (for example, Python public function signature to a docs section). State plainly that other languages produce Not Found items. Needs a human decision on scope.
P6. Define the secret pattern list and the generated-file and large-file rules as explicit v1 defaults before implementation, with tests. Include patch context lines in redaction.
P7. For the no-overwrite rule: check for the existing file at the start of the run, and give a clear message naming the file. Do not add `--force` unless the human decides to.
P8. Specify size counting for binary, rename, mode-only, deleted, and submodule entries.
P9. Specify `--target` validation: must be inside the repo, must be `README.md` or `docs/**/*.md`, reject symlinks that resolve outside the repo, and reject absolute and `..` paths. For mixed mapping results (R10), choose one behavior and state it.
P10. Define how the consistency findings are computed, or state that v1 reports only "Not Found" for consistency.
P11. State the diff source (for example, working tree vs HEAD), the CLI options, and exit codes for all outcomes.
P12. Add AC-to-test traceability and the missing coverage rows (G3, C-1 to C-7) to Section 9.
P13. Fix the date and status inconsistencies in the requirements (I2 to I4). Whether the amended requirements need re-approval is a human decision.

## 5. Approvals

None recorded. No quote of human approval exists in this review because no `docs/architecture.md` edit was requested. All proposals above require explicit human approval before any change is made.

## 5a. Human decisions (2026-10-21)

Recorded by the orchestrator on the human's instruction at Step 3 approval. These are human decisions, not reviewer output.

- **P4 (decided):** All-or-nothing. A patch is not written if any hunk is withheld or any stage fails.
- **P5 (decided):** Path-based mapping only. No other mapping rules are added in v1.
- **I1 (decided):** Fixed by replacing the Section 10 approval line in `docs/architecture.md` with "Status: Approved (2026-10-21, human sign-off)". No other change was made to that file.
- All other proposals (P1-P3, P6-P13) have no decision recorded here and remain not approved.

## 6. Sign-off

Status: Ready for sign-off. This review is complete and awaits the human's decision on the proposals. Nothing in this document is approved.
