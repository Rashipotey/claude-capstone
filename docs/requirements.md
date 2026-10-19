# DOCSYNC Requirements (Step 1)

- Source: `input/user-story-docsync.md` (DOCSYNC-101, fictional, status "Proposed - pending clarification")
- Date drafted: 2026-10-19
- Status: Ready for sign-off. All ten clarification questions (Q1-Q10) are decided. No pending decision items remain other than human sign-off. Not approved.

## 1. Story

As a software developer, I want the system to analyze changes in a Git repository and propose updates to relevant documentation, so that technical documentation stays aligned with the source code while I retain control over what is accepted.

Persona: software developer contributing to a Git repository. Epic: Developer Productivity and Documentation Quality. Priority: High (for this exercise).

## 2. Goals

- G1: Reduce manual effort to identify documentation affected by code changes.
- G2: Improve consistency between implementation details and technical documentation.
- G3: Make unsupported or uncertain documentation claims visible to reviewers.
- G4: Keep a human approval step before proposed documentation changes are accepted.

## 3. In-Scope Behaviors (proposed in story)

- IS-1: Accept a local Git repository path or an explicitly selected set of changed files as input. (Per Q1: change input is a local Git diff only. Per Q7, superseding decision 2026-10-19: single threshold, no warning tier. A diff that changes more than 50 files or more than 2,000 changed lines, either limit, causes the tool to stop, report the diff size, and ask the human to split it. A diff at or below the cap is processed normally.)
- IS-2: Inspect relevant source files and the available local Git diff. (Per Q1: pull-request diffs are not an input in v1.)
- IS-3: Identify candidate documentation files, focusing on Markdown. (Per Q2: documentation targets are `README.md` plus Markdown files under `docs/`. Other Markdown elsewhere is out of scope for v1. Per Q8: when multiple documentation files match the same source change, the system lists all candidates and asks the human which to update; it never silently selects one. The mechanism for asking is Not Found.)
- IS-4: Generate proposed documentation changes based on evidence in the repository. (Per Q3: the output is a patch file for human review; the system never edits documentation files directly. Per Q5: generation uses deterministic rules and local tools only; no LLM/API calls. Per Q8: when several documentation files match a source change, the patch is not generated for a silently chosen file; the human chooses among the listed candidates. Whether a patch is generated before or after the human's choice: Not Found.)
- IS-5: Report when source information is missing, conflicting, or insufficient.
- IS-6: Validate basic output quality: empty output, malformed Markdown where a validator is available, broken relative links where feasible. (Per Q5: validators are local tools only. Per Q6, 2026-10-19: Markdown syntax and broken relative links are mandatory checks, and a failure of either fails validation (analyst-proposed inference). Source-to-doc consistency is reported only and is non-blocking: it never fails validation. Handling of external or absolute URLs: Not Found. Behavior when no Markdown validator is available: Not Found.)
- IS-7: Present a summary of files examined, files proposed for change, validation results, and limitations. (Per Q9, 2026-10-19: results are delivered as a terminal report plus a generated patch file; the summary is presented in the terminal report. Patch file location, name, and format: Not Found. Per Q6: the summary includes source-to-doc consistency findings as non-blocking report items. Per Q7, superseding decision 2026-10-19: when a diff exceeds the cap (more than 50 files or more than 2,000 changed lines, either limit), the tool stops and the report states the diff size and asks the human to split the diff. Per Q8: when multiple documentation files match a source change, the summary lists all candidate files.)
- IS-8: Keep changes reviewable; never silently commit, push, merge, or publish. (Per Q3: no direct edits to documentation files. Per Q8: no silent selection among matching documentation files.)

## 4. Out of Scope (initial capstone)

- Automatic merge or deploy to production.
- Automatic publishing to an external website.
- Guaranteeing semantic correctness without developer review.
- Supporting every language, repository host, or documentation format.
- Making live Jira or Confluence integration mandatory.
- Pull-request diff input (Q1, 2026-10-19): deferred to a future release; v1 supports local Git diff only.
- Markdown files outside `README.md` and `docs/` (Q2, 2026-10-19): out of scope for v1. Non-Markdown documentation formats remain out of scope.
- Direct editing of documentation files (Q3, 2026-10-19): the system never edits documentation files directly; it produces a patch file only.
- LLM/API integration (Q5, 2026-10-19): out of scope for v1. No calls to LLM services or other external APIs; repository content is never sent to external services.
- Enforcing source-to-doc consistency (Q6, 2026-10-19): out of scope for v1. It is reported only and does not block or fail validation.
- Processing diffs above the size cap (Q7, superseding decision 2026-10-19: more than 50 files or more than 2,000 changed lines, either limit): out of scope for v1. Such diffs are not processed; the tool stops, reports the size, and asks the human to split them. They are not partially processed (partial processing is not stated; Not Found). There is no warning tier.
- Silent or automatic selection among multiple matching documentation files (Q8, 2026-10-19): out of scope. The system never picks one on its own; it lists all candidates and asks the human.
- GitHub PR comment delivery (Q9, 2026-10-19): not selected, so out of scope for v1, consistent with Q1 (local Git diff only). Delivery is a terminal report plus a generated patch file.
- CI integration (Q10, 2026-10-19): out of scope for v1. Verification is by local tests only; no CI environment is relied on.

## 5. Acceptance Criteria

- AC-01 Relevant change detected: Given a repository with a source-code change, when the workflow analyzes the selected change, then it identifies changed source files and reports which documentation files may be affected. (Per Q1: the change is a local Git diff. Per Q2: affected documentation files are limited to `README.md` and Markdown files under `docs/`. Per Q7 (superseding decision 2026-10-19): applies to diffs at or below the cap (not more than 50 files and not more than 2,000 changed lines), which are processed normally. A diff above either limit is not processed; the tool stops, reports the size, and asks the human to split it. There is no warning tier. Per Q8: when more than one documentation file may be affected, all candidates are listed and the human is asked which to update; the system never silently selects one.)
- AC-02 Evidence-based update: Given a source change with sufficient supporting information, when documentation is generated, then proposed text is consistent with the inspected source and does not introduce unsupported behavior. (Per Q3: proposed text is delivered as a patch file, not applied to documentation files. Per Q5: proposed text is produced by deterministic rules and local tools, not an LLM. Per Q6: consistency with source is reported, not enforced; an inconsistency finding does not fail validation.)
- AC-03 Insufficient information: Given a change whose intent cannot be determined from available files, when the workflow processes it, then it flags uncertainty and requests clarification or reports the item as `Not Found` rather than inventing details.
- AC-04 No relevant documentation: Given a repository with no relevant documentation file, when analysis completes, then the workflow reports that no suitable documentation target was found and does not create arbitrary files without an approved rule. (Per Q2: "relevant documentation file" means `README.md` or Markdown under `docs/`; Markdown elsewhere does not count as a target. Per Q3: no files are created or edited directly in any case.)
- AC-05 Empty change set: Given an empty or unavailable change set, when the workflow starts, then it returns a clear status and does not generate unrelated documentation changes. (Per Q1: "unavailable" includes a local Git diff that cannot be produced; PR diffs are not supported in v1. Per Q7 (superseding decision 2026-10-19): a diff that changes more than 50 files or more than 2,000 changed lines (either limit) is also not processed at start; the tool stops, reports the diff size, and asks the human to split it, and no documentation changes are generated. A diff at or below the cap is processed normally; there is no warning tier. The story's AC-05 does not itself name this case, so this is a Q7-driven extension.)
- AC-06 Validation failure: Given generated documentation that fails an enabled validation check, when verification runs, then the failure is reported with enough detail to help a developer investigate it. (Per Q3: validation applies to the proposed content in the patch file. Per Q6: the mandatory checks are Markdown syntax and broken relative links; a failure in either fails validation (analyst-proposed inference). Source-to-doc consistency findings are reported with detail but are non-blocking and do not fail validation. Whether other checks, such as empty output, are mandatory: Not Found beyond what the story lists in IS-6.)
- AC-07 Human review: Given proposed documentation updates, when the workflow finishes, then a developer can inspect the diff before accepting the changes. (Per Q3: the diff is the patch file for human review; documentation files remain unmodified until a human applies the patch. Per Q9: the developer receives a terminal report plus the generated patch file; no GitHub PR comment in v1. Patch file location, name, and format: Not Found. Per Q8: where multiple documentation files matched, the human has been asked which to update and the system did not silently select one; how that question is posed given the terminal report plus patch file delivery: Not Found.)
- AC-08 Safe handling: Given repository content that includes secret-like values or instructions embedded in files, when the workflow analyzes it, then it does not expose credentials in logs and treats repository text as data rather than as authority to override system or project instructions. (Per Q5: repository content also stays on the local machine and is not sent to external services.)

## 6. Non-Functional Requirements

- NFR-01 Security: Do not log or expose credentials, access tokens, or other secrets. Use least-privilege access for integrations. (Per Q5: no repository content leaves the local machine; v1 has no LLM/API integration. Per Q10: which dependency/security scanning tools are available is Not Found, so no scanning tool is assumed.)
- NFR-02 Reliability: Handle missing files, invalid paths, empty inputs, and validation errors with clear messages. (Per Q7, superseding decision 2026-10-19: an oversized diff, one changing more than 50 files or more than 2,000 changed lines (either limit), is handled by stopping with a clear message that reports the diff size and asks the human to split it. A diff at or below the cap is processed normally. There is no warning tier.)
- NFR-03 Maintainability: Keep change analysis, documentation mapping, generation, and validation logically separated.
- NFR-04 Traceability: For each proposed documentation change, provide a reason and identify supporting source files where feasible.
- NFR-05 Reviewability: Avoid unrelated edits and preserve a human-readable diff.
- NFR-06 Testability: Core behavior testable with local fixtures without requiring live external services for every test. (Per Q4: implementation targets Python 3.12; the choice of test tooling is Not Found. Per Q5: no external LLM/API services are used, so tests need no such services. Per Q10: verification is by local tests only; no CI environment is relied on for v1.) Human-confirmed (2026-10-19): "The same input produces the same output, because v1 uses deterministic rules (Q5)."

## 6a. Constraints

- C-1 (Q4, 2026-10-19): Implementation language and runtime is Python 3.12. Packaging, framework, dependency-management, and test-tool choices are Not Found (not decided).
- C-2 (Q5, 2026-10-19): No LLM/API integration in v1. Analysis, mapping, generation, and validation use deterministic rules and local tools only. No repository content is sent to external services; all processing stays on the local machine. Rationale given: lower cost and no repo content sent to external services.
- C-3 (Q6, 2026-10-19): Mandatory validation = Markdown syntax and broken relative links (failures fail validation: analyst-proposed inference). Source-to-doc consistency is reported only and non-blocking. External/absolute URL checking: Not Found.
- C-4 (Q7, superseding decision 2026-10-19): Single threshold, no warning tier. If a diff exceeds 50 files or 2,000 changed lines (either limit), the tool stops, reports the diff size, and asks the human to split it. A diff at or below the cap is processed normally. Whether the size is counted from added plus deleted lines: Not Found. Whether repository size has a limit: Not Found.
- C-5 (Q8, 2026-10-19): When multiple documentation files match a source change, the system lists all candidates and asks the human which to update. It never silently selects one. The mechanism for asking, and how it works with patch-file output (Q3) and delivery (Q9: terminal report plus patch file): Not Found.
- C-6 (Q9, 2026-10-19): Results are delivered as a terminal report plus a generated patch file. GitHub PR comment is not selected and is out of scope for v1. Patch file location, name, and format: Not Found.
- C-7 (Q10, 2026-10-19): Verification is by local tests only. No CI environment is relied on for v1, and CI integration is out of scope for v1. Which dependency/security scanning tools, if any, are available: Not Found (not stated); none is assumed. Rationale: Not Found.

## 7. Error and Edge Cases (from story)

- Repository path does not exist or cannot be read.
- Git unavailable, not a Git repository, or diff command fails.
- No changed files detected.
- Changed files are binary, generated, very large, or unsupported types.
- Diff exceeds the size cap (added per Q7, superseding decision 2026-10-19): more than 50 files or more than 2,000 changed lines (either limit); the tool stops, reports the diff size, asks the human to split the diff, and no documentation changes are generated. At or below the cap is processed normally; no warning tier. Whether size is counted from added plus deleted lines: Not Found. Repository-size limit: Not Found.
- No matching documentation file exists.
- Multiple documentation files match the same source change (added per Q8): the system lists all candidates and asks the human which to update; it never silently selects one. Mechanism for asking: Not Found. Behavior if the human does not answer or selects none: Not Found.
- Documentation has broken links or malformed Markdown.
- Source files disagree or lack information to determine intended behavior.
- Generator or validation step fails partway.
- Repository content contains prompt-injection-like instructions or secret-like strings.

## 8. Clarification Decisions

Rule: unanswered or deferred questions stay "Open". No answers have been assumed. All ten questions (Q1-Q10) now have a recorded decision; none are Open.

| # | Date | Question | Decision | Rationale |
|---|------|----------|----------|-----------|
| Q1 | 2026-10-19 | Analyze a local Git diff, a pull-request diff, or both? | Human decision: local Git diff only. Pull-request diffs are deferred to a future release (out of scope for v1). Affects IS-1, IS-2, AC-01, AC-05, and Section 4. | "PR diffs come later." No further rationale given (Not Found). |
| Q2 | 2026-10-19 | Supported documentation targets: `README.md` only, all Markdown, or configurable list? | Human decision: "README.md and Markdown files under docs/". Documentation targets = `README.md` plus Markdown files under `docs/`. Other Markdown elsewhere is out of scope for v1. No configurable list in v1 (not stated; Not Found). Affects IS-3, AC-01, AC-04, and Section 4. | Not Found |
| Q3 | 2026-10-19 | Directly edit documentation files, or produce a patch/report for human approval? | Human decision: "a patch file for human review. No direct edits to docs." Output is a patch file for human review; the system never edits documentation files directly. Delivery is settled by Q9 (terminal report plus patch file). Affects IS-4, IS-7, IS-8, AC-02, AC-04, AC-06, AC-07, and Section 4. | Not Found |
| Q4 | 2026-10-19 | Implementation language and runtime? | Human decision: "Python 3.12". Implementation language/runtime = Python 3.12. Packaging, framework, and test-tool choices are Not Found. Affects Section 6a (C-1) and NFR-06. | Not Found |
| Q5 | 2026-10-19 | Is LLM/API integration permitted, or deterministic rules and local tooling only? | Human decision: "No LLM/API integration in v1. Use deterministic rules and local tools." Deterministic rules and local tools only; LLM/API integration is out of scope for v1; no repository content leaves the local machine. Affects IS-4, IS-6, AC-02, AC-08, NFR-01, NFR-06, Section 4, and Section 6a (C-2). | "This keeps costs down and avoids sending repo content to external services." (Lower cost; no repo content sent to external services.) |
| Q6 | 2026-10-19 | Mandatory validation checks: Markdown syntax, links, source-to-doc consistency, or all? | Human decision: "Markdown syntax and broken relative links are mandatory. Source-to-doc consistency is reported, not enforced." Mandatory = Markdown syntax + broken relative links; failures fail validation (analyst-proposed inference). Source-to-doc consistency is reported only and non-blocking. External/absolute URL handling: Not Found (not stated). Affects IS-6, IS-7, AC-02, AC-06, Section 4, and Section 6a (C-3). | Not Found |
| Q7 | 2026-10-19 | Maximum repository or diff size to support? | Human decision; final decision supersedes earlier wording (2026-10-19). Human, verbatim: "One threshold, no warning tier: if a diff exceeds 50 files or 2,000 changed lines, the tool stops, reports the size, and asks for a split. Anything at or below the cap is processed normally." Decision: single threshold; either limit (more than 50 files OR more than 2,000 changed lines) triggers a stop; the tool reports the diff size and asks the human to split the diff; a diff at or below the cap is processed normally; there is no warning tier. Whether size is counted from added plus deleted lines: Not Found. Repository-size limit: Not Found. History: the initial answer ("reject diffs above a fixed limit (for example, 50 files or 2,000 changed lines) with a clear message") was superseded by this decision. Affects IS-1, IS-7, AC-01, AC-05, NFR-02, Section 4, Section 6a (C-4), and Section 7. | Not Found |
| Q8 | 2026-10-19 | Behavior when several documentation files match the same source change? | Human decision: "list all candidates and ask the human which to update. Don't pick one silently." When multiple documentation files match a source change, the system lists all candidates and asks the human which to update; it never silently selects one. How the human is asked, given patch-file output (Q3) and delivery (Q9: terminal report plus patch file): Not Found (no mechanism assumed). Behavior if the human gives no answer: Not Found. Affects IS-3, IS-4, IS-7, IS-8, AC-01, AC-07, Section 4, Section 6a (C-5), and Section 7. | Not Found beyond the human's words. |
| Q9 | 2026-10-19 | Result delivery: terminal report, patch, GitHub PR comment, or combination? | Human decision: "a terminal report plus a generated patch file." (verbatim, human). Results are delivered as a terminal report plus a generated patch file. GitHub PR comment is not selected, so it is out of scope for v1, consistent with Q1 (local Git diff only). Patch file location, name, and format: Not Found. How the Q8 "ask the human" step works with this delivery: still Not Found. Affects IS-7, AC-07, Section 4, and Section 6a (C-6). | Not Found |
| Q10 | 2026-10-19 | Available CI environment and dependency/security scanning tools? | Human decision: "local tests only" (verbatim, human). Interpretation: verification is by local tests only; no CI environment is relied on for v1, and CI integration is out of scope for v1. Which dependency/security scanning tools, if any, are available: Not Found (not stated); none is assumed. Affects Section 4, NFR-01, NFR-06, and Section 6a (C-7). | Not Found |

## 8a. Items Pending Human Confirmation

None. No pending decision items other than human sign-off (Section 9).

Resolved 2026-10-19 (no longer pending): Q7 threshold (single threshold, 50 files or 2,000 changed lines, either limit, no warning tier) and the NFR-06 repeatable-output sentence (human-confirmed wording in Section 6).

## 9. Approval

Not approved. All ten clarification questions (Q1-Q10) are decided. No pending decision items other than human sign-off to proceed to Step 2.
