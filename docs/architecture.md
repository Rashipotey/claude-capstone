# DOCSYNC Architecture (Step 2)

- Input: `docs/requirements.md` (Status: Approved, 2026-10-22, including OQ-4 and OQ-5 as written in its Section 8c)
- Date drafted: 2026-10-20
- Last revised: 2026-10-22
- Status: Approved (2026-10-22, human sign-off on this revision)

References: Q1-Q10 and D1-D31 are in requirements Sections 8 and 8b. The rules are in requirements Section 6b. E1-E14 are the requirements' edge cases (Section 7). T01-T16 are tasks in `docs/impl-plan.md`.

## 0. Where the requirements' open items are resolved

| # | Item | Resolution |
|---|---|---|
| A1 | Patch location and format (C-6, AC-07) | D3, D26: unified diff at `output/docsync.patch`, relative to the directory the tool is run from. Section 2.6, Section 7. |
| A2 | Choosing among several candidate docs (C-5, Q8) | D4, D25, D30, OQ-4: no prompt; list candidates and exit without a patch; re-run with `--target`. Section 2.3. |
| A3 | Validation scope and not-checked handling (IS-6, C-3) | D5, D9, D27, OQ-5: Section 2.4. |
| A4 | Size counting (C-4) | D6, D12, D23: Section 2.1. |
| A5 | Partial failure (E10) | D1, D31: all-or-nothing, Section 4. |
| A6 | Diff source (IS-1, IS-2) | D21: `git diff HEAD`, tracked changes only. |
| A7 | Git hardening | D22: Section 7.3. |
| A8 | CLI and exit codes | D24: Section 6a. |
| A9 | Consistency findings | D28: one Not Found item in v1. |
| A10 | Packaging, framework, test tool | D10, D18: standard library, `unittest`, no packaging. |
| A11 | Defaults (OQ-1, OQ-2, OQ-3, OQ-6) | Applied as the defaults in requirements Section 8c. See Section 9a. |
| A12 | Design risks R12 and R14 | No decision exists. Guarantees and limits are stated in Section 8. |

## 1. Design principles

- Deterministic and local only (C-2, Q5): no network, LLM, or external API. The same input in the same environment gives the same output (NFR-06; limits in Section 8).
- Separated stages (NFR-03): analysis, mapping, generation, validation. Each is its own module with a typed, immutable data contract. No stage imports another stage's internals.
- Read-only toward the repository (Q3, IS-8): the tool never writes to documentation files and never commits, pushes, merges, or publishes. Its only write is the patch file (D26).
- Repository text is data (AC-08): never executed, never used to build a command.
- "Not Found" over invention (AC-03): every generated claim cites evidence or is reported as Not Found.

## 2. Components and responsibilities

| Component | Responsibility | Requirement refs |
|---|---|---|
| CLI / Orchestrator (`cli`) | Parses the repository path and `--target <path>` only (D24), with no prompt and no stdin. Runs the stages in the order of Section 4, stops on a gate failure, and maps each outcome class to its exit code. Holds no analysis, mapping, generation, or validation logic. | IS-1, NFR-03 |
| Input Resolver (`input`) | Takes the repository path (optional positional argument, default the current directory: OQ-1). Checks that it exists and is readable. Produces a `ChangeRequest`. | IS-1, AC-05, NFR-02 |
| Git Adapter (`gitadapter`) | The only module that runs `git`. Read-only subcommands from a fixed allow-list, via an argument list and no shell, hardened as in Section 7.3. Confirms the path is the repository root (`rev-parse --show-toplevel`); any other path is an input error, exit 3 (OQ-1 default, Section 9a). Before any diff call it runs the content-filter preflight (Section 7.3) and stops, exit 3, if the repository defines a content filter. Returns `git diff HEAD` output (D21), file stats, and untracked file names. A repository with no `HEAD` is a Git error. | IS-2, AC-05 |
| Size Gate (`sizegate`) | Applies the single cap and the counting rules in Section 2.1. | IS-1, C-4, AC-05, NFR-02 |
| Change Analyzer (`analysis`) | Parses the diff into `ChangedFile` records and classifies each as source, generated, documentation, test, deleted, or unsupported. Only source files go on to mapping. The others are skipped and reported (a deleted file is "not analyzed"). Extracts changed symbol names for `.py` files; other text files get a generic text diff and no symbol names (D17). | IS-2, AC-01, AC-03, E4 |
| Doc Mapper (`mapping`) | Maps each source file to at most one candidate (Section 2.2). | IS-3, AC-01, AC-04, C-5 |
| Target Resolver (in `mapping`) | Validates `--target` and decides the run's scope (Section 2.3). Kept out of the CLI. | Q8, C-5 |
| Doc Generator (`generation`) | For each in-scope (change, target) pair, builds an edit: a reason line plus the changed symbol names, with supporting source files (D20, NFR-04). No free text, no run time or random value. Insufficient or conflicting evidence, including a change with no symbol names, becomes a "Not Found / needs clarification" item listing the files involved (AC-03). Output stays in memory. | IS-4, AC-02, AC-03, NFR-04, NFR-05 |
| Redactor (`redact`) | Masks secret-like text in everything printed or logged, and tells the Patch Writer whether a hunk contains a secret-like value (Section 7.2). | AC-08, NFR-01 |
| Validator (`validation`) | Runs the mandatory checks and reports the non-mandatory consistency item (Section 2.4). | IS-6, AC-06, C-3 |
| Patch Writer (`output`) | Pre-checks for an existing patch, then writes the unified diff (Section 2.6). | IS-4, IS-8, AC-07, C-6 |
| Reporter (`report`) | Renders the terminal report (Section 2.5). | IS-5, IS-7, C-6 |

### 2.1 Size Gate rules (D6, D12, D14, D23)

- Cap: more than 50 files or more than 2,000 changed lines, either limit. Over the cap the tool stops, reports both counts, and asks for a split. There is no warning tier, no partial processing, and no repository-size limit.
- Every diff entry counts as one file, including entries later skipped as generated. Very large files count toward the cap only.
- Text entries count added plus deleted lines.
- A rename or copy without a content change is 1 file and 0 lines. With a content change it counts the changed lines.
- A deleted file is 1 file plus its deleted lines, and is reported as not analyzed.
- A binary, mode-only, or submodule entry stops the run with a typed "unsupported entry" error that names the path and kind. It is never counted as zero. The unsupported-entry check runs before the cap check, because line counts for such entries are unknown (design choice, Section 9a).

### 2.2 Classification and mapping (D13, D17, D19)

- Generated: paths matching `*.lock`, `*.min.*`, `dist/**`, `build/**`. Documentation: `README.md` and `docs/**`. Test: under a `test` or `tests` directory, or named `test_*.py` or `*_test.py`. Each skip is reported.
- Candidates are only `README.md` and `docs/**/*.md` in the working tree.
- A source file maps to `docs/<module>.md` if it exists, otherwise `README.md` if it exists, otherwise to no candidate.
- Module name: the file name without its last extension, lowercased. Directories are ignored. `__init__.py` uses its parent directory's name. Non-Python files use the same rule.
- The lookup is directly under `docs/`, by lowercased stem. The reported path is the doc's actual path. Files with the same module name give one candidate.

### 2.3 Target Resolver rules (D4, D11, D25, D30, OQ-4)

1. The run's candidate list is the sorted set of distinct docs that the source changes map to.
2. If no change has a candidate, the result is "no suitable documentation target" (AC-04, exit 7), with or without `--target`.
3. Without `--target`, when at least one change has a candidate:
   - If every source change maps to the same single doc, the run proceeds.
   - Otherwise (several docs, or some changes with no candidate) the tool lists all candidate docs with the changed files mapped to each, reports the changes with no candidate, and exits without a patch (exit 8).
4. With `--target`:
   - The target is validated first. It must be a path relative to the repository root, and `README.md` or Markdown under `docs/`, and one of the run's candidates. Absolute paths, any `..` segment, and any path whose resolved location is outside the repository (including through a symlink) are rejected. An invalid target exits non-zero (2), writes no patch, and lists the valid candidates.
   - Changes that map to the target are in scope.
   - Changes that map to another doc are intentionally out of scope. They are reported as "not addressed in this run" with the doc they map to. They are never omitted silently, never moved to the target, and never counted as processed. This is the only intentional exclusion of a change from the run's scope.
   - A change with no candidate is unresolved and blocks the patch (exit 8).
   - A Not Found item for an in-scope change is a reported result and does not block the patch. If every in-scope change yields only Not Found items, the output is empty and no patch is written (D7, exit 9).
5. The tool never selects a target and never prompts.

### 2.4 Validation scope (D2, D5, D7, D9, D27, D28, OQ-5)

Mandatory checks. Any failure, or any check not performed, writes no patch:

| Check | Scope | Result |
|---|---|---|
| Markdown syntax | Standard-library checks for unbalanced code fences and malformed link syntax (D5) on the proposed content | Failure reports file, line, rule |
| Relative links | Inline relative links and images, `[text](path)`, on the added lines of each edit. A path is resolved from the edited document's directory, against the working tree. A `#fragment` is stripped and the anchor is not checked. | A link to a missing file fails, with file, line, rule |
| Non-empty output | The generated output as a whole (D7) | Empty output: no patch |

- A mandatory check that is unsupported or not performed is reported as "not checked", is never reported as passing, and validation does not pass (D5).
- Outside the declared scope, and therefore limitations rather than failed or unperformed checks (OQ-5): external and absolute URLs, reference-style links, autolinks, anchor targets, and links on lines the edit does not add. The Reporter lists them as "not checked, outside v1 scope". They are never reported as passing and do not by themselves fail validation.
- Consistency is not computed in v1. The report carries one non-blocking item, "Not Found: consistency is not computed in v1" (D28).
- How a line is reported for a not-checked result: file and rule only (OQ-3 default).

### 2.5 Reporter contents

Files examined; files proposed; files skipped with the reason (generated, documentation, test, deleted, untracked as "not analyzed"); validation results including any "not checked"; candidate lists and "not addressed in this run" items; Not Found items including the consistency item. Limitations are always stated: external URLs are not checked; no dependency or security scanner is run (D9); untracked files are not analyzed (D21); the link kinds in Section 2.4 are outside the check (D27); consistency is not computed (D28). All report text passes through the Redactor.

### 2.6 Patch Writer rules (D1, D3, D26, D29, D31)

- The existing-patch pre-check runs at the start of the run, before any Git call. If `output/docsync.patch` exists, the run stops, names the file, and writes nothing (exit 11, a stage failure under D1).
- The patch is a unified diff produced with `difflib`, written to `output/docsync.patch` relative to the directory the tool is run from.
- It is written only if the run reaches the write stage with every condition met: no stage failure, no withheld hunk, all mandatory checks passed, non-empty output, no unresolved in-scope change.
- The file is created with exclusive creation, so an existing file is never overwritten, even if it appears after the pre-check. There is no `--force`.
- The `output/` directory is created only if it is missing (OQ-6 default).
- The writer refuses any path inside `README.md` or `docs/` and never edits `.gitignore`.
- The writer also refuses an `output` that is a symbolic link, a Windows junction, or another reparse point (exit 11, naming the path), before it resolves real paths for `output`. The real-path resolution described above is kept for the other path components. The Reporter states the resolved destination of the patch when it differs from `<cwd>/output/docsync.patch`. (Amendment, human decision 2026-10-25, "policy B"; the earlier text allowed a link to any directory other than `README.md` and `docs/`.)

## 3. Technology choices

| Choice | Justification | Requirement |
|---|---|---|
| Python 3.12 | Mandated language and runtime. | C-1 (Q4) |
| Standard library only (`subprocess`, `pathlib`, `re`, `difflib`, `dataclasses`, `logging`, `unittest`) | No third-party code, no packaging (D10, D18). Keeps processing local and the attack surface small. Any addition needs a human decision. | C-1, C-2, NFR-01 |
| Local `git` through `subprocess.run([...], shell=False)` | Local Git diff is the only input. An argument list avoids shell injection. | Q1, IS-2, AC-08 |
| Rule tables, regex, and Python `ast` for `.py` symbol names | Deterministic rules, no LLM. Other languages get a generic text diff only (D17). | Q5 |
| `difflib` for patch rendering | Deterministic, local, human-readable unified diff. | Q3, NFR-05 |
| Frozen dataclasses as stage contracts | Keeps stages separated and unit-testable. | NFR-03, NFR-06 |
| Fixture-based `unittest` tests with temporary Git repositories; no CI | No external services. Verification is by local tests only. | NFR-06, Q10, C-7 |

## 4. Data flow

```
repo path (and optional --target)
   |
   v
[Patch Writer pre-check] --output/docsync.patch exists--> STOP (names the file, exit 11)
   |
   v
[Input Resolver] --invalid path / unreadable--> STOP (exit 3)
   |
   v
[Git Adapter: root check, content-filter preflight, git diff HEAD, hardened]
   |         --git missing / not a repo root / content filter defined / no HEAD / diff fails--> STOP (exit 3)
   |  raw diff, stats, untracked names
   v
[Size Gate] --no tracked changes--> STOP "no changes" (exit 4)
   |         --binary / mode-only / submodule entry--> STOP "unsupported entry" (exit 6)
   |         --over cap--> STOP: report size, ask for split (exit 5)
   v
[Change Analyzer] -> ChangedFile[] (skipped and reported: generated, documentation, test, deleted)
   |         --nothing left to map--> STOP "no changes" class (exit 4)
   v
[Doc Mapper + Target Resolver] -> MappingResult per change, then the run's scope
   |         --no change has a candidate (with or without --target)--> STOP "no suitable documentation target" (exit 7)
   |         --several docs or unmapped changes, no --target--> STOP: list candidates (exit 8)
   |         --invalid --target--> STOP (exit 2); --target but a change has no candidate--> STOP (exit 8)
   v
[Doc Generator] -> ProposedEdit[] and NotFound items (in-scope changes only)
   |
   v
[Redactor / withhold] --any hunk with a secret-like value--> STOP, no patch; file and line only (exit 10)
   |
   v
[Validator] -> ValidationReport
   |         --failed or "not checked" mandatory check, or empty output--> STOP, no patch (exit 9)
   v
[Patch Writer] -> output/docsync.patch (exclusive creation)      [Reporter] -> terminal report
   |
   v
HUMAN reviews the patch and decides whether to apply it
```

Stage order (D31): generate, redact and withhold, validate, write. Any stage failure writes no patch, and the report names the failed stage and the completed units (D1, exit 12). Stages exchange only data objects and return a result or a typed error. The orchestrator alone sequences the stages and decides whether to stop.

## 5. Human-approval preservation (G4, IS-8, AC-07)

- No code path edits `README.md` or `docs/**`, or runs `commit`, `push`, `merge`, `apply`, `checkout`, `reset`, or publish commands. The Git Adapter allows only a fixed set of read-only subcommands.
- The output is a patch file plus a terminal report. A human applies the patch with their own tooling and decision.
- Multiple targets always go to the human (Q8, D4). There is no prompt that silence could answer.
- A failed check never applies anything. The patch is written only if all mandatory checks pass.
- Test (NF-15): no tracked file, documentation file, or Git history changes during a run. On a successful run the generated patch is the only new file. On every failed or stopped run no patch is written and nothing else changes. The failure cases are: a stage failure, a withheld hunk, a failed or not-checked validation, empty output, an unresolved candidate list, an invalid target, an existing patch, an unsupported entry, a diff over the cap, a repository content filter, and a Git or input error.

## 6. Error handling for the requirements' edge cases

All errors become typed results with a clear message and a non-zero exit status. Messages pass through the Redactor, and no stack trace includes file contents. Codes are in Section 6a.

| Edge case | Handling | Exit |
|---|---|---|
| E1 Repository path missing or unreadable | Input Resolver stops with a message naming the path. No Git call is made. | 3 |
| E2 Git unavailable, not a repository root, no `HEAD`, diff fails, or a content filter is defined | Typed error with the failing step and exit code. For a content filter, the message names the config key and its origin file, never its value. No patch, no silent retry. | 3 |
| E3 No changed files | "No changes." Untracked files, if any, are listed as "not analyzed". | 4 |
| E4 Binary, generated, very large, unsupported | Binary, mode-only, and submodule entries stop the run (Section 2.1). Generated paths are skipped and reported. Very large files count toward the cap only. | 6 for unsupported entries |
| E5 Diff over the cap | Size Gate stops before analysis and asks for a split. | 5 |
| E6 No matching documentation file | "No suitable documentation target found." No file is created (AC-04). | 7 |
| E7 Multiple matching documents | All candidates are listed, no patch. The human re-runs with `--target`. | 8 |
| E8 Broken links or malformed Markdown | Validator reports file, line, rule; no patch. Link kinds outside the check are limitations, not failures (Section 2.4). | 9 |
| E9 Sources disagree or lack information | The Generator emits a Not Found item (AC-03). The patch is still written if other in-scope edits pass. | 0, or 9 if the output is empty |
| E10 Generator or validation fails partway | All-or-nothing. The report names the failed stage and completed units. | 12 |
| E11 Injection-like text or secret-like values | See the two cases below the table. | 10 for a withheld hunk |
| E12 Untracked files exist | Not read; listed as "not analyzed"; stated as a limitation. | unchanged |
| E13 Patch file already exists | Detected by the start-of-run pre-check; names the file; no patch. | 11 |
| E14 Invalid `--target` | Rejected by the Target Resolver; valid candidates are listed. | 2 |
| Changes outside the selected target (OQ-4) | Reported as "not addressed in this run". The patch is still written. | 0 |
| Empty generated output | No patch (D7). The report says the output was empty. | 9 |

E11 has two separate cases (D8, D16, D31):

1. Instruction-like text is always treated as data. It is parsed, never executed, never obeyed, and never detected as a special case (D16). It does not trigger withholding and changes no behavior.
2. A secret-like value, meaning text that matches the implemented pattern set (Section 7.2), causes the whole hunk to be withheld and no patch to be written. Only the file and line are reported.

## 6a. Exit status (D24)

Exit 0 only when a patch was written, including a run that reports "not addressed" items. Every other outcome exits non-zero with a distinct code per outcome class. The numbers and the all-skipped case are the OQ-2 default and match requirements Section 6b.12.

| Code | Outcome |
|---|---|
| 0 | Patch written |
| 2 | Usage error or invalid `--target` (D11, D30) |
| 3 | Input or Git error (path, not a repository root, content filter defined, no `HEAD`, diff failed) |
| 4 | No changes (also untracked files only, or every changed file skipped as documentation, test, or generated) |
| 5 | Diff over the cap |
| 6 | Unsupported entry (binary, mode-only, submodule) |
| 7 | No suitable documentation target (no change has a candidate) |
| 8 | Unresolved candidates (several docs without `--target`, or a change with no candidate while others have one) |
| 9 | Validation failed, a mandatory check not performed, or empty output |
| 10 | Secret-like hunk withheld |
| 11 | Existing patch or patch write failure |
| 12 | Other stage failure; any uncaught error is converted to this code |

## 7. Security approach (AC-08, NFR-01)

### 7.1 Instructions as data

- Repository, diff, and user-story text is only parsed, matched, and quoted. It is never executed, evaluated, or used to choose commands, paths, or tool behavior.
- There is no `eval`, `exec`, or dynamic import of repository content, and no shell. The Git Adapter takes only validated paths, and option-like paths are passed after `--`.
- Instruction-like text is not detected in v1 (D16). It is data in every case.

### 7.2 Secrets

Detection is by pattern only. The minimum pattern set (D15) is:

- key, token, password, and secret assignments;
- PEM private-key headers;
- AWS-style access key IDs.

The full list is finalized by the T13 tests.

What is guaranteed, for text matching an implemented pattern:

- Report, log, and error text: the matched value is masked.
- The patch: every hunk is scanned, including added, removed, and context lines. A hunk with a match is withheld whole, and because the run is all-or-nothing, no patch is written (D8, D31). Only the file and line are reported, never the value.
- The tool's output contains only paths, counts, symbol names, reason lines, and, in the patch, lines of the target documents. It never prints raw diff content.

What is not guaranteed:

- A secret that matches no implemented pattern is not detected. Examples are a bare high-entropy string with no assignment context and a token format outside the minimum set.
- The guarantee covers only the output channels above.

The tool reads no environment credentials, config tokens, or `.env` files, and never commits, so it cannot commit a secret.

Tests: one fake value per minimum pattern category (T02, T13); negative fixtures (the word "password" with no value, and a line reading "ignore previous instructions") that must not cause masking or withholding; a fixture proving the fake value is absent from the report, the error text, and any written file.

### 7.3 Git hardening (D22, risk R1)

Required effects, from D22:

- Read-only subcommands only, an argument list, no shell.
- External diff drivers, text conversion (textconv), and the pager are disabled.
- User and system Git configuration is ignored.
- Execution-capable repository settings are overridden on the command line.
- The Git environment is cleaned of inherited variables.
- No content filter defined in the superproject configuration can run during collection. The run stops before any diff call if one is defined (preflight below). For submodules the protection is qualified: the preflight cannot see a submodule's own configuration, so the diff commands add `--ignore-submodules=dirty`, which was quiet in every tested state but is verified only on Windows with Git 2.56.0 and the tested fixtures (limitations in Section 9a).

The exact flag list is not decided here. Task T05 fixes it. The Status column is the intended treatment, not a verified result. The last column states the evidence each claim needs before it may be made:

| Effect | Status | Candidate mechanism (for T05 to confirm) | Required test evidence |
|---|---|---|---|
| Subcommand allow-list, no shell | Specified | Fixed allow-list in the Git Adapter | T04: forbidden subcommands rejected; a path starting with `-` is data |
| External diff driver off | Overridden | `--no-ext-diff` | Hostile fixture with a driver command that would write a marker file; marker absent |
| textconv off | Overridden | `--no-textconv` | Hostile fixture with a textconv command; marker absent |
| Nested submodule diffs and submodule working-tree state | Overridden (qualified) | `--submodule=short` and `--ignore-submodules=dirty` in the shared diff argument group (amendment approved by the human on 2026-10-22; finding H1: a clean filter in a submodule's own configuration ran during `git diff HEAD` with `--submodule=short` alone, and the preflight reads only the superproject configuration) | Hostile fixture: a submodule whose own configuration defines a clean filter writing a marker; the live control must fire, the protected run leaves the marker absent. Evidence is Windows, Git 2.56.0 (2.56.0.windows.2), one fixture family; no universal protection is claimed. `=untracked` did not help; `=all` was rejected because it removes the submodule entry and pointer change that D23/T06 need. |
| Pager off | Overridden | `--no-pager` | Hostile fixture with a pager command; marker absent |
| `core.fsmonitor` | Overridden | `-c core.fsmonitor=false` | Hostile fixture with an fsmonitor command; marker absent |
| User and system configuration | Ignored | Environment settings such as `GIT_CONFIG_NOSYSTEM` and `GIT_CONFIG_GLOBAL` | Hostile user-level configuration; marker absent |
| Inherited Git environment variables | Cleaned | Rebuilt environment | Test with hostile `GIT_EXTERNAL_DIFF` and `GIT_PAGER` set; marker absent |
| Content filters (`filter.<name>.clean`, `.smudge`, `.process`) | Fail-safe stop | Preflight (below), before any diff call | Hostile fixtures: a `clean` filter, a `process` filter, one defined in a worktree config, and one defined through an include; each must stop the run with exit 3 and a marker file absent. Control fixtures: an attribute bound to an undefined filter proceeds; a repository with no filters proceeds. |
| Other repository-controlled settings | Not neutralized | None specified | No protection is claimed |

Content-filter preflight (design choice under D22, Section 9a):

- A working-tree diff can run the commands of content filters. A filter command exists only if a Git config defines it; a `.gitattributes` binding alone defines no command. Because the filter name is chosen by the repository, the architecture does not try to override each name. It refuses to run instead.
- Before any diff or listing call, the Git Adapter reads the effective repository configuration with a read-only `git config --list --show-origin` call, run with the same hardened environment (user and system configuration ignored, includes followed). That is the only use of `config`, and it only lists.
- If the output contains any key of the form `filter.<name>.clean`, `filter.<name>.smudge`, or `filter.<name>.process`, the run stops with a typed Git error (exit 3) and no patch. The message names the key and its origin file and never prints the value.
- The preflight reads configuration only and does not execute filter commands. The diff does not start until it passes.
- The guarantee depends on Git's configuration model: the effective configuration is what remains after user and system configuration are ignored, the environment is cleaned, and repository, worktree, and included files are read. T05 must cover each of those sources with a fixture. If a source is found that the preflight cannot see, T05 must report it and the human decides. No protection is claimed beyond the fixtures.

Other limits:

- A repository's own `.git/config` cannot be switched off. Protection against its other execution-capable settings rests on the command-line overrides, the preflight, and the allow-list. Any such setting not listed in the table is outside the claim.
- Claims are made only for effects the hostile-configuration tests demonstrate.

### 7.4 Local-only and least privilege

- No network or external service calls. No repository content leaves the machine (C-2, Q5).
- Filesystem access is read-only on the repository. The one write is the patch (Section 2.6).
- `.gitignore` caveat (D3, D26): an `output/` entry protects the patch only when the output lies inside the repository that the ignore file governs and the pattern matches. If the tool runs from another directory, the analyzed repository's `.gitignore` does not cover the patch. Maintaining the entry is the user's responsibility.
- Dependency and security scanners are outside v1 scope (D9). None is assumed or run, and the report says so.

## 8. Maintainability, determinism, and patch applicability

Maintainability (NFR-03 to NFR-05):

- Each stage is a separate module behind a narrow interface, testable alone with in-memory fixtures. Only the Git Adapter needs a temporary Git repository.
- Every `ProposedEdit` has a `reason` and `supporting_sources` field. Generators emit minimal hunks without reformatting untouched text.

### 8.1 Determinism (NFR-06, risk R14)

Guaranteed: for the same tool version, the same Python 3.12, the same Git version, and the same repository content (`HEAD`, index, working tree, documents), the patch and the report text are identical. This rests on:

- explicit sorting of files, candidates, and findings, by path code points, never by locale;
- no timestamps and no random values in any output;
- paths written in one form (forward slashes).

Design choices that support this (Section 9a):

- Git output is decoded as UTF-8 with an explicit error policy. Text that cannot be decoded is a typed failure (exit 12, no patch). Replacement characters are never substituted.
- Paths are read from Git in a form that does not depend on locale. T05 chooses the mechanism.
- Document line endings are not normalized. Added lines use the line ending of the target document.

Not guaranteed (explicit limitations): identical output across different Git versions (diff output details such as rename detection can differ), across operating systems, or across locale and encoding settings. Local tests run on one platform only (Q10).

Tests: run the tool twice on the same temporary repository and compare the outputs; create the files in a different order; a non-ASCII path; an LF document and a CRLF document; confirm that the report contains no timestamp.

### 8.2 Patch applicability (risk R12)

Guaranteed: the patch is produced from the documents' working-tree content at generation time, so its context lines equal that content.

Not guaranteed: that the patch applies cleanly to later content, to a document with different line endings, or after the document changes. The tool never runs `git apply --check`, because `apply` is forbidden (Section 5). The human reviews and applies the patch with their own tooling (AC-07).

Test (test code only, not a runtime check): a helper applies the generated hunks in memory to the original document and must reproduce the proposed content. Context lines must equal the original lines. The Reporter's always-stated limitations list is fixed by the requirements, so this limitation is documented here and not added to the report.

## 9. Coverage and traceability

| Requirement | Addressed by |
|---|---|
| IS-1, AC-05, NFR-02 | Input Resolver, Git Adapter, Size Gate, Section 6 |
| IS-2, AC-01 | Git Adapter, Change Analyzer, Doc Mapper |
| IS-3, AC-04, Q8 | Doc Mapper, Target Resolver |
| IS-4, AC-02, AC-03 | Doc Generator |
| IS-5 | Analyzer, Mapper, Generator, Reporter |
| IS-6, AC-06, C-3 | Validator (Section 2.4) |
| IS-7, IS-8, AC-07 | Reporter, Patch Writer, Section 5 |
| AC-08, NFR-01 | Section 7, Redactor |
| NFR-03 | Section 2 component separation |
| NFR-04, NFR-05 | Doc Generator, Section 8 |
| NFR-06 | Section 8.1 |
| G1, G2 | Doc Mapper, Doc Generator |
| G3 | Not Found items, consistency item, Reporter limitations |
| G4 | Section 5 |
| C-1, C-7 | Section 3 |
| C-2 | Section 7.4 |
| C-4 | Size Gate (Section 2.1) |
| C-5 | Target Resolver (Section 2.3) |
| C-6 | Patch Writer, Reporter |

AC-to-test traceability (tasks in `docs/impl-plan.md`):

| AC | Tests |
|---|---|
| AC-01 | T05 diff retrieval, T06 boundaries, T07 and T08 mapping, T16 end to end |
| AC-02 | T10 generation, T11b consistency item, T16 |
| AC-03 | T07, T10 Not Found items, T16 |
| AC-04 | T08 no-doc fixture, T15, T16 |
| AC-05 | T03, T04, T05, T06 (empty set, cap, unsupported entry), T16 |
| AC-06 | T11, T12 (file, line, rule; out-of-scope link kinds listed as limitations), T14, T16 |
| AC-07 | T09, T13, T14, T16 (the patch is the only new file; none on failure); Section 8.2 round-trip test |
| AC-08 | T02, T04, T05 (hostile configuration, content filter), T07, T13 (withheld hunk), T14, T16 |

Edge-case coverage by test:

| Edge case | Tests |
|---|---|
| E1, E2, E3 | T03, T04, T05 |
| E4, E5 | T06, T07, T07b |
| E6, E7, E14, out-of-scope changes | T08, T09 |
| E8 | T11, T12 |
| E9 | T10 |
| E10 | T15 |
| E11 | T02, T13, T14 |
| E12 | T05 |
| E13 | T13, T15 |
| Empty output, all-or-nothing | T13, T15, T16 |

Decision-to-component map:

| Decisions | Component |
|---|---|
| D1, D31 | Orchestrator, Patch Writer (Sections 2.6, 4) |
| D2, D5, D7, D9, D27, D28 | Validator (Section 2.4) |
| D3, D26, D29 | Patch Writer (Section 2.6) |
| D4, D11, D25, D30 | Target Resolver (Section 2.3) |
| D6, D12, D14, D23 | Size Gate (Section 2.1) |
| D8, D15, D16 | Redactor (Section 7.2) |
| D10, D18 | Section 3 |
| D13, D17, D19, D20 | Change Analyzer, Doc Mapper, Doc Generator |
| D21, D22 | Git Adapter (Section 7.3) |
| D24 | Orchestrator (Section 6a) |

## 9a. Design choices, applied defaults, and limitations

Design choices made in this document that no decision states. Each is the simplest way to meet an approved rule:

1. Untracked file names are listed with a read-only `git ls-files --others --exclude-standard` call. Ignored files are not listed, and file content is never read.
2. The Change Analyzer classifies documentation and test files. The Doc Mapper maps only source files.
3. The Target Resolver lives in `mapping`, so the CLI holds no mapping logic.
4. Exit code 7 means no change has a candidate. Exit code 8 means unresolved candidates.
5. The unsupported-entry check runs before the cap check.
6. Undecodable text is a typed failure (exit 12). Line endings are not normalized.
7. Content filters are handled by a fail-safe preflight that stops the run, not by overriding each filter name. This is stricter than an override and adds a read-only `git config --list --show-origin` call to the allow-list.

Applied defaults (requirements Section 8c; these are settled in this document and not open):

- OQ-1: the repository path is an optional positional argument that defaults to the current directory. The requirements leave subdirectory handling as Not Found, so the architecture applies the strict reading: the path must be the repository root, and any other path is an input error (exit 3). `--target` is relative to that root.
- OQ-2: the exit-code numbers in Section 6a, and exit 4 when every changed file is skipped.
- OQ-3: a not-checked result is reported with file and rule only.
- OQ-6: the `output/` directory is created when missing.

Limitations that no decision removes:

- R12 and R14, as stated in Sections 8.1 and 8.2.
- Secrets outside the implemented pattern set are not detected (Section 7.2).
- Execution-capable repository settings other than those in the Section 7.3 table are not neutralized, and no protection is claimed for them.
- The exact Git flag list is fixed in T05. By a human-approved amendment of 2026-10-22 the shared diff argument group includes `--ignore-submodules=dirty` (diff templates only; the allow-list stays six templates and the only `-c` option stays `core.fsmonitor=false`).
- Git limitations added by that amendment (Section 8 holds only determinism and patch-applicability limits, so they are listed here):
  - (a) A submodule with uncommitted or untracked content but an unchanged HEAD commit is not reported (invisible). A moved submodule pointer (mode 160000) is still reported.
  - (b) The submodule-protection evidence is limited to Windows, Git 2.56.0 (2.56.0.windows.2) and the tested fixtures. No protection is claimed for other Git versions or platforms.
  - (c) Known preflight over-refusal, kept as is (conservative, fails safe; human decision 2026-10-22): a `filter.*` key whose value contains `.clean`, `.smudge` or `.process` followed by `=` or end of line (for example `filter.x.required=run.clean`) is refused although it defines no content filter; and a configuration value such as `core.note=x.filter.y.clean=z` is accepted.

## 9b. Task traceability and the implementation plan

`docs/impl-plan.md` was synchronized with this architecture on 2026-10-22 and is pending human approval. For each task, the architecture requires the following, and "Plan today" records how the plan implements it.

| Task | The architecture requires | Refs | Plan today |
|---|---|---|---|
| T03, T04 | Optional positional repository path; the Git Adapter checks the repository root (exit 3). Allow-list: `rev-parse`, `diff`, `ls-files` (untracked names only), and `config --list --show-origin` (preflight only). | AC-05, E1, E2, D21, D22 | Matches. T04 enforces exact argument templates and an environment allow-list defined in T05, rejects any other form, and applies a timeout. |
| T05 | `git diff HEAD`, hardened. Content-filter preflight before any diff call. Untracked names listed, never read. Fixture matrix of Section 7.3. Fixes the exact flag list. | AC-01, AC-05, AC-08, E2, E3, E12, D21, D22 | Matches. T05 fixes the templates, flags, `core.fsmonitor` override, and environment, and states the limitations. It adds that the preflight fails closed (exit 3) if the command fails, its output cannot be parsed, or the repository's own configuration is not seen. This refines the preflight inside exit 3. |
| T06 | Counting rules of Section 2.1; the unsupported-entry check before the cap check. | AC-05, E4, E5, D23 | Matches. |
| T09 | `--target` and Target Resolver rules of Section 2.3: zero candidates first (exit 7); no `--target` and several docs or unmapped changes (exit 8); validation of the target (exit 2); out-of-scope changes reported and the patch still written; a change with no candidate blocks the patch; a Not Found item does not. Exit-code mapping. | AC-01, AC-04, AC-07, E6, E7, E14, D4, D11, D24, D25, D30 | Matches. |
| T11 | Mandatory syntax and non-empty checks; "not checked" never passes and no patch is written; file and rule only for a not-checked result (OQ-3). | AC-06, E8, D2, D5, D7 | Matches. |
| T11b | The single "Not Found: consistency is not computed in v1" item, non-blocking. | AC-02, D28 | Matches. T15 depends on T11b because the happy-path report contains the item. |
| T12 | Link check on the added lines only, from the edited document's directory; fragments stripped. Reference-style links, autolinks, anchors, external URLs, and unchanged lines are reported as limitations, never as passing, and do not fail validation (OQ-5). | AC-06, E8, D9, D27 | Matches. |
| T13 | Start-of-run pre-check and exclusive creation (exit 11); `output/` created if missing; the writer refuses a destination inside `README.md` or `docs/`; withheld hunk means no patch (exit 10); secret-pattern tests with negative fixtures. | AC-07, AC-08, E11, E13, D3, D8, D15, D26, D29, D31 | Matches. The destination is fixed with no output-path option. The guard refusal uses exit 11, which the architecture does not state separately and which the plan flags. |
| T15 | Stage order of Section 4; every stop maps to its exit code (Section 6a); any unexpected stage failure writes no patch and names the stage. | AC-01 to AC-08, E1 to E14, D1, D24, D31 | Matches. Expected outcomes keep their designated codes, and exit 12 is reserved for unexpected internal failures. |
| T16 | Unchanged-tree test with the patch as the only new file on success and no patch on any failure (Section 5); determinism tests (Section 8.1); round-trip test (Section 8.2); an instructions-as-data test. | AC-01 to AC-08, NFR-06 | Matches. The determinism test compares two equivalent fresh fixtures in separate working directories, so it does not conflict with exclusive creation. R12 and R14 stay as limitations. |

## 10. Sign-off

Status: Approved (2026-10-22). The human approved this revision as written, by instruction of 2026-10-22. The earlier approval (commit `9ba17d6`) covered the 2026-10-21 text only. No Git commit records this approval yet.
