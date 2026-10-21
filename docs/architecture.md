# DOCSYNC Architecture (Step 2)

- Input: `docs/requirements.md` (Status: Approved 2026-10-19)
- Date drafted: 2026-10-20
- Status: Approved (2026-10-21, human sign-off)

## 0. Items the requirements left as Not Found, and how they were resolved

Section 8 of the requirements has no Open questions (Q1-Q10 are all decided). The requirements recorded several details as "Not Found". The human resolved them on 2026-10-21 as decisions D1-D9 and the A6 decision D10 (requirements Section 8b). This table maps each item to its decision. This document does not invent answers beyond those decisions.

| # | Not Found item (requirements ref) | Resolution in this design |
|---|---|---|
| A1 | Patch file location, name, format (C-6, IS-7, AC-07) | Resolved by D3 (human decision): unified diff at `output/docsync.patch`. The writer refuses to overwrite an existing file. `output/` is excluded by `.gitignore`. |
| A2 | How the human is asked to choose among multiple candidate docs, and what happens on no answer (C-5, IS-3, IS-4, Section 7) | Resolved by D4 (human decision): no interactive prompt. The tool lists all candidates and exits without a patch. The human re-runs with `--target <path>`. The tool never selects a target. |
| A3 | Behavior when no Markdown validator is available (IS-6) | Resolved by D5 (human decision): standard-library checks for unbalanced code fences and malformed link syntax. A check that is unsupported or not performed is reported as "not checked", never as passing, and validation does not pass. |
| A4 | External/absolute URL handling (IS-6, C-3) | Resolved by D9 (human decision): external URL validation is outside v1 scope. URLs are not checked and not network-fetched (C-2). This is reported as a limitation. |
| A5 | Whether size counts added plus deleted lines; repository-size limit (C-4) | Counting rule resolved by D6 (human decision): files are counted as files, and changed lines are added plus deleted. The repository-size limit is still Not Found; only the diff cap is defined. |
| A6 | Packaging, framework, dependency management, test tool (C-1, NFR-06) | Resolved by D10 (human decision): tests use Python's standard-library `unittest`. Distribution packaging is out of v1 scope. Framework and dependency management stay Not Found; this design uses the standard library only, so none is needed. |
| A7 | Whether other checks such as empty output are mandatory (AC-06) | Resolved by D7 and D2 (human decisions): non-empty output is a mandatory check. Empty generated output produces no patch. |
| A8 | Dependency/security scanning tools (C-7, NFR-01) | Resolved by D9 (human decision): dependency/security scanners are outside v1 scope. None is assumed or run. This is reported as a limitation. |
| A9 | Behavior when a run partially fails (Section 7, "Generator or validation step fails partway") | Resolved by D1 (human decision): all-or-nothing. Any pipeline-stage failure writes no patch (see Section 6). |

Note: the task brief refers to "section 8 edge cases". In the approved requirements, the edge cases are in Section 7 and Section 8 is the clarification table. Section 7 is used here.

Details still Not Found (no decision covers them): how the tool reacts when `--target` names a path that is not `README.md` or Markdown under `docs/`, or that is not among the matching candidates; the repository-size limit; the "generated" and "very large" file detection rules; the secret-pattern list; and the instruction-like-text detection rules.

## 1. Design principles

- Deterministic, local only (C-2, Q5): no network, no LLM, no external API. The same input gives the same output (NFR-06).
- Four separated stages (NFR-03): change analysis, documentation mapping, generation, and validation. Each is its own module with a typed, immutable data contract. No stage imports another stage's internals.
- Read-only toward the repository (Q3, IS-8): the tool never writes to documentation files, and never runs commit, push, merge, or publish. The only artifact written is the patch file, and only outside the tracked documentation targets.
- Repository text is data (AC-08): no repository content is ever interpreted as an instruction, executed, or used to build a command.
- "Not Found" over invention (AC-03): every generated claim must cite evidence, or it is reported as Not Found.

## 2. Components and responsibilities

| Component | Responsibility | Requirement refs |
|---|---|---|
| CLI / Orchestrator (`cli`) | Parses arguments, runs the stages in order, stops on a gate failure, and decides the exit status. Contains no analysis, mapping, generation, or validation logic. | IS-1, NFR-03 |
| Input Resolver (`input`) | Validates the repository path (exists, readable, is a Git repo). Produces a `ChangeRequest`. | IS-1, AC-05, NFR-02 |
| Git Adapter (`gitadapter`) | The only module that runs `git`. It runs read-only commands (diff, rev-parse) via an argument list, without a shell. It returns the raw diff text and file stats. | IS-2, AC-05 |
| Size Gate (`sizegate`) | Applies the single cap: more than 50 files or more than 2,000 changed lines (either limit). Changed lines are added plus deleted (D6). Over the cap it stops, reports the size, and asks for a split. There is no warning tier and no partial processing. | IS-1, C-4, AC-05, NFR-02 |
| Change Analyzer (`analysis`) | Parses the diff into `ChangedFile` records. Classifies each file as source, binary, generated, unsupported, or too large. Extracts evidence such as changed symbols and signatures with deterministic parsers. Excludes non-source files from generation and reports them. | IS-2, AC-01, AC-03, Section 7 |
| Doc Mapper (`mapping`) | Discovers candidate targets, which are only `README.md` and `docs/**/*.md`. Maps each source change to candidates by deterministic rules. Emits `MappingResult`: zero candidates (AC-04), one, or several (the Q8 path). It never selects among several. | IS-3, AC-01, AC-04, C-5 |
| CLI `--target <path>` option (in `cli`) | Names the one documentation file to update. With several candidates and no `--target`, the tool lists all candidates and exits without a patch; the human re-runs with `--target`. There is no interactive prompt and no Chooser interface. The tool never selects a target (D4). | Q8, C-5 |
| Doc Generator (`generation`) | Takes confirmed (change, target) pairs and builds proposed edits from rule templates. Each edit carries a reason and supporting source files. It emits proposed content in memory only. If evidence is insufficient, it emits a "Not Found / needs clarification" item instead of text. | IS-4, AC-02, AC-03, NFR-04, NFR-05 |
| Validator (`validation`) | Runs checks on the proposed content: Markdown syntax (mandatory), broken relative links (mandatory), and non-empty output (mandatory). The Markdown checks are standard-library checks for unbalanced code fences and malformed link syntax (D5). A check that is unsupported or not performed is reported as "not checked", never as passing, and validation does not pass. Reports source-to-doc consistency as non-blocking findings. Each result carries enough detail (file, line, rule) to investigate. | IS-6, AC-06, C-3 |
| Patch Writer (`output`) | Renders the proposed edits as a patch file for human review (unified diff at `output/docsync.patch`, D3). It never touches documentation files and refuses to overwrite an existing file (D3). It writes only after all mandatory validation passes (D2), and never when the generated output is empty (D7). A hunk containing a secret-like value is withheld entirely (D8). | IS-4, IS-8, AC-07, C-6 |
| Reporter (`report`) | Renders the terminal report: files examined, files proposed for change, validation results, limitations, candidate lists, and consistency findings. Limitations always state that external URLs are not checked and that no dependency/security scanner is run (D9). Applies secret redaction (Section 7). | IS-5, IS-7, C-6 |
| Redactor (`redact`) | Masks secret-like strings in anything printed or logged. Used by Reporter and error handling. For the patch, a hunk containing a secret-like value is withheld entirely instead of masked (D8); only its file and line are reported. | AC-08, NFR-01 |

## 3. Technology choices

| Choice | Justification | Requirement |
|---|---|---|
| Python 3.12 | Mandated language and runtime. | C-1 (Q4) |
| Standard library only by default (`subprocess`, `pathlib`, `re`, `difflib`, `dataclasses`, `logging`) | Keeps distribution packaging out of v1 (D10), keeps all processing local, and keeps the attack surface small. Any third-party addition would need a human decision. | C-1, C-2, NFR-01 |
| Local `git` CLI invoked through `subprocess.run([...], shell=False)` | Local Git diff is the only input. Using an argument list avoids shell injection from paths. It uses read-only subcommands. | Q1, IS-2, AC-08 |
| Rule tables and regex or AST-based extractors (Python `ast` for `.py` sources; other languages beyond a generic text diff are Not Found) | Deterministic rules, no LLM. Language coverage is deliberately bounded. | Q5, Section 4 ("not every language") |
| `difflib` for patch rendering | Deterministic, local, human-readable diff output. Output is a unified diff written to `output/docsync.patch` (D3). `output/` is excluded by `.gitignore`, and an existing file is never overwritten. | Q3, NFR-05 |
| Frozen dataclasses as stage contracts | Keeps stages separated and unit-testable with fixtures. | NFR-03, NFR-06 |
| Local fixture-based tests with temporary Git repositories, run with the standard-library `unittest` (D10) | No external services are needed. | NFR-06, C-7 |
| No CI dependency | Verification is by local tests only. | Q10, C-7 |
| Markdown validation: standard-library checks (D5) | Checks for unbalanced code fences and malformed link syntax, using only the standard library. A check that is unsupported or not performed is reported as "not checked", never as passing, and validation does not pass. | IS-6, Q6 |

## 4. Data flow

```
repo path (or local diff selection)
   |
   v
[Input Resolver] --invalid path/unreadable--> STOP (clear message)
   |
   v
[Git Adapter] --git missing / not a repo / diff fails--> STOP (clear message)
   |  raw diff + stats
   v
[Size Gate] --empty--> STOP "no changes"
   |         --over cap (>50 files or >2,000 lines)--> STOP: report size, ask for split
   v
[Change Analyzer] -> ChangedFile[] (+ skipped: binary/generated/unsupported/large)
   |
   v
[Doc Mapper] -> MappingResult per change
   |      zero candidates  -> report "no suitable documentation target" (no files created)
   |      one candidate    -> proceed
   |      many candidates  -> --target given: use it; otherwise list all candidates and exit with no patch (D4)
   v
[Doc Generator] -> ProposedEdit[] (reason + supporting sources) or NotFound items
   |
   v
[Validator] -> ValidationReport (mandatory: syntax, relative links, non-empty output; non-blocking: consistency)
   |      any failed or "not checked" mandatory check -> no patch (D2, D5, D7)
   v
[Patch Writer] -> output/docsync.patch (human review; refuses to overwrite)   [Reporter] -> terminal report
   (any stage failure above -> no patch, report names failed stage, D1)
   |
   v
HUMAN reviews the patch and decides whether to apply it
```

Stage boundaries carry only data objects. Each stage returns a result or a typed error. The orchestrator is the only place that sequences stages and decides whether to stop.

## 5. Human-approval preservation (G4, IS-8, AC-07)

- The tool has no code path that edits `README.md` or `docs/**`, and none that runs `git commit`, `push`, `merge`, `apply`, `checkout`, `reset`, or publish commands. The Git Adapter uses a fixed allow-list of read-only subcommands.
- The output is a patch file plus a terminal report. A human applies the patch, using their own tooling and their own decision.
- Multiple matching targets always go to the human (Q8): the tool lists all candidates and exits without a patch, and the human re-runs with `--target <path>` (D4). The tool never selects a target, and there is no prompt that silence could answer.
- Failing validation never auto-applies anything. The patch is written only if all mandatory checks pass (Markdown syntax, relative links, non-empty output). A failed check produces a report with file, line, and rule (AC-06) and no patch (D2).
- Test: a fixture-based test asserts that the working tree and Git history are unchanged after a run.

## 6. Error handling for the Section 7 edge cases

All errors become typed results with a clear message and a non-zero exit status. The messages pass through the Redactor, and no stack trace includes file contents.

| Edge case | Handling |
|---|---|
| Repository path does not exist or cannot be read | Input Resolver stops with a message naming the path (redacted if needed). No Git call is made. |
| Git unavailable, not a Git repo, or diff command fails | Git Adapter returns a typed error with the failing step and exit code. The tool stops, produces no patch, and does not retry silently. |
| No changed files | Size Gate/Analyzer returns "empty change set" status. No documentation changes are generated (AC-05). |
| Binary, generated, very large, or unsupported files | Analyzer classifies and skips these files, and lists them under Limitations. The "generated" detection rules and the "very large" per-file threshold are Not Found. Only the diff cap is defined. |
| Diff over the cap | Size Gate stops before analysis. It reports file count and changed-line count, and asks the human to split the diff. No partial processing, no warning tier. Changed lines are added plus deleted (D6). |
| No matching documentation file | Mapper reports "no suitable documentation target found". No file is created and no arbitrary target is used (AC-04). |
| Multiple matching documentation files | All candidates are listed and the tool exits without a patch (Q8, D4). The human re-runs with `--target <path>`. The tool never selects one. How it reacts to an invalid `--target` is Not Found. |
| Broken links or malformed Markdown | The Validator reports file, line, and rule. Failure of either mandatory check fails validation and no patch is written (D2). External URLs are not checked, and this is reported as a limitation (D9). |
| Empty generated output | No patch is written (D7). The report says the output was empty. |
| Source files disagree or lack information | The Generator emits a "Not Found / needs clarification" item instead of text (AC-03, IS-5). Conflicts are listed with the files involved. |
| Generator or validation step fails partway | All-or-nothing (D1). Any stage failure writes no patch. The report names the failed stage and the completed units. Nothing is written to documentation files, since the tool never writes them. |
| Prompt-injection-like text or secret-like strings in the repo | Handled per Section 7 below. The text is treated as data. Secret-like values are masked in printed and logged output, and a patch hunk containing one is withheld entirely (D8). |

## 7. Security approach (AC-08, NFR-01)

Instructions as data:
- Repository, diff, and user-story text is only parsed, matched, and quoted. It is never executed, evaluated, or used to choose commands, paths, or tool behavior.
- There is no `eval`, `exec`, or dynamic import of repository content, and no shell. The Git Adapter takes only validated paths. Option-like paths are passed after `--` so they cannot be read as flags.
- Instruction-like phrases (for example, "ignore previous instructions") are not acted on. The Analyzer may flag them as an informational finding. The detection rules are Not Found, and flagging is optional.

Secrets:
- The Redactor masks secret-like patterns (for example, key/token/password assignments, private-key blocks, and well-known token prefixes) before any output. The exact pattern list is Not Found and will be defined at implementation and covered by tests.
- Secret-like values are never written to logs, the terminal report, error messages, or the patch file. If a proposed edit would contain one, the tool withholds the entire hunk and reports only the file and line, never the value (D8). If every hunk is withheld, the output is empty and no patch is written (D7).
- The tool reads no environment credentials, config tokens, or `.env` files. Such files are not documentation targets. Logging records counts and paths, never file contents.
- No secret is ever committed, because the tool never commits.

Local-only and least privilege:
- No network or external service calls. v1 has no LLM/API integration, so no repository content leaves the machine (C-2, Q5). No Jira or Confluence integration exists (Section 4).
- Filesystem access is read-only on the repository. The one write is the patch file at `output/docsync.patch` (D3). The writer must refuse any path inside `README.md` or `docs/`, and it refuses to overwrite an existing patch file (D3).
- Git is run with read-only subcommands only. Dependency/security scanners are outside v1 scope (D9), so none is assumed or run, and the report says so. Using stdlib only reduces supply-chain exposure.

## 8. Maintainability and testability (NFR-03, NFR-04, NFR-05, NFR-06)

- Each stage is a separate module behind a narrow function or interface, so it can be tested alone with in-memory fixtures. Only the Git Adapter needs a temporary Git repository.
- Every `ProposedEdit` has a `reason` and `supporting_sources` field (NFR-04). Generators emit minimal hunks, with no reformatting of untouched text (NFR-05).
- Ordering is explicit and sorted (files, candidates, findings) so the same input yields the same output (NFR-06). The time of the run is not embedded in generated content.
- Tests run locally only (Q10), using the standard-library `unittest` (D10).

## 9. Requirement coverage summary

| Requirement | Addressed by |
|---|---|
| IS-1, AC-05, NFR-02 | Input Resolver, Git Adapter, Size Gate |
| IS-2, AC-01 | Git Adapter, Change Analyzer, Doc Mapper |
| IS-3, AC-04, Q8 | Doc Mapper, CLI `--target` option |
| IS-4, AC-02, AC-03 | Doc Generator |
| IS-5 | Analyzer, Mapper, Generator reports via Reporter |
| IS-6, AC-06 | Validator |
| IS-7, IS-8, AC-07 | Reporter, Patch Writer, Section 5 |
| AC-08, NFR-01 | Section 7, Redactor |
| NFR-03 | Section 2 component separation |
| NFR-04, NFR-05, NFR-06 | Section 8 |

## 10. Sign-off

Status: Ready for sign-off. Human approval of this architecture is required before Step 3; it has not been given. Decisions D1-D10 are human decisions recorded in requirements Section 8b (2026-10-21). Details still Not Found are listed under the Section 0 table.
