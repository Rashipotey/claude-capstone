# DOCSYNC Requirements (Step 1)

- Source: `input/user-story-docsync.md` (DOCSYNC-101, fictional, status "Proposed - pending clarification")
- Date drafted: 2026-10-19
- Last revised: 2026-10-22
- Status: Approved (2026-10-22, human sign-off on this revision, including the proposed defaults in Section 8c as written).

How to read this file:

- Sections 1 to 7a are the requirements: story, goals, scope, acceptance criteria, constraints, behavior rules, edge cases, and traceability. Section 6b holds the detailed rules from the decisions.
- Sections 8 to 8c are the decision history, the approval status of each decision group, and the open questions.
- Section 9 is the approval record.
- Items marked **Proposed** in Section 6b are not human-approved. They are listed in Section 8c.

## 0. Approval status and evidence

| Item | Status | Evidence | Covered by the earlier Step 1 approval? |
|---|---|---|---|
| Original Step 1 text (story, goals, IS-1 to IS-8, AC-01 to AC-08, NFRs, edge cases, Q1 to Q10) | Human-approved, earlier text only | The file recorded "Approved (2026-10-19)" in commit `b576e7e` (dated 2026-10-20). Some Q1-Q10 labels were written by the assistant and not verified against the human's wording. | Yes, for the text as it stood then. This revision restructures and annotates it, so it needs re-approval. |
| D1-D10 | Recorded as human decisions, 2026-10-21 | Committed in `6d64178`. The architecture (`9ba17d6`) and design review (`43ca0d5`) rely on them. The original decision conversation is not in the evidence available to this revision. | No |
| D11-D18, D20 | Assistant proposals (2026-10-21), approved by the human on 2026-10-22 | The human's instruction of 2026-10-22 to apply the confirmed decisions for D11-D20 | No |
| D19 | Assistant proposal, approved by the human on 2026-10-22 as Option B | The human's instructions of 2026-10-22 ("D19 Option B", then "apply D19 Option B") | No |
| D21-D31 | Approved by the human on 2026-10-22 in the form of the recommended defaults for NF-1, NF-2, NF-8 to NF-14, P4, and P9 | The human's instruction of 2026-10-22 to apply those items. Particulars the defaults did not state are marked Proposed in Section 6b and listed in Section 8c. | No |
| Open questions OQ-1 to OQ-6 | Not decided | Section 8c | No |

No amendment (D1-D31) was part of the earlier Step 1 approval. No Git commit approves this revision.

## 1. Story

As a software developer, I want the system to analyze changes in a Git repository and propose updates to relevant documentation, so that technical documentation stays aligned with the source code while I retain control over what is accepted.

Persona: software developer contributing to a Git repository. Epic: Developer Productivity and Documentation Quality. Priority: High (for this exercise).

## 2. Goals

- G1: Reduce manual effort to identify documentation affected by code changes.
- G2: Improve consistency between implementation details and technical documentation.
- G3: Make unsupported or uncertain documentation claims visible to reviewers.
- G4: Keep a human approval step before proposed documentation changes are accepted.

## 3. In-Scope Behaviors (proposed in story)

Each item is the story's wording, followed by the decisions that shape it. Detailed rules are in Section 6b.

- IS-1: Accept a local Git repository path or an explicitly selected set of changed files as input.
  - The input is a local Git diff only (Q1). In v1 the input is the repository path; the explicit file-set form is deferred (D21).
  - Diffs over the size cap are not processed (Q7, Section 6b.3).
- IS-2: Inspect relevant source files and the available local Git diff.
  - Pull-request diffs are not an input in v1 (Q1). The diff is `git diff HEAD` (D21).
- IS-3: Identify candidate documentation files, focusing on Markdown.
  - Documentation targets are `README.md` plus Markdown files under `docs/` (Q2). Other Markdown is out of scope.
  - The mapping rule is D19. Multiple matching documents are listed, never silently selected (Q8, D4).
- IS-4: Generate proposed documentation changes based on evidence in the repository.
  - The output is a patch file for human review (Q3). Generation uses deterministic rules and local tools only, with no LLM or API calls (Q5).
  - No patch is generated for a silently chosen file (Q8). Under D4, no patch is generated for the multiple-candidate case until the human re-runs with `--target <path>`.
- IS-5: Report when source information is missing, conflicting, or insufficient.
- IS-6: Validate basic output quality: empty output, malformed Markdown where a validator is available, broken relative links where feasible.
  - Mandatory checks and their scope are in Section 6b.9 (Q6, D2, D5, D7, D9, D27).
- IS-7: Present a summary of files examined, files proposed for change, validation results, and limitations.
  - The summary is the terminal report, delivered with the patch file (Q9). Contents are in Section 6b.13.
- IS-8: Keep changes reviewable; never silently commit, push, merge, or publish.
  - No direct edits to documentation files (Q3). No silent selection among matching documentation files (Q8).

## 4. Out of Scope (initial capstone)

From the story:

- Automatic merge or deploy to production.
- Automatic publishing to an external website.
- Guaranteeing semantic correctness without developer review.
- Supporting every language, repository host, or documentation format.
- Making live Jira or Confluence integration mandatory.

From the decisions:

- Pull-request diff input (Q1, 2026-10-19): deferred to a future release. v1 supports local Git diff only.
- Explicit file-set input, branch-vs-base diffs, and commit-range diffs (D21): not supported in v1.
- Analysis of untracked files (D21): not supported in v1. They are listed as "not analyzed".
- Markdown files outside `README.md` and `docs/` (Q2): out of scope for v1. Non-Markdown documentation formats remain out of scope.
- Direct editing of documentation files (Q3): the system never edits documentation files directly. It produces a patch file only.
- LLM/API integration (Q5): out of scope for v1. No calls to LLM services or other external APIs. Repository content is never sent to external services.
- Enforcing source-to-doc consistency (Q6): out of scope for v1. It is reported only and does not block validation (see D28).
- Processing diffs above the size cap (Q7): out of scope for v1. Such diffs are not processed or partially processed. The tool stops, reports the size, and asks the human to split them. There is no warning tier.
- Silent or automatic selection among multiple matching documentation files (Q8): out of scope. The system never picks one on its own.
- GitHub PR comment delivery (Q9): not selected, so out of scope for v1.
- CI integration (Q10): out of scope for v1. Verification is by local tests only.
- External URL validation and dependency/security scanners (D9): out of scope for v1. Not checked and not assumed; reported as limitations.
- Distribution packaging (D10): out of scope for v1.
- Instruction-like text detection (D16): dropped from v1. Repository text is still treated as data.

## 5. Acceptance Criteria

The statement of each criterion is the story's wording. The decisions that apply follow it.

- AC-01 Relevant change detected: Given a repository with a source-code change, when the workflow analyzes the selected change, then it identifies changed source files and reports which documentation files may be affected.
  - Local Git diff (Q1). Affected documentation files are limited to `README.md` and Markdown under `docs/` (Q2).
  - Applies to diffs at or below the cap (not more than 50 files and not more than 2,000 changed lines), which are processed normally (Q7). A diff above either limit is not processed.
  - When more than one documentation file is affected across the run, all candidates are listed and the system never silently selects one (Q8, D4, Section 6b.6).
- AC-02 Evidence-based update: Given a source change with sufficient supporting information, when documentation is generated, then proposed text is consistent with the inspected source and does not introduce unsupported behavior.
  - Proposed text is delivered as a patch file, not applied (Q3), and is produced by deterministic rules and local tools (Q5, D20).
  - Consistency with source is reported, not enforced (Q6). In v1 the report carries a single Not Found item for consistency (D28).
- AC-03 Insufficient information: Given a change whose intent cannot be determined from available files, when the workflow processes it, then it flags uncertainty and requests clarification or reports the item as `Not Found` rather than inventing details.
- AC-04 No relevant documentation: Given a repository with no relevant documentation file, when analysis completes, then the workflow reports that no suitable documentation target was found and does not create arbitrary files without an approved rule.
  - A relevant documentation file is `README.md` or Markdown under `docs/` (Q2). No files are created or edited directly in any case (Q3).
- AC-05 Empty change set: Given an empty or unavailable change set, when the workflow starts, then it returns a clear status and does not generate unrelated documentation changes.
  - Unavailable includes a local Git diff that cannot be produced, including a repository with no `HEAD` (Q1, D21).
  - Extension from Q7 (the story's AC-05 does not name this case): a diff over the cap is not processed. The tool stops, reports the diff size, asks the human to split it, and generates no documentation changes.
  - Extension from D23: a binary, mode-only, or submodule entry stops the run with an "unsupported entry" error.
- AC-06 Validation failure: Given generated documentation that fails an enabled validation check, when verification runs, then the failure is reported with enough detail to help a developer investigate it.
  - Validation applies to the proposed content in the patch file (Q3).
  - The mandatory checks are Markdown syntax, broken relative links, and non-empty output (Q6, D2, D7). A failure fails validation and no patch is written. The report gives file, line, and rule.
  - Consistency findings are non-blocking (Q6).
- AC-07 Human review: Given proposed documentation updates, when the workflow finishes, then a developer can inspect the diff before accepting the changes.
  - The diff is the patch file for human review. Documentation files stay unmodified until a human applies the patch (Q3).
  - The developer receives a terminal report plus the patch file at `output/docsync.patch`. No GitHub PR comment in v1 (Q9, D3, D26).
  - Where multiple documents matched, the tool lists them and exits without a patch, and the human re-runs with `--target <path>` (Q8, D4).
- AC-08 Safe handling: Given repository content that includes secret-like values or instructions embedded in files, when the workflow analyzes it, then it does not expose credentials in logs and treats repository text as data rather than as authority to override system or project instructions.
  - Repository content stays on the local machine and is not sent to external services (Q5).
  - A hunk containing a secret-like value is withheld, and no patch is written (D8, D31, Section 6b.8).

## 6. Non-Functional Requirements

- NFR-01 Security: Do not log or expose credentials, access tokens, or other secrets. Use least-privilege access for integrations.
  - No repository content leaves the local machine, and v1 has no LLM/API integration (Q5). No scanning tool is assumed (Q10, D9).
- NFR-02 Reliability: Handle missing files, invalid paths, empty inputs, and validation errors with clear messages.
  - An oversized diff is handled by stopping with a message that reports the diff size and asks the human to split it. There is no warning tier (Q7).
  - An unsupported entry, an invalid `--target`, an existing patch file, and a repository with no `HEAD` are also handled with clear messages (D21, D23, D29, D30).
- NFR-03 Maintainability: Keep change analysis, documentation mapping, generation, and validation logically separated.
- NFR-04 Traceability: For each proposed documentation change, provide a reason and identify supporting source files where feasible.
- NFR-05 Reviewability: Avoid unrelated edits and preserve a human-readable diff.
- NFR-06 Testability: Core behavior testable with local fixtures without requiring live external services for every test.
  - Implementation targets Python 3.12 (Q4). Tests use the standard-library `unittest` (D10). No external LLM/API services are used (Q5). Verification is by local tests only (Q10).
  - Human-confirmed (2026-10-19): "The same input produces the same output, because v1 uses deterministic rules (Q5)."

## 6a. Constraints

- C-1 (Q4): Implementation language and runtime is Python 3.12. Tests use standard-library `unittest` and distribution packaging is out of v1 scope (D10). Framework and dependencies: standard library only, no packaging (D18).
- C-2 (Q5): No LLM/API integration in v1. Analysis, mapping, generation, and validation use deterministic rules and local tools only. No repository content is sent to external services; all processing stays on the local machine. Rationale given: lower cost and no repository content sent to external services.
- C-3 (Q6): Mandatory validation is Markdown syntax and broken relative links. Failures fail validation (originally an analyst-proposed inference, confirmed by D2). Source-to-doc consistency is reported only and non-blocking. External and absolute URLs are not checked in v1 and are reported as a limitation (D9). Scope and not-checked handling: Section 6b.9.
- C-4 (Q7): Single threshold, no warning tier. If a diff exceeds 50 files or 2,000 changed lines (either limit), the tool stops, reports the diff size, and asks the human to split it. A diff at or below the cap is processed normally. Counting rules: D6, D23, Section 6b.3. There is no repository-size limit; the diff cap is the only limit (D12).
- C-5 (Q8): When multiple documentation files match, the system lists all candidates and asks the human which to update. It never silently selects one. Mechanism: D4, Section 6b.6.
- C-6 (Q9): Results are delivered as a terminal report plus a generated patch file. GitHub PR comment is out of scope for v1. The patch is a unified diff at `output/docsync.patch` (D3), relative to the tool's working directory (D26), and an existing file is never overwritten (D3, D29).
- C-7 (Q10): Verification is by local tests only. No CI environment is relied on, and CI integration is out of scope for v1. No dependency/security scanning tool is assumed (D9). No rationale was given.

## 6b. Behavior Rules

These rules apply the decisions in Section 8b. Each cites its decision. Text marked **Proposed** has no human approval; it is a default listed in Section 8c.

### 6b.1 Input and diff source (Q1, D21)

- The inputs are a repository path (see OQ-1) and the optional `--target <path>`.
- The diff is `git diff HEAD`: tracked changes in the working tree against `HEAD`, staged and unstaged together.
- Untracked files are never read or analyzed. They are listed in the report as "not analyzed", so new files are not documented. This limitation is always stated in the report.
- A repository with no `HEAD` is a Git error and stops the run.
- If there are no tracked changes, the result is "no changes", even when untracked files exist. The untracked files are still listed.
- Pull-request diffs, branch-vs-base diffs, commit ranges, and an explicit set of changed files are not supported in v1.

### 6b.2 Git safety (D22)

- Git is run through one adapter. It runs read-only subcommands only, using an argument list and no shell. The tool never commits, pushes, merges, or publishes (IS-8).
- External diff drivers, text conversion (textconv), and the pager are disabled. User and system Git configuration is ignored. Execution-capable repository settings, such as `core.fsmonitor`, are overridden on the command line. The Git environment is cleaned of inherited variables.
- The exact flag list is not decided here. It is fixed in the implementation plan (task T05) and described in the architecture (Section 7).
- Test obligation: a hostile `.git/config` fixture (for example an external diff driver, a textconv filter, `core.fsmonitor`, and a pager) must execute nothing.
- Repository text is data. It is never executed or used to build commands (AC-08).

### 6b.3 Size gate and counting (Q7, D6, D12, D23)

- Every diff entry counts as one file. This includes entries later skipped as generated (D13).
- Text entries count added plus deleted lines.
- A rename or copy with no content change counts as 1 file and 0 changed lines. With a content change it counts the added plus deleted lines.
- A deleted file counts as 1 file plus its deleted lines. It is reported as "not analyzed".
- A binary entry (line counts shown as `-`), a mode-only change, or a submodule entry stops the run with a typed "unsupported entry" error that names the path and kind. It is never skipped or counted as zero, and no patch is written.
- The cap is more than 50 files or more than 2,000 changed lines (either limit). Over the cap the tool stops, reports the file and line counts, and asks the human to split the diff. There is no warning tier and no partial processing.
- Very large files count toward the cap and are not analyzed separately. There is no per-file threshold (D14). There is no repository-size limit (D12).

### 6b.4 File classification (D13, D17)

- Paths matching `*.lock`, `*.min.*`, `dist/**`, and `build/**` are generated. They are skipped and each skip is reported.
- Changes to `README.md` or `docs/**` themselves, and test files (see 6b.5), are not source. They are skipped and reported.
- Text files other than `.py` get a generic text diff only, with no language mapping and no symbol names (D17).

### 6b.5 Mapping (D19, P5, Q2)

- Mapping is path-based only. Each changed source file maps to at most one candidate:
  1. `docs/<module>.md`, if that file exists;
  2. otherwise `README.md`, if it exists;
  3. otherwise no candidate.
- Module name: the file name with its last extension removed, lowercased. Directories are ignored, so a nested path uses its stem only (`pkg/util/parser.py` gives `parser`). `__init__.py` uses the parent directory's name. Non-Python files use the same rule.
- Lookup: `docs/<module>.md` directly under `docs/` (no subfolders), matched on the lowercased stem, in the working tree (not `git ls-files`). The reported path is the document's actual path.
- Test files are not mapped. A test file is one under a `test` or `tests` directory, or named `test_*.py` or `*_test.py`. Each is reported as skipped.
- Two changed files with the same module name map to the same document. That is one candidate.
- If no changed source file has a candidate, the tool reports "no suitable documentation target" and creates no files (AC-04).
- D19 replaces the earlier wording (README always a candidate, plus `docs/<module>.md`). That wording gave two candidates for every module with a doc, and under D4 that would stop nearly every run.

### 6b.6 Target selection (Q8, D4, D11, D25, D30)

The run's candidate list is the sorted set of distinct documents that the analyzed source changes map to. Under D19 a single change has at most one candidate, so several candidates arise only across the run's changes. The tool never selects a target, never prompts, and never reads stdin.

Without `--target`:

- If every analyzed source change maps to the same single document, the run proceeds.
- **Proposed (OQ-4):** otherwise the tool writes no patch. It lists all candidate documents with the changed files that map to each, reports any change with no candidate, and exits non-zero. The human re-runs with `--target <path>` (D4).
- The approved basis is D4 and the NF-10 default that an unresolved candidate set writes no patch and exits non-zero. Whether several distinct documents counts as unresolved is the Proposed reading.

With `--target <path>`:

- The target is validated first (D30, D11). It must be a path relative to the repository root, and must be `README.md` or a Markdown file under `docs/`. It must be one of the run's candidates. Absolute paths, any `..` segment, and any path whose resolved location is outside the repository (including through a symlink) are rejected. A rejected target exits non-zero, writes no patch, and lists the valid candidates.
- **Proposed (OQ-4):** changes that map to the target are in scope. Changes that map to a different document are intentionally out of scope, because the human selected the target. They are listed in the report as "not addressed in this run", with the document they map to. They are never silently omitted, never moved to the target, and never counted as processed.
- **Proposed (OQ-4):** a change with no candidate at all is unresolved, and it blocks the patch. Choosing a target does not cover it.
- Any in-scope failure blocks the patch, as in 6b.11: a stage failure, a withheld hunk, a failed or not-checked mandatory check, or empty output.
- **Proposed (OQ-4):** an AC-03 Not Found item for an in-scope change is a reported result, not a failure. It does not block the patch. If every in-scope change yields only Not Found items, the output is empty and no patch is written (D7).

### 6b.7 Generation (Q5, D17, D20)

- Each proposed edit is a reason line plus the changed symbol names from the diff, with its supporting source files (NFR-04). There is no free-text generation.
- The output is deterministic. The same input gives the same text, with no run time or random value embedded.
- A change with no extractable symbol names, such as a non-`.py` file (D17), has insufficient evidence. It is reported as a "Not Found / needs clarification" item (AC-03). Conflicting or insufficient sources are handled the same way, listing the files involved.
- Edits are minimal. Unrelated lines are not touched (NFR-05).

### 6b.8 Secrets and withholding (D8, D15, D16, D31)

- The minimum secret pattern set is key, token, password, and secret assignments, PEM private-key headers, and AWS-style access key IDs. The full list is finalized by the tests of the patch-writer task (T13).
- Secret-like values are masked in anything printed or logged. The terminal report, logs, error messages, and patch never contain the value.
- A hunk containing a secret-like value is withheld entirely, including its context lines. The report gives the file and line only.
- Because the run is all-or-nothing, any withheld hunk means no patch is written (D31).
- Instruction-like text is not detected in v1 (D16). It is still treated as data and never acted on.

### 6b.9 Validation (Q6, D2, D5, D7, D9, D27, D28)

Mandatory checks. A failure of any of them fails validation and no patch is written (D2):

| Check | Scope | Failure |
|---|---|---|
| Markdown syntax | Standard-library checks for unbalanced code fences and malformed link syntax (D5), on the proposed content | Reported with file, line, and rule |
| Relative links | Inline relative links and images, written `[text](path)`, that appear on the added lines of each proposed edit. A path is resolved relative to the directory of the document being edited, against the working tree. A `#fragment` is stripped and the anchor is not checked. | Link to a missing file is reported with file, line, and rule |
| Non-empty output | The generated output as a whole (D7) | Empty output produces no patch |

Not mandatory:

- Source-to-doc consistency is not computed in v1. The report carries one item: "Not Found: consistency is not computed in v1". It is non-blocking and never fails validation (D28). Supporting source files are still listed per edit.

Explicitly outside v1 scope. These are not checked, and the report says so under limitations. They are never reported as passing:

- External and absolute URLs (D9).
- Reference-style links and autolinks (D27).
- Anchor targets, that is, whether a `#fragment` exists in the target file (D27).
- Links on lines that the proposed edit does not add (D27).
- Dependency and security scanners (D9).

Not-checked rule (D5):

- A mandatory check that is unsupported or not performed is reported as "not checked". It is never reported as passing, and validation does not pass, so no patch is written.
- **Proposed (OQ-5):** the link kinds listed above as outside v1 scope are a declared limit of the relative-link check, not a mandatory check that was not performed. They are reported as limitations and do not by themselves fail validation. This treats them like external URLs under D9. If the human reads D5 as failing validation whenever any link is unchecked, those links would block the patch instead.
- How a line is reported for a not-checked result: **Proposed** (OQ-3), file and rule only.

### 6b.10 Output (Q3, Q9, D3, D26, D29)

- The deliverables are a terminal report and a patch file in unified diff format (Q9).
- The patch is written to `output/docsync.patch`, relative to the directory the tool is run from (D26). That directory is not necessarily the repository being analyzed. The tool never writes inside `README.md` or `docs/`, and never edits `.gitignore`.
- D3 states that `output/` is excluded by `.gitignore` because it holds generated local artifacts. A `.gitignore` entry protects the output only when the output lies inside the repository governed by that ignore file and the pattern matches. If the tool is run from another directory, or the patch lands in a different repository, that repository's `.gitignore` does not cover it. Maintaining the entry is the user's responsibility. At the time of this revision the `.gitignore` of this project contains `output/`.
- An existing `output/docsync.patch` is never overwritten, and there is no `--force` (D3, D29). The tool checks for it at the start of the run, before any Git call. If it exists, the run stops, the message names the file, no patch is written, and the exit class is "existing patch or write failure". This is a stage failure under D1. A file that appears after the check is still never overwritten.
- Whether the tool creates the `output/` directory when it is missing: **Proposed** (OQ-6).
- The patch is written only when the run reaches the end of the order in 6b.11 with every condition met.

### 6b.11 All-or-nothing and stage order (D1, D2, D31, P4)

- The order is: generate, redact and withhold, validate, write.
- No patch is written when any of these occurs: a stage failure, a withheld hunk, a failed or not-checked mandatory check, empty output, an unresolved in-scope change, an invalid `--target`, a diff over the cap, an unsupported entry, a Git or input error, or an existing patch file.
- The report names the failed stage and the completed units (D1). For a secret, it names the file and line only.
- A successful run writes exactly one new file, the patch. Documentation files are never modified.

### 6b.12 CLI and exit status (D24)

- The only inputs are the repository path and `--target <path>`. There is no interactive prompt and no stdin.
- Exit 0 only when a patch was successfully written. A run that writes a patch while reporting "not addressed" items still exits 0, and the items appear in the report.
- Every other outcome exits non-zero with a distinct code for its class. **Proposed** (OQ-2), numeric values, identical to the architecture (Section 6a):

| Code | Outcome class |
|---|---|
| 0 | Patch written |
| 2 | Usage error or invalid `--target` |
| 3 | Input or Git error (path, not a repository, no `HEAD`, diff failed) |
| 4 | No changes |
| 5 | Diff over the cap |
| 6 | Unsupported entry (binary, mode-only, submodule) |
| 7 | No suitable documentation target |
| 8 | Unresolved candidates |
| 9 | Validation failed or empty output |
| 10 | Secret-like hunk withheld |
| 11 | Existing patch or patch write failure |
| 12 | Other stage failure |

- The approved part is that exit 0 is only for a written patch and that each outcome class has a distinct non-zero code. The code for a run where every changed file is skipped (documentation, test, or generated files only) is **Proposed** (OQ-2): class 4, "No changes", with the skip report.

### 6b.13 Report contents (IS-5, IS-7)

The terminal report contains:

- Files examined, and files proposed for change.
- Files skipped, with the reason: generated, documentation, test, deleted, or untracked ("not analyzed").
- Validation results, including any "not checked" result.
- Candidate lists, and "not addressed in this run" items.
- Not Found items, including the consistency item.
- The limitations, always stated: external URLs are not checked; no dependency or security scanner is run (D9); untracked files are not analyzed (D21); the link kinds in 6b.9 are outside the check (D27); consistency is not computed (D28).
- Secret-like values are masked (Section 6b.8).

## 7. Error and Edge Cases

E1 to E11 are the story's nine cases plus the size cap (E5, from Q7) and multiple matching documents (E7, from Q8). E12 to E14 were added from decisions. The labels are used by the implementation plan.

- E1: Repository path does not exist or cannot be read. Exit class 3.
- E2: Git unavailable, not a Git repository, no `HEAD`, or the diff command fails. Exit class 3.
- E3: No changed files detected. Exit class 4. Untracked files, if any, are listed as "not analyzed".
- E4: Changed files are binary, generated, very large, or unsupported types. A binary, mode-only, or submodule entry stops the run with an "unsupported entry" error (D23). Generated paths are skipped and reported (D13). Large files count toward the cap only (D14).
- E5: Diff exceeds the size cap (Q7): more than 50 files or more than 2,000 changed lines (either limit). The tool stops, reports the diff size, asks the human to split the diff, and generates no documentation changes. Exit class 5.
- E6: No matching documentation file exists (AC-04). Exit class 7.
- E7: Multiple documentation files match (Q8, D4, D25): the tool lists all candidates and exits without a patch, and the human re-runs with `--target <path>`. Exit class 8. There is no interactive prompt, so a non-answer cannot occur.
- E8: Documentation has broken links or malformed Markdown (D2, D5): validation fails and no patch is written. Exit class 9.
- E9: Source files disagree or lack information to determine intended behavior: reported as Not Found (AC-03).
- E10: Generator or validation step fails partway (D1): any stage failure writes no patch. Exit class 12.
- E11: Repository content contains prompt-injection-like instructions or secret-like strings (D8, D16, D31): text is treated as data. A hunk with a secret-like value is withheld, the file and line are reported, and no patch is written. Exit class 10.
- E12 (D21): Untracked files exist. They are not part of `git diff HEAD`. They are listed as "not analyzed" and are a stated limitation.
- E13 (D29): `output/docsync.patch` already exists. The run stops at the start, names the file, and writes nothing. Exit class 11.
- E14 (D11, D30): `--target` is invalid. The run exits with class 2, writes no patch, and lists the valid candidates.

## 7a. Traceability

Story items to acceptance criteria:

| Item | Acceptance criteria | Notes |
|---|---|---|
| IS-1, IS-2 | AC-01, AC-05 | |
| IS-3 | AC-01, AC-04 | |
| IS-4 | AC-02, AC-03, AC-07 | |
| IS-5 | AC-03 | |
| IS-6 | AC-06 | |
| IS-7 | AC-06, AC-07 | |
| IS-8 | AC-07, AC-08 | |
| G1 | AC-01 | |
| G2 | AC-02 | |
| G3 | AC-03, AC-06 | |
| G4 | AC-07 | |
| NFR-01 | AC-08 | |
| NFR-02 | AC-05, E1 to E14 | |
| NFR-03 | none | Verified at design review and code review, not by an acceptance criterion |
| NFR-04 | AC-02, AC-03 | |
| NFR-05 | AC-07 | |
| NFR-06 | all | Verified by local tests (Q10) |

Edge cases to acceptance criteria:

| Edge case | Acceptance criteria |
|---|---|
| E1, E2, E3, E5, E12 | AC-05 |
| E4 | AC-03, AC-05 |
| E6 | AC-04 |
| E7, E14 | AC-01, AC-07 |
| E8 | AC-06 |
| E9 | AC-03 |
| E10 | AC-06 |
| E11 | AC-08 |
| E13 | AC-07 |

Decisions to the requirements they affect:

| Decisions | Requirements and sections |
|---|---|
| D1, D31 | AC-06, AC-07, E10, Section 6b.11 |
| D2, D5, D7, D27, D28 | IS-6, AC-02, AC-06, C-3, Section 6b.9 |
| D3, D26, D29 | IS-7, AC-07, C-6, E13, Section 6b.10 |
| D4, D11, D25, D30 | IS-3, IS-4, AC-01, AC-07, C-5, E7, E14, Section 6b.6 |
| D6, D12, D14, D23 | IS-1, AC-05, C-4, E4, E5, Section 6b.3 |
| D8, D15, D16 | AC-08, E11, Section 6b.8 |
| D9 | IS-6, C-3, C-7, Section 6b.9 |
| D10, D18 | C-1, NFR-06 |
| D13, D17, D19, D20 | IS-3, IS-4, AC-01, AC-03, AC-04, E4, Sections 6b.4, 6b.5, 6b.7 |
| D21, D22 | IS-1, IS-2, AC-05, AC-08, E2, E3, E12, Sections 6b.1, 6b.2 |
| D24 | NFR-02, Section 6b.12 |

Known gap: no acceptance criterion is dedicated to the existing-patch refusal, the invalid `--target`, or the unsupported entry. They are covered by edge cases E4, E13, E14 and NFR-02. No new acceptance criterion was added, because that would extend the approved criteria set. Whether to add them is not decided.

## 8. Clarification Decisions

Rule: unanswered or deferred questions stay "Open". No answers have been assumed. All ten questions (Q1-Q10) now have a recorded decision; none are Open.

| # | Date | Question | Decision | Rationale |
|---|------|----------|----------|-----------|
| Q1 | 2026-10-19 | Analyze a local Git diff, a pull-request diff, or both? | Human decision: local Git diff only. Pull-request diffs are deferred to a future release (out of scope for v1). Affects IS-1, IS-2, AC-01, AC-05, and Section 4. | "PR diffs come later." No further rationale given. |
| Q2 | 2026-10-19 | Supported documentation targets: `README.md` only, all Markdown, or configurable list? | Human decision: "README.md and Markdown files under docs/". Documentation targets = `README.md` plus Markdown files under `docs/`. Other Markdown elsewhere is out of scope for v1. No configurable list in v1 (not stated). Affects IS-3, AC-01, AC-04, and Section 4. | None given. |
| Q3 | 2026-10-19 | Directly edit documentation files, or produce a patch/report for human approval? | Human decision: "a patch file for human review. No direct edits to docs." Output is a patch file for human review; the system never edits documentation files directly. Delivery is settled by Q9 (terminal report plus patch file). Affects IS-4, IS-7, IS-8, AC-02, AC-04, AC-06, AC-07, and Section 4. | None given. |
| Q4 | 2026-10-19 | Implementation language and runtime? | Human decision: "Python 3.12". Implementation language/runtime = Python 3.12. Packaging, framework, and test-tool choices were undecided at Step 1; see D10 (`unittest`; distribution packaging out of v1 scope). Affects Section 6a (C-1) and NFR-06. | None given. |
| Q5 | 2026-10-19 | Is LLM/API integration permitted, or deterministic rules and local tooling only? | Human decision: "No LLM/API integration in v1. Use deterministic rules and local tools." Deterministic rules and local tools only; LLM/API integration is out of scope for v1; no repository content leaves the local machine. Affects IS-4, IS-6, AC-02, AC-08, NFR-01, NFR-06, Section 4, and Section 6a (C-2). | "This keeps costs down and avoids sending repo content to external services." (Lower cost; no repo content sent to external services.) |
| Q6 | 2026-10-19 | Mandatory validation checks: Markdown syntax, links, source-to-doc consistency, or all? | Human decision: "Markdown syntax and broken relative links are mandatory. Source-to-doc consistency is reported, not enforced." Mandatory = Markdown syntax + broken relative links; failures fail validation (originally an analyst-proposed inference; confirmed by D2). Source-to-doc consistency is reported only and non-blocking. External/absolute URL handling was undecided at Step 1 (not stated); resolved by D9: not checked in v1 and reported as a limitation. Affects IS-6, IS-7, AC-02, AC-06, Section 4, and Section 6a (C-3). | None given. |
| Q7 | 2026-10-19 | Maximum repository or diff size to support? | Human decision; final decision supersedes earlier wording (2026-10-19). Human, verbatim: "One threshold, no warning tier: if a diff exceeds 50 files or 2,000 changed lines, the tool stops, reports the size, and asks for a split. Anything at or below the cap is processed normally." Decision: single threshold; either limit (more than 50 files OR more than 2,000 changed lines) triggers a stop; the tool reports the diff size and asks the human to split the diff; a diff at or below the cap is processed normally; there is no warning tier. Size counting was undecided at Step 1; resolved by D6 and D23. There is no repository-size limit; the diff cap is the only limit (D12). History: the initial answer ("reject diffs above a fixed limit (for example, 50 files or 2,000 changed lines) with a clear message") was superseded by this decision. Affects IS-1, IS-7, AC-01, AC-05, NFR-02, Section 4, Section 6a (C-4), and Section 7. | None given. |
| Q8 | 2026-10-19 | Behavior when several documentation files match the same source change? | Human decision: "list all candidates and ask the human which to update. Don't pick one silently." When multiple documentation files match a source change, the system lists all candidates and asks the human which to update; it never silently selects one. How the human is asked, given patch-file output (Q3) and delivery (Q9: terminal report plus patch file) was undecided at Step 1 (no mechanism assumed); resolved by D4: no interactive prompt, the tool lists all candidates and exits without a patch, and the human re-runs with `--target <path>`. Behavior if the human gives no answer is moot under D4. Affects IS-3, IS-4, IS-7, IS-8, AC-01, AC-07, Section 4, Section 6a (C-5), and Section 7. | None given beyond the human's words. |
| Q9 | 2026-10-19 | Result delivery: terminal report, patch, GitHub PR comment, or combination? | Human decision: "a terminal report plus a generated patch file." (verbatim, human). Results are delivered as a terminal report plus a generated patch file. GitHub PR comment is not selected, so it is out of scope for v1, consistent with Q1 (local Git diff only). Patch file location, name, and format were undecided at Step 1; resolved by D3 and D26. How the Q8 "ask the human" step works with this delivery was undecided at Step 1; resolved by D4. Affects IS-7, AC-07, Section 4, and Section 6a (C-6). | None given. |
| Q10 | 2026-10-19 | Available CI environment and dependency/security scanning tools? | Human decision: "local tests only" (verbatim, human). Interpretation: verification is by local tests only; no CI environment is relied on for v1, and CI integration is out of scope for v1. Which dependency/security scanning tools, if any, are available was not stated; none is assumed (confirmed by D9: scanners are outside v1 scope). Affects Section 4, NFR-01, NFR-06, and Section 6a (C-7). | None given. |

## 8a. Approval status of the decisions

The status of each decision group, and the evidence, is in Section 0. In short:

- Q1-Q10: human-approved on the earlier text.
- D1-D10: recorded as human decisions on 2026-10-21.
- D11-D31: approved by the human on 2026-10-22, except the parts marked Proposed in the register (D24 numeric codes, D25 `--target` scoping, D27 reading of D5). They are not covered by the earlier Step 1 approval.
- Unresolved: OQ-1 to OQ-6 in Section 8c. OQ-4 and OQ-5 need the human's decision before this file is approved.

Resolved 2026-10-19 (no longer pending): Q7 threshold (single threshold, 50 files or 2,000 changed lines, either limit, no warning tier) and the NFR-06 repeatable-output sentence (human-confirmed wording in Section 6).

## 8b. Amendment Decisions (D1-D31)

Where Step 1 left an item undecided, the note beside it names the decision that resolves it. The rules that apply D11-D31 are in Section 6b; this register gives each decision and its basis.

Basis codes: H1 = human decision recorded 2026-10-21. H2 = assistant proposal approved by the human 2026-10-22. H3 = approved by the human 2026-10-22 as the recommended default for the named NF or P item.

| ID | Decision | Basis | Rules |
|---|---|---|---|
| D1 | Partial failure: all-or-nothing. Any pipeline-stage failure writes no patch. The report names the failed stage and the completed units. | H1 | 6b.11 |
| D2 | Validation gate: the patch is written only if all mandatory checks pass (Markdown syntax, relative links, non-empty output). A failed check produces a report with file, line, and rule, and no patch. | H1 | 6b.9 |
| D3 | Patch location and format: unified diff at `output/docsync.patch`. The tool refuses to overwrite an existing file. `output/` is excluded by `.gitignore` because it holds generated local artifacts. Qualified by D26 (base directory, and what a `.gitignore` entry covers) and D29 (existing file). | H1 | 6b.10 |
| D4 | Multiple matching docs: no interactive prompt in v1. The tool lists all candidates and exits without a patch. The human re-runs with `--target <path>`. The tool never selects a target. Under D19 each changed file has at most one candidate, so the candidate list is the set of distinct documents the run maps to (see OQ-4). | H1 | 6b.6 |
| D5 | Markdown validator: standard-library checks for unbalanced code fences and malformed link syntax. A check that is unsupported or not performed is reported as "not checked" and is never reported as passing; validation does not pass. | H1 | 6b.9 |
| D6 | Size counting: files are counted as files, and changed lines are added plus deleted. | H1 | 6b.3 |
| D7 | Empty output: empty generated output produces no patch. | H1 | 6b.9 |
| D8 | Secret-like values: withhold the entire affected hunk. Report only the file and line, never the value. | H1 | 6b.8 |
| D9 | External URLs and dependency/security scanners: outside v1 scope. Not checked and not assumed; reported as limitations. | H1 | 6b.9 |
| D10 | Test tool and packaging (resolves A6): local tests use Python's standard-library `unittest`. Distribution packaging is out of v1 scope. The official instructions (user story, CLAUDE.md) do not require another approach. Directed by the human conditionally on the official instructions. | H1 | C-1 |
| D11 | Invalid `--target`: the tool exits non-zero, writes no patch, and lists the valid candidates. | H2 | 6b.6 |
| D12 | Size limit: the diff cap only (50 files or 2,000 changed lines). There is no repository-size limit. | H2 | 6b.3 |
| D13 | Generated files: paths matching `*.lock`, `*.min.*`, `dist/**`, and `build/**` are skipped. Each skip is reported. | H2 | 6b.4 |
| D14 | Very large files count toward the diff cap and are not analyzed separately. There is no per-file threshold. | H2 | 6b.3 |
| D15 | Secret patterns: the minimum set is key, token, password, and secret assignments, PEM private-key headers, and AWS-style access key IDs. The full list is finalized by the T13 tests. | H2 | 6b.8 |
| D16 | Instruction-like text detection is dropped from v1. Repository text is still treated as data and never acted on (AC-08). | H2 | 6b.8 |
| D17 | Languages beyond `.py`: generic text diff only, with no language mapping. | H2 | 6b.4, 6b.7 |
| D18 | Framework and dependencies: standard library only, no packaging. | H2 | C-1 |
| D19 | Mapping, Option B: a changed source file maps to `docs/<module>.md` if it exists, otherwise `README.md` if it exists, otherwise no candidate. Path-based only (P5). Module-name, lookup, and skip details: Section 6b.5. Supersedes the earlier wording (README always a candidate). | H2 (Option B approved 2026-10-22) | 6b.5 |
| D20 | Generation: each proposed edit is a reason line plus the changed symbol names from the diff. No free-text generation. The output is deterministic. | H2 | 6b.7 |
| D21 | Diff source (NF-1, P11): `git diff HEAD`, tracked changes, staged and unstaged. Untracked files are not analyzed and are listed as a limitation. No `HEAD` is a Git error. The explicit file-set form of IS-1, branch-vs-base, and commit ranges are deferred. | H3 | 6b.1 |
| D22 | Git hardening (NF-2, P2): read-only argument-list Git without a shell; external diff, textconv, and the pager disabled; user and system configuration ignored; execution-capable repository settings overridden; clean environment; tested with a hostile `.git/config` fixture. | H3 | 6b.2 |
| D23 | Size counting detail (NF-8, P8): each entry is one file; renames and copies, deleted files, and the unsupported-entry stop as in Section 6b.3. | H3 | 6b.3 |
| D24 | CLI and exit status (NF-9, P11): the repository path and `--target` only; no prompt; exit 0 only when a patch was written; a distinct non-zero code per outcome class. Numeric values: Proposed (OQ-2). | H3 for the rule; Proposed for the numbers | 6b.12 |
| D25 | Mixed and multiple results (NF-10, R10): an unresolved candidate set writes no patch and exits non-zero. The tool never selects a target. How `--target` scopes the run and how several distinct documents are treated: Proposed (OQ-4). | H3 for the rule; Proposed for the scoping | 6b.6 |
| D26 | Output location (NF-11, P3): `output/docsync.patch` is relative to the directory the tool is run from. The tool never edits `.gitignore`. | H3 | 6b.10 |
| D27 | Link-check scope (NF-12, R13): inline relative links and images on the added lines, resolved from the edited document's directory; fragments stripped; reference-style links, autolinks, anchors, and external URLs are outside the check and are reported as limitations. How this relates to D5: Proposed (OQ-5). | H3 for the scope; Proposed for the D5 reading | 6b.9 |
| D28 | Consistency findings (NF-13, P10): v1 reports a single "Not Found: consistency is not computed in v1" item. Non-blocking. | H3 | 6b.9 |
| D29 | Existing patch (NF-14, P7): checked at the start of the run, before any Git call; the message names the file; no patch is written; it is a stage failure under D1; no `--force`. | H3 | 6b.10 |
| D30 | `--target` validation (P9): repository-relative path; `README.md` or Markdown under `docs/`; must be one of the run's candidates; reject absolute paths, any `..` segment, and paths resolving outside the repository, including through symlinks. | H3 | 6b.6 |
| D31 | Stage order (P4): generate, redact and withhold, validate, write. Any withheld hunk or stage failure means no patch. The report names the file and line, never the value. | H3 | 6b.11 |

## 8c. Open questions and proposed defaults

None of these has a human decision. Each has a proposed default that the documents currently apply. "Blocks approval" means the human must decide the question before approving this file; approving the file as written with the proposed default would count as that decision.

| ID | Question | Proposed default | Blocks approval of this file? |
|---|---|---|---|
| OQ-1 | Is the repository path required, or does it default to the current directory? Is a subdirectory of a repository accepted? | Optional positional argument that defaults to the current directory. Subdirectory handling is Not Found. | No. It is an interface detail. It should be settled before the argument-handling tasks (T03, T09) are implemented. |
| OQ-2 | Numeric exit-code values, and the exit class for a run where every changed file is skipped. | The table in Section 6b.12, which matches the architecture (Section 6a), and class 4 for the all-skipped case. | No. The requirement is a distinct code per class, which is approved. Numbers are settled with the architecture. |
| OQ-3 | How a line is reported for a "not checked" result (design review Gap 7). | File and rule only. | No. |
| OQ-4 | (a) Does a run whose changes map to several distinct documents write no patch without `--target`? (b) With `--target`, are changes mapped to other documents intentionally out of scope and reported as "not addressed", while a change with no candidate blocks the patch? (c) Does an AC-03 Not Found item for an in-scope change block the patch? | (a) Yes, no patch. (b) Out of scope and reported; a change with no candidate blocks. (c) No, it is a reported result. The evidence is D4, Q8, and the NF-10 default. None states the `--target` scoping. | Yes. These change what the tool produces. |
| OQ-5 | Do the link kinds outside the relative-link check (reference-style links, autolinks, anchors, links on unchanged lines) fail validation under D5, or are they limitations like external URLs under D9? | Limitations. They are reported as outside v1 scope, never as passing, and do not by themselves block the patch. | Yes. It decides which patches are blocked. |
| OQ-6 | Does the tool create the `output/` directory when it is missing? | Yes, it creates that directory only. No decision covers it, but the patch cannot be written otherwise. | No. |

Also not blocking, and left as documented limitations:

- No acceptance criterion is dedicated to the existing-patch refusal, invalid `--target`, or unsupported entry (Section 7a).
- Design review I2 and I3 (date wording): the old Section 8b heading carried 2026-10-20 while its text said 2026-10-21. This revision removes the heading date. D1-D10 are dated 2026-10-21, as in the committed file. The date of the architecture draft is outside this file.
- R12 (patch applicability is not checked) and R14 (determinism across platform differences) from the design review have no decision. They remain open as the design review states them.

## 9. Approval

Approved (2026-10-22). The human approved the current revision of this file, as written, by instruction of 2026-10-22. No Git commit records this approval yet.

- All ten clarification questions (Q1-Q10) are decided.
- The earlier Step 1 approval (recorded as 2026-10-19, commit `b576e7e`) covered the original text only. This approval covers the current revision, including D1-D31 and Section 6b.
- The approval includes the proposed defaults in Section 8c as written, including OQ-4 and OQ-5. Earlier statements in this file that those two need a decision before approval are resolved by this approval. OQ-1, OQ-2, OQ-3, and OQ-6 remain documented defaults.
