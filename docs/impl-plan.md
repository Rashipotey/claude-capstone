# DOCSYNC Implementation Plan (Step 4)

- Inputs: `docs/requirements.md` (Approved 2026-10-22), `docs/architecture.md` (Approved 2026-10-22), `docs/design-review.md` (Approved 2026-10-21; re-approved 2026-10-22)
- Date: 2026-10-21 (revised 2026-10-22)
- Status: Approved (2026-10-22, human sign-off on this revision)

## 0. Basis and rules for this plan

- Human decisions applied: D1-D31 (requirements 8b; D11-D31 decided 2026-10-22), plus design review 5a: P4 all-or-nothing (no patch if any hunk is withheld or any stage fails), P5 path-based mapping only (no other mapping rules in v1), I1 fixed.
- The defaults in requirements Section 8c (OQ-1 to OQ-6) were approved with the requirements on 2026-10-22 and are applied as written. Design review proposals P6, P8, P10, P11, P12, and P13 are resolved by D13-D15, D23, D28, D21 and D24, the Section 9 traceability table, and the status corrections respectively. Anything not covered stays "Not Found". An implementer must not invent such details.
- Requirements, architecture, design review, and this plan are approved. Step 5 (implementation) runs one task at a time, as the human directs.
- Python 3.12, standard library only, tests with `unittest`, local fixtures only (C-1, D10, NFR-06). No network, no CI (C-2, C-7).
- Each task is sized for one implementer run. Repository text is data and is never executed (AC-08).
- Edge case references use Section 7 of the requirements (the brief's "section 8" is the clarification table). Edge cases are named E1-E14 as in requirements Section 7:
  E1 path missing/unreadable; E2 git unavailable/not a repo root/no HEAD/diff fails (or a content filter is defined, architecture 7.3); E3 no changed files; E4 binary/generated/very large/unsupported; E5 diff over cap; E6 no matching doc; E7 multiple matching docs; E8 broken links/malformed Markdown; E9 source files disagree or lack information; E10 generator/validation fails partway; E11 injection-like text or secret-like strings; E12 untracked files; E13 existing patch; E14 invalid `--target`.

## 1. Details and their status

| Ref | Item and status | Needed by |
|---|---|---|
| NF-1 | Resolved by D21: `git diff HEAD` (tracked changes, staged and unstaged). Untracked files are not analyzed and are listed as a limitation. No `HEAD` is a Git error. The IS-1 explicit file-set form is deferred. | T05, T15 |
| NF-2 | Resolved by D22. Enforced by the T05 templates and environment: fixed read-only argument templates with no shell; external diff (`--no-ext-diff`), textconv (`--no-textconv`), pager (`--no-pager`), and nested submodule diffs (`--submodule=short`) disabled; the single `-c` override `core.fsmonitor=false`; a rebuilt environment that drops inherited Git variables; user and system configuration ignored through `GIT_CONFIG_NOSYSTEM` and null-device `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` (Git 2.32 or newer). Content filters are detected, not overridden: the fail-closed preflight (`git config --list --show-origin`) stops the run with exit 3 before any diff or listing call. Limitation: D22 says execution-capable repository settings are overridden, but the enforced set is only `core.fsmonitor` plus the features the flags disable. Any other execution-capable repository setting is not neutralized, and no protection is claimed for it. The hostile-fixture tests demonstrate the enforced items only. | T04, T05 |
| NF-3 | Resolved by D19 (Option B): a changed source file maps to `docs/<module>.md` if it exists, otherwise `README.md` if it exists, otherwise no candidate. | T08 |
| NF-4 | Resolved by D19: discovery is in the working tree. `docs/<module>.md` is looked up directly under `docs/` by lowercased stem. | T08 |
| NF-5 | Resolved by D20 and D17: each edit is a reason line plus the changed symbol names from the diff, deterministic, with no free-text generation. Symbol names come from Python `ast` for `.py`; other languages use a generic text diff only. | T10 |
| NF-6 | Resolved by D15 and D8: the minimum pattern set is key, token, password, and secret assignments, PEM private-key headers, and AWS-style access key IDs. The T13 tests finalize the full list. A hunk is withheld as a whole (D8), so none of its context lines are written. | T02, T13 |
| NF-7 | Resolved by D13 and D14: generated files are paths matching `*.lock`, `*.min.*`, `dist/**`, `build/**`, and each skip is reported. Very large files count toward the diff cap, with no per-file threshold. | T07b |
| NF-8 | Resolved by D23: rename or copy without content change is 1 file and 0 lines; a deleted file is 1 file plus its deleted lines and is reported as not analyzed; binary, mode-only, and submodule entries stop the run with a typed "unsupported entry" error. No repository-size limit (D12). | T06 |
| NF-9 | Resolved by D24: the only options are the repository path and `--target`; no prompt, no stdin. Exit 0 only when a patch was written; distinct non-zero codes otherwise (architecture Section 6a; numeric values are default OQ-2). | T09, T15 |
| NF-10 | Resolved by D25 and D11: without `--target`, proceed only if all analyzed changes map to one doc; otherwise list candidates and write no patch. With `--target`, process only the changes mapped to it and report the rest as "not addressed". Invalid `--target`: non-zero, no patch, valid candidates listed. | T09 |
| NF-11 | Resolved by D26: `output/docsync.patch` is relative to the directory the tool is run from. The tool never edits `.gitignore`. | T13 |
| NF-12 | Resolved by D27: inline relative links and images in the added lines, resolved relative to the edited document's directory in the working tree; fragments stripped, anchors not checked; reference-style links, autolinks, and external URLs are limitations. | T12 |
| NF-13 | Resolved by D28: v1 reports a single "Not Found: consistency is not computed in v1" item. Non-blocking. | T11b |
| NF-14 | Resolved by D29: checked at the start of the run before any Git call, exclusive creation at write time, the message names the file, it is a D1 stage failure with its own exit code, and there is no `--force`. | T13, T15 |
| NF-15 | Resolved: the unchanged-tree test asserts no tracked file, documentation file, or Git history changed and the generated patch is the only new file on success. A failed or stopped run writes no patch and changes nothing. | T16 |

Defaults from requirements Section 8c (OQ-1 repository path default and root check, OQ-2 numeric exit codes, OQ-3 not-checked line reporting, OQ-6 `output/` creation) were approved with the requirements and are applied as written. Design risks R12 (patch applicability is not checked) and R14 (cross-platform determinism) have no decision and stay as limitations (architecture 8).

## 2. Task list (dependency order)

### T01 Project skeleton, data contracts, test fixtures
- Scope: package layout with one module per stage (`cli`, `input`, `gitadapter`, `sizegate`, `analysis`, `mapping`, `generation`, `validation`, `output`, `report`, `redact`). Frozen dataclasses for `ChangeRequest`, `ChangedFile`, `MappingResult`, `ProposedEdit` (with `reason` and `supporting_sources`, NFR-04), `NotFoundItem`, `ValidationReport`, and typed stage errors. A test helper that builds a temporary Git repository from a small fixture spec. No stage imports another stage's internals.
- Depends on: none.
- AC / edge cases: supports all ACs; NFR-03, NFR-04, NFR-06.
- Tests: contracts are immutable; helper creates a repo with known files; a module-boundary test asserts no cross-stage internal imports.
- Status: Ready.

### T02 Redactor
- Scope: `redact` module that masks secret-like strings in any printed or logged text, and reports whether a given text contains a secret-like value (used later to withhold hunks, D8).
- Depends on: T01.
- AC / edge cases: AC-08, NFR-01; E11.
- Tests: fixtures with fake key/token/password assignments, private-key block, token prefixes, and clean text. Masked output never contains the value. No real secrets in fixtures.
- Status: Ready. The minimum pattern set is key, token, password, and secret assignments, PEM private-key headers, and AWS-style access key IDs. The T13 tests finalize the full list.

### T03 Input Resolver
- Scope: validate that the repository path (optional positional argument, default the current directory, OQ-1) exists and is readable. Produce a `ChangeRequest`. No Git call on failure. Error message names the path, passed through the Redactor interface.
- Depends on: T01.
- AC / edge cases: AC-05; NFR-02; E1.
- Tests: nonexistent path, unreadable path (where the platform allows), a regular file instead of a directory, a valid directory.
- Status: Ready (the redaction call is wired when T02 is available; message text is tested without secrets).

### T04 Git Adapter core
- Scope: the only module that runs `git`. `subprocess.run([...], shell=False)` with a fixed timeout (value fixed here; a timeout counts as a failed command). The allow-list is exactly the six argument templates and the environment defined in T05, "Hardening controls". The Adapter holds them as data. Any argument vector that does not match a template exactly is rejected before it runs, and no other subcommand or option is reachable. The `config --list --show-origin` template is the one approved read-only configuration inspection, used only by the T05 preflight. Option-like paths are passed after `--`. The Adapter confirms the path is the repository root with the `rev-parse --show-toplevel` template, comparing resolved paths (Git prints forward slashes on Windows); any other path is an input error, exit 3 (OQ-1 default). Typed errors for git missing, not a repository, not a repository root, no `HEAD`, a timeout, and non-zero exit (failing step and exit code, no file contents).
- Depends on: T01.
- AC / edge cases: AC-05, AC-08; NFR-02; E2, E11 (paths treated as data).
- Tests: not a Git repo; a subdirectory of a repository (not a root) is exit 3; git executable not found (simulated by an injected executable name); path starting with `-`; forbidden subcommands (commit, push, merge, apply, checkout, reset) are rejected; each of the six templates is accepted; rejected variants: a diff without `--no-ext-diff`, a diff with an extra option, `config --global user.name x`, `config --unset`, `config --edit`, `config --file <path> --list`, `config --list` without `--show-origin`, and a `-c` option other than `core.fsmonitor=false`; a command that exceeds the timeout is a typed error; the root path Git prints on Windows (forward slashes) compares equal to the resolved input path, and a linked worktree root is accepted; no call uses a shell.
- Status: Ready.

### T05 Git diff retrieval and content-filter preflight
- Scope: obtain the raw diff text and per-file stats with `git diff HEAD` (D21) under the hardening controls below, and list untracked files by name only (never read) as "not analyzed". Run the content-filter preflight first, and fail closed.
- Hardening controls. This list is complete; anything not listed is not allowed (T04 enforces it). Here `G` means `git --no-pager -c core.fsmonitor=false`, and `D` means `--no-ext-diff --no-textconv --no-color --submodule=short --find-renames --find-copies --`.
  - The six argument templates:
    1. `G rev-parse --show-toplevel`
    2. `G config --list --show-origin` (the preflight; read-only; the only permitted `config` form)
    3. `G diff HEAD --raw -z D` (modes: detects mode-only and submodule entries)
    4. `G diff HEAD --numstat -z D` (line counts; binary entries show `-`)
    5. `G diff HEAD D` (diff text)
    6. `G ls-files --others --exclude-standard -z` (untracked names)
  - Record formats to parse: with `-z`, `--raw` gives `:<modes> <shas> <status>` then NUL then the path (a rename or copy has the old and new path as two NUL-separated fields); `--numstat` gives `<added>` tab `<deleted>` tab then NUL-separated paths (a rename or copy leaves the path field empty and follows with the old and new paths); a binary entry shows `-` for both counts.
  - Enforced protections: external diff drivers (`--no-ext-diff`), text conversion (`--no-textconv`), pagers (`--no-pager`), color (`--no-color`), and nested diffs inside submodules (`--submodule=short`) are disabled; `core.fsmonitor` is overridden (`-c core.fsmonitor=false`, the only `-c` option allowed); user and system configuration are ignored (below); content filters are handled by the preflight, which stops the run and does not override them.
  - Controlled environment. The environment is built from scratch, never copied. Pass-through is limited to `PATH`, and on Windows `SYSTEMROOT`, `TEMP`, and `TMP`. The following are set: `GIT_CONFIG_NOSYSTEM=1`; `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` set to the null device; `GIT_OPTIONAL_LOCKS=0`; `GIT_TERMINAL_PROMPT=0`; `LC_ALL=C`. Every other inherited variable is dropped, including `GIT_EXTERNAL_DIFF`, `GIT_PAGER`, `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`, and `GIT_EXEC_PATH`.
  - Stated limitations (no protection is claimed beyond the enforced list):
    - Any other execution-capable repository setting is not neutralized.
    - `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` need Git 2.32 or newer. On an older Git the user-level configuration may be read. The preflight still lists any content filter in it, so the run stops.
    - The pager protection is verified by asserting `--no-pager` in every argument vector. A pager fixture cannot fire while standard output is captured, so a behavioral pager test is not possible.
    - A mode-only change is reported by Git only if Git sees it; where `core.filemode` is false (common on Windows), an unstaged executable-bit change is not reported.
    - The checks below were run once (2026-10-22) against Git 2.56.0 for Windows. Other Git versions and platforms are not verified.
- Content-filter preflight, fail closed (architecture Section 7.3). It runs after the root check and before any diff or listing call:
  - Run template 2. Split each output line at its first tab into `<origin>` and the record. The origin has the form `<type>:<name>`; the key is the record text before the first `=` (or the whole record when there is no `=`). Values are never kept.
  - The preflight is verified only if all of these hold: (1) the command exits 0 within the timeout; (2) every non-empty line contains a tab, and every origin type is one of `file`, `command line`, `standard input`, `blob`; (3) at least one record has origin type `file` and key `core.repositoryformatversion`, which shows the repository's own configuration was inspected; (4) no key matches `filter.<name>.clean`, `filter.<name>.smudge`, or `filter.<name>.process` (section and variable names matched case-insensitively; the name may contain dots), whatever the origin: repository config, worktree config, or an included file.
  - If (4) fails, stop with a typed Git error: exit 3, no patch, no diff or listing call. The message names the key and its origin file and never prints the value.
  - If (1), (2), or (3) fails, or the configuration sources cannot be shown to have been inspected, stop the same way: exit 3, no patch, no diff or listing call. The message reads "content-filter protection could not be verified" and names the failed check (command failed or timed out; output not parseable; repository configuration not found in output; unknown origin type). It contains no configuration values and no raw command output.
  - The tool never reports filter protection as verified unless all four conditions hold.
  - Known consequence (flagged, Section 4): Git prints a multi-line configuration value across several lines, and the continuation line has no tab. Such a repository fails condition (2) and is refused. This is safe but restrictive. The `-z` form would avoid it but is not the approved `config` form.
- Depends on: T04.
- AC / edge cases: AC-01, AC-05, AC-08; E2, E3, E12.
- Tests, method: every hostile fixture needs a control run that omits the protections and proves the fixture can fire. A fixture whose control does not fire is not evidence and is recorded as such (this applies to the pager).
- Tests, hardening controls:
  - With an injected runner spy, every Git call's argument vector equals one of the six templates exactly, and `--no-pager` is present in every vector.
  - With hostile values set in the parent environment (`GIT_EXTERNAL_DIFF`, `GIT_PAGER`, `GIT_DIR`, `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`, `GIT_EXEC_PATH`), the environment passed to the child contains none of them and contains no variable outside the allowed set.
  - Behavioral fixtures, each with the marker file absent after the run and each with a live control: an external diff driver, a textconv filter (with a `.gitattributes` binding), a `core.fsmonitor` command, a hostile user-level configuration, and a submodule whose own configuration is hostile (with `diff.submodule=diff` set in the superproject).
- Tests, preflight, positive (each must stop with exit 3 and no patch, the message names the key and origin, the value is absent from all output, and the marker file the filter would write is absent; the control without the preflight must fire the marker): `filter.x.clean` in `.git/config` with a `.gitattributes` binding; `filter.x.smudge`; `filter.x.process`; a filter defined in a worktree config (`extensions.worktreeConfig`); a filter defined in a file pulled in through `include.path`; a filter name that contains dots; upper-case spelling of the section and variable.
- Tests, preflight, ordering: with a hostile filter, the spy shows template 2 ran and no diff or `ls-files` call was made.
- Tests, preflight, fail closed (each must stop with exit 3, no patch, and no diff or listing call; the message names the failed check; no value and no raw output appear; the text never says protection was verified): the command exits non-zero (a corrupted `.git/config`); the command times out; empty output; a line with no tab; a truncated line; an unknown origin type; output that lacks the repository's own configuration record (a runner stub returning only a `command line` record); a configuration with a multi-line value.
- Tests, preflight, negative (each must proceed normally): a `.gitattributes` binding to a filter with no defined command; a repository with no filters; a linked worktree (the repository record is found and the root check passes); lookalike keys (`filter.x.required` alone, `filterx.y.clean`, `diff.x.clean`). A filter defined only in a hostile user-level configuration must never execute (marker absent): on a Git that honors the null-device variables the run proceeds, and on an older Git the preflight sees the filter and stops with exit 3. The test records which case occurred.
- Tests, diff retrieval: staged and unstaged changes are both returned; a rename is one entry; a deleted file, a binary change, a staged mode-only change, and a submodule change (mode 160000) are each reported in the form T06 needs; an untracked file is listed as "not analyzed", an ignored file is not listed, and neither content is read; a repo with no commits is a Git error (exit 3); an empty change set returns "empty change set".
- Status: Ready.

### T06 Size Gate
- Scope: take per-file stat records (in memory) and apply the single cap. Stop if more than 50 files or more than 2,000 changed lines (added plus deleted, D6), either limit. Report file count and line count and ask for a split. Zero files returns "no changes". No warning tier, no partial processing. At or below the cap passes. Per D23: rename or copy without content change is 1 file and 0 lines; a deleted file is 1 file plus its deleted lines and is flagged not analyzed; a binary, mode-only, or submodule entry raises a typed "unsupported entry" error naming the path and kind, never zero. This check runs before the cap check.
- Depends on: T01.
- AC / edge cases: AC-01, AC-05; NFR-02; E3, E5.
- Tests: boundaries 50/51 files, 2,000/2,001 lines, each limit alone, both limits, empty set; pure rename (1 file, 0 lines), rename with edits, deleted file, binary, mode-only, and submodule entries each raise the typed error or count as specified; a diff that is both over the cap and contains an unsupported entry reports the unsupported entry (exit 6). Fixtures are in-memory records.
- Status: Ready.

### T07 Change Analyzer (parsing, source/binary/unsupported, Python evidence)
- Scope: parse the diff into `ChangedFile` records. Classify files as source, generated, or unsupported type. Binary, mode-only, and submodule entries are stopped earlier by T06. For `.py` sources extract the changed symbol names with `ast` (D20). Files not classified as source are excluded from generation and listed under Limitations. Other languages use a generic text diff only and produce no symbol names (D17), which is reported as such.
- Depends on: T01.
- AC / edge cases: AC-01, AC-03; NFR-04; E4 (binary, unsupported), E9, E11 (injection-like text is parsed as data only).
- Tests: diff fixtures with a Python function change, a `.txt` file, a file containing "ignore previous instructions" (no effect on behavior), stable sorted output.
- Status: Ready.

### T07b Analyzer: generated and very large file rules
- Scope: skip generated files, meaning paths matching `*.lock`, `*.min.*`, `dist/**`, and `build/**`, and report each skip (D13). Very large files are not analyzed separately: they count toward the diff cap and there is no per-file threshold (D14).
- Depends on: T07.
- AC / edge cases: AC-01; E4.
- Tests: one fixture path per generated pattern is skipped and reported; a non-matching path is analyzed; a very large file is counted by T06 and not skipped by this task.
- Status: Ready.

### T08 Doc Mapper
- Scope: discover candidate targets (`README.md` and `docs/**/*.md` only) and map each source change to at most one candidate with the path-based rule only (P5, D19 Option B): `docs/<module>.md` if it exists directly under `docs/` in the working tree, otherwise `README.md` if it exists, otherwise none. Module name: the file name with its last extension removed, lowercased; directories ignored; `__init__.py` uses the parent directory's name; non-Python files use the same rule (D17); the match on the doc is by lowercased stem and reports the doc's actual path. Changes to `README.md` or `docs/**`, test files (under `test` or `tests`, or named `test_*.py` or `*_test.py`), and D13 generated paths are not mapped and are reported as skipped. Emit a `MappingResult` per change and a sorted run-level list of distinct docs. Never select among several. Zero candidates reports "no suitable documentation target" and creates no files.
- Depends on: T01, T07.
- AC / edge cases: AC-01, AC-04; E6, E7.
- Tests: repo with no docs; only `README.md` (maps to it); only `docs/a.md` (`a.py` maps to it); `README.md` plus `docs/a.md` (`a.py` maps only to `docs/a.md`, `b.py` maps to `README.md`); nested `pkg/util/Parser.py` maps to `docs/parser.md`; `pkg/__init__.py` uses `pkg`; a non-Python file maps by the same rule; two files with one stem give one candidate; changes to `README.md` and test files are skipped and reported; Markdown outside `docs/` and `docs/sub/a.md` are not candidates; deterministic ordering.
- Status: Ready.

### T09 CLI argument handling and `--target`
- Scope: argument parsing (repository path, `--target <path>`; no other options, no stdin, no prompt; D24). Any other option, including `--force`, is a usage error (exit 2). Resolution order (architecture Section 2.3):
  1. If no change has a candidate, the result is "no suitable documentation target" (exit 7), with or without `--target`.
  2. Without `--target`: proceed only if every analyzed change maps to the same single doc. Otherwise list all candidate docs with the changed files mapped to each, report any change with no candidate, and exit with no patch (exit 8; D4, D25).
  3. With `--target`: validate it first (D30, D11): `README.md` or Markdown under `docs/`, relative to the repository root, one of the run's candidates; reject absolute paths, `..` segments, and paths that resolve outside the repository (including through symlinks). An invalid target exits 2, writes no patch, and lists the valid candidates. For a valid target, process only the changes mapped to it, report the others as "not addressed in this run" with the doc they map to, and treat a change with no candidate as unresolved (exit 8). A Not Found item for an in-scope change does not block the patch.
  4. The tool never selects a target. Map every outcome to its code in architecture Section 6a.
- Depends on: T01, T08.
- AC / edge cases: AC-01, AC-04, AC-07; E6, E7, E14.
- Tests:
  - Zero candidates (no `README.md`, no module doc): exit 7 and nothing written, both without `--target` and with a `--target` argument.
  - No `--target`, two distinct docs: both listed with their changed files, exit 8, nothing written.
  - No `--target`, one change mapped and one change with no candidate: exit 8, nothing written.
  - No `--target`, every change maps to the same single doc: the run proceeds with all changes in scope.
  - Valid `--target` selection: only the changes mapped to it are in scope; the others are reported as "not addressed in this run" with their doc; each change appears in exactly one of in scope, not addressed, or unresolved; none is dropped silently.
  - Valid `--target` plus a change with no candidate: exit 8, nothing written.
  - Invalid `--target` (a non-candidate, an absolute path, a `..` path, a non-Markdown file, a symlink pointing outside the repository): exit 2, nothing written, valid candidates listed.
  - Outcome-to-code function: each outcome class returns its own code from architecture Section 6a, and the codes are distinct. (Exit 0 for a written patch is asserted in T15 and T16.)
  - `--force` and an unknown option: exit 2. No code path reads stdin.
- Status: Ready.

### T10 Doc Generator
- Scope: from confirmed (change, target) pairs, build minimal `ProposedEdit`s. Each edit is a reason line plus the changed symbol names from the diff, with supporting source files (D20). There is no free-text generation. When evidence is insufficient or sources conflict, emit a `NotFoundItem` listing the files involved instead of text. Output stays in memory.
- Depends on: T07, T08, T09.
- AC / edge cases: AC-02, AC-03; NFR-04, NFR-05; E9.
- Tests: a changed Python function yields one minimal edit, a reason line plus the changed symbol name and its source file; a non-Python change has no symbol names (D17) and yields a Not Found item; conflicting fixtures yield a Not Found item with both files; no edit touches unrelated lines.
- Status: Ready (after T08 and T09). The output is deterministic (D20).

### T11 Validator: mandatory checks (syntax, non-empty)
- Scope: standard-library checks on proposed content for unbalanced code fences and malformed link syntax; non-empty output check. Each result carries file, line, and rule. A check that is unsupported or not performed is "not checked" and validation does not pass (D5). Any failed or not-checked mandatory check fails validation (D2).
- Depends on: T01.
- AC / edge cases: AC-06; C-3; E8.
- Tests: fixtures with an unclosed fence, malformed link, empty content, clean content, and a forced "not checked" that must not pass. How a line is reported for a not-checked result is Not Found (design review Gap 7); the implementer reports file and rule only and flags this to the human.
- Status: Ready.

### T11b Validator: consistency findings
- Scope: source-to-doc consistency as a single non-blocking "Not Found: consistency is not computed in v1" item (D28). No consistency computation in v1.
- Depends on: T10, T11.
- AC / edge cases: AC-02, AC-06 (non-blocking); IS-6.
- Tests: the item is reported and never fails validation.
- Status: Ready (after T10 and T11).

### T12 Validator: relative link check
- Scope: detect broken inline relative links and images (mandatory, D2) in the added lines of each proposed edit (D27). Resolve each path relative to the directory of the document being edited, against the working tree; strip `#fragment` and do not check anchors. Reference-style links, autolinks, anchor targets, links on lines the edit does not add, and external URLs are outside the check (OQ-5). They are listed as limitations, are never reported as passing, and external URLs are never fetched (D9). This is a declared scope, not a "not checked" mandatory check under D5, so these items do not fail validation by themselves.
- Depends on: T11.
- AC / edge cases: AC-06; C-3; E8.
- Tests: link to a missing file fails with file, line, rule; link to an existing file passes; a link with a `#fragment` passes when the file exists; a link relative to a nested doc resolves against that doc's directory; an `https://` link, an autolink, and a reference-style link are skipped and listed as limitations; a broken link on a line the edit does not add is not a failure and is listed as a limitation; none of these is reported as passing.
- Status: Ready (after T11).

### T13 Patch Writer
- Scope: render proposed edits as a unified diff with `difflib` and write the patch.
  - Destination: fixed at `output/docsync.patch`, resolved against the tool's working directory (not the repository). There is no output-path option, because none exists in the approved requirements and architecture. Never edit `.gitignore`. Create `output/` only if it is missing (OQ-6).
  - Destination guard (architecture Section 2.6): before writing, resolve the destination with the real paths of `output` and the file, following symlinks and comparing case-insensitively on Windows. Refuse it if it equals `<repository>/README.md` or lies inside `<repository>/docs/`. This can happen only when the tool is run from inside `docs/` or `output` links into it. Also refuse, writing nothing, if `output` exists and is not a directory. A refusal exits 11 (patch write failure, architecture Section 6a) and names the resolved destination.
  - What the guard does and does not cover: it protects `README.md` and `docs/`, as the architecture states. The patch is created with exclusive creation, so it never overwrites or changes an existing file anywhere, including a tracked source file. If the tool is run from a subdirectory of the repository, such as `src/`, the patch is created at `src/output/docsync.patch`, a new untracked file inside the repository. Refusing every destination inside the repository would be a new requirement and is flagged in Section 4, not added.
  - Existing patch (D3, D29): provide the pre-check `check_no_existing_patch`, which T15 calls at the start of the run before any Git call. It uses `os.path.lexists`, so a dangling symlink at `output/docsync.patch` counts as existing. The message names the file. The exit code is 11. There is no `--force`.
  - Publishing: `publish_patch(content)` creates `output/docsync.patch` with exclusive creation (the equivalent of open mode `x`, `O_CREAT|O_EXCL`, which does not follow a symlink at the destination), writes the content, flushes, fsyncs, and closes it. It returns a token made of the device and file index read from the open file, the size, and the SHA-256 of the content. If anything exists at the path at that moment, even if it appeared after the pre-check, nothing is written and the exit code is 11. A write error (for example a full disk) removes only the partial file it created, identified by device and file index, and exits 11. Any other exception inside it also removes only that partial file and propagates as an unexpected failure (exit 12).
  - Rollback: `rollback_patch(token)` reads the destination without following a symlink and deletes it only if it is a regular file whose device, file index, size, and SHA-256 all equal the token. Anything else is left untouched. It can fail (for example when the file is held open elsewhere); the caller reports that failure. T15 calls it if anything fails after the patch was created.
  - Sequence and preconditions: the writer is the last stage in the order generate, redact/withhold, validate, write (D31). As defense in depth it refuses to write unless it is given content that has passed the redact/withhold stage and the validation stage. It refuses if any hunk is withheld, any mandatory check failed or is "not checked", the output is empty (D7), or an in-scope change is unresolved. T15 stops earlier on each of these with its own exit code, so a writer precondition failure means the sequence was broken, which is an unexpected internal failure (exit 12).
  - Secrets: a hunk containing a secret-like value is withheld whole, including its context lines. Only the file and line are reported. Because P4 is decided, any withheld hunk means no patch (exit 10).
- Depends on: T02, T10, T11, T12.
- AC / edge cases: AC-07, AC-08; NFR-05; E8, E10, E11, E13.
- Tests:
  - Fixed destination: the publish function takes no destination argument (a signature test), and a run writes only `output/docsync.patch` under the working directory, with the working directory different from the repository.
  - Documents untouched: the SHA-256 of `README.md`, of every file under `docs/`, and of every tracked file is identical before and after a successful run and after a failed run, and no file is created under `docs/`.
  - Destination guard: with the working directory set to `<repository>/docs`, the write is refused (exit 11, nothing written, `README.md` and `docs/` unchanged); with `output` as a symlink to `<repository>/docs`, the write is refused the same way; with `output` as a regular file, the write is refused; with the working directory at the repository root, the patch is written; with the working directory at `<repository>/src`, the patch is created only at `src/output/docsync.patch` and no tracked file changes. Symlink cases are skipped, with the reason recorded, on a platform that cannot create symlinks.
  - A dangling symlink at `output/docsync.patch` pointing at a tracked file: the pre-check reports it as existing (exit 11), and the target is not created or modified. The same holds if the symlink appears between the pre-check and the write.
  - An existing file is refused by the pre-check: exit 11, the message names the file, the file is unchanged (hash compared).
  - A file created between the pre-check and the write is not overwritten: exit 11, the file is unchanged, and no rollback touches it.
  - Rollback removes a file it created; rollback does not delete a different file that replaced the patch after publish (different content, and the same content under a new file identity); a write error leaves no partial file and exits 11; a failed publish attempt on an existing file leaves that file unchanged; a directory at the destination is refused and left in place; rollback with the file held open raises an error the caller can report. (Prototype evidence and its limits are in Section 4.)
  - `output/` is created when missing; empty edits produce no file.
  - A fake secret in an added line, a removed line, and a context line each produce no patch (exit 10), report only file and line, and the value is absent from all output. One fixture per minimum pattern category.
  - Negative secret fixtures (the word "password" with no value; a line reading "ignore previous instructions") do not mask or withhold, and the patch is written.
  - Precondition tests: the writer refuses a withheld hunk, a failed mandatory check, a "not checked" result, empty output, and an unresolved in-scope change, writes nothing, and raises the unexpected internal failure (exit 12 through T15).
- Status: Ready (after T02, T10, T11, T12). This task's tests finalize the full secret pattern list (D15).

### T14 Reporter
- Scope: terminal report with files examined, files proposed, validation results (including "not checked"), candidate lists, Not Found items, consistency findings (when available), and limitations. Limitations always state that external URLs are not checked and that no dependency/security scanner is run (D9). Output passes through the Redactor. The Reporter has two functions so that the report can be fully built before the patch is written: `render_report(result) -> str` is pure (no file, console, or network access) and renders either the success report or a failure report for a stopped run. A failure report names the outcome class; for a withheld hunk it lists each withheld file and line and never a value. `fallback_report(outcome_class) -> str` is a fixed one-line message ("Run stopped: <outcome class>") that contains no data. `emit_report(text)` writes the text to standard output and flushes.
- Depends on: T01, T02.
- AC / edge cases: AC-06, AC-07, AC-08; IS-5, IS-7; E4, E5, E7, E10, E11.
- Tests: golden-text tests for a passing run, a size-cap stop, a multi-candidate stop, a failed validation (file, line, rule), and a run containing a fake secret (value absent from output); `render_report` performs no I/O (open, print, and the console are patched to raise); the failure report for a withheld hunk lists the file and line and does not contain the fake secret value; `fallback_report` contains only the outcome class; `emit_report` raises when standard output raises, and does not swallow the error.
- Status: Ready (after T02).

### T15 Orchestrator (pipeline sequencing, all-or-nothing)
- Scope: run the stages in this order, stopping at the first stop condition:
  1. The existing-patch pre-check (T13), before any Git call (D29).
  2. Input, Git (root check, content-filter preflight, diff), size gate, analysis, mapping and target resolution.
  3. Generate, then redact/withhold secret-containing hunks, then validate (including the consistency item from T11b) (D31).

  If steps 1 to 3 pass (the success path), continue:
  4. Render the success report in memory (T14 `render_report`). It is pure and states the planned patch path.
  5. Write the patch (T13 `publish_patch`): exclusive creation, write, flush, fsync. This is the only step that creates the patch, and it is the last step that can change the file system.
  6. Emit the report (T14 `emit_report`). Only after it succeeds does the run exit 0.

  If an expected outcome stops the run at steps 1 to 3 (the stop path), no patch exists and none is written. `render_report` is called once with the stop outcome and produces the failure report, which `emit_report` prints. For a withheld hunk the failure report lists each withheld file and line and never the value. The run exits with the designated code of the outcome.

  Report-failure rule (one rule for all cases): a report failure never changes an outcome that is already decided when no patch exists. It changes the outcome to exit 12 only on the success path, where a patch is at stake.
  - Stop path: if `render_report` raises, use `fallback_report(outcome class)` instead; if `emit_report` raises, ignore the error after a best-effort note on standard error. The designated code stands and no patch exists in either case.
  - Success path, step 4 fails: exit 12, and no patch exists because step 5 has not run.
  - Success path, step 5 or step 6 fails after the patch was created, including a failure to emit the report: the Orchestrator calls `rollback_patch` with the token from step 5. It deletes the patch only if the path still holds the file this run created, so a different or pre-existing file is never deleted. It then exits 12. If the rollback itself fails, it exits 12 and names the leftover patch path on standard error, stating that the all-or-nothing outcome was not achieved.
  - An unexpected exception at steps 1 to 3: exit 12, the failure report is attempted in the same best-effort way, and no patch exists.

  Residual non-guarantees, stated and not hidden: a process kill or power loss between step 5 and the exit can leave a patch (possibly partial) with no report; a rollback that cannot delete the file leaves it in place; a change to the file between the rollback's check and its delete is not detected; a closed standard error hides the message.

  Exit-code contract (architecture Section 6a, D24). Every expected, explicitly defined outcome is a typed result that keeps its designated code. No expected outcome is ever mapped to 12:

  | Expected outcome | Exit |
  |---|---|
  | Invalid `--target` or usage error | 2 |
  | Input or Git error, including the preflight (content filter defined, or protection could not be verified) | 3 |
  | No changes, or every changed file skipped | 4 |
  | Diff over the cap | 5 |
  | Unsupported entry | 6 |
  | No suitable documentation target | 7 |
  | Unresolved candidates or an unresolved in-scope change | 8 |
  | Validation failed, a mandatory check not performed, or empty output | 9 |
  | Withheld hunk (secret-like value) | 10 |
  | Existing patch, destination guard refusal, or write failure | 11 |

  Exit 12 is reserved for unexpected failures: an untyped exception in any stage, a broken writer precondition, and, on the success path only, a report rendering or emission failure (which also triggers the rollback). A report failure on a stop path never changes the designated code. The report names the failed stage and the completed units (D1). No stage logic lives here.
- Depends on: T03, T05, T06, T07, T08, T09, T10, T11, T11b, T12, T13, T14.
- AC / edge cases: AC-01 to AC-08 end to end; E1 to E14. E10 (a stage fails partway) is the unexpected-failure case and maps to 12; the expected failures among E1 to E9 and E11 to E14 keep their own codes.
- Tests:
  - Success-path call order: a spy asserts pre-check, then the Git calls, then redact/withhold, then validate, then render (success), then publish, then emit.
  - Stop-path call order, withheld hunk (exit 10): validate and publish are not called; `render_report` is called exactly once with the stop outcome and `emit_report` once; the output lists the withheld file and line and does not contain the fake secret value; no patch exists.
  - Stop-path call order, mandatory validation failure, "not checked" result, and empty output (exit 9): validate runs, publish is not called, `render_report` is called exactly once for the failure report, no patch exists.
  - Stop-path report failure: with a validation failure (exit 9), an exception injected into `render_report` still exits 9 and prints the fallback message; standard output raising during emit still exits 9. No patch exists in either case.
  - An existing patch: exit 11 before any Git call (the spy shows zero Git calls); the failure report is rendered and the existing file is unchanged (hash compared), even with report failures injected.
  - A content filter defined, and a preflight that cannot be verified (T05): exit 3, no patch, no diff call.
  - A table-driven test over the expected outcomes of the contract table: each fixture exits with its designated code, none exits 12, `render_report` is called once with the stop outcome, `publish_patch` is never called, and the codes are distinct.
  - Unexpected failure before publish: an untyped exception injected into each of input, Git, size gate, analysis, mapping, generation, redact, and validation exits 12, the report names the stage, and no patch exists.
  - Success-path report failure leaves no patch: an exception in `render_report` exits 12 and the patch path does not exist (publish was never called); an exception in `emit_report` (standard output raising, as for a closed pipe) after publish removes the new patch, exits 12, and the patch path does not exist afterwards.
  - Report failure does not touch other files: with a different file at `output/docsync.patch` that replaced the new patch after publish (simulated in a hook), an emit failure exits 12 and the replacement is not deleted (hash compared).
  - Pre-existing file: with the file appearing between the pre-check and the write, publish exits 11, the file is unchanged (hash compared), and no rollback deletes it.
  - Rollback failure: with the deletion made to fail (for example the file held open), the run exits 12 and names the leftover patch path, and the test asserts the all-or-nothing outcome is reported as not achieved.
  - A write error during publish (simulated full disk): the partial file is removed, exit 11. An untyped exception inside publish: the partial file is removed, exit 12.
  - Happy path: patch and report, exit 0. The report contains the consistency Not Found item (T11b), and it changes neither validation nor the exit code. A run with out-of-scope changes under `--target` still exits 0 and reports them. A Not Found item for an in-scope change does not block; if every in-scope change yields only Not Found items, the output is empty and the exit is 9.
- Status: Ready (after its dependencies).

### T16 End-to-end and traceability tests
- Scope: fixture-driven end-to-end tests mapped to AC-01 to AC-08.
  - Read-only test (NF-15): no tracked file, documentation file, or Git history changed, and on a successful run the generated patch is the only new file. On every failed or stopped run (stage failure, withheld hunk, failed or not-checked validation, empty output, unresolved candidates, invalid target, existing patch, unsupported entry, diff over the cap, content filter, Git or input error, report-emission failure) no patch remains and nothing else changes.
  - Determinism test (NFR-06). The tool never overwrites `output/docsync.patch`, so the test does not run twice in one working directory. Instead it builds two equivalent fresh fixtures from the same fixture spec in two separate temporary working directories, runs the tool once in each, and compares the two patch files byte for byte and the two report texts. The patch and report must contain no absolute temporary path, commit hash, or timestamp. If the report names the temporary directory, the test replaces that prefix with a placeholder and records the substitution. Variants: files created in a different order; a non-ASCII path; an LF document and a CRLF document.
  - Round-trip test (architecture 8.2, test code only): apply the generated hunks in memory to the original document and reproduce the proposed content, with context lines equal to the original lines.
  - Exit-code contract test: each expected outcome class exits with its own code from architecture Section 6a, and only an unexpected internal failure exits 12.
  - Instructions-as-data test: repository text with injected instructions changes no behavior.
  - Limitations kept (no runtime guarantee, not removed by these tests): R12, patch applicability to later content is not checked; R14, identical output across Git versions, operating systems, and locale or encoding settings is not guaranteed.
- Depends on: T15.
- AC / edge cases: AC-01 to AC-08; E1 to E14.
- Tests: see Section 3 matrix.
- Status: Ready (after T15).

## 3. AC coverage matrix

| AC | Covered by | Fully testable now |
|---|---|---|
| AC-01 | T05, T06, T07, T08, T09, T15, T16 | Yes, after dependencies |
| AC-02 | T10, T11b, T15, T16 | Yes, after dependencies |
| AC-03 | T07, T10, T15, T16 | Yes, after dependencies |
| AC-04 | T08, T15, T16 | Yes, after dependencies |
| AC-05 | T03, T04, T05, T06, T15, T16 | Yes, after dependencies |
| AC-06 | T11, T12, T14, T15, T16 | Yes, after dependencies |
| AC-07 | T09, T13, T14, T15, T16 | Yes, after dependencies |
| AC-08 | T02, T04, T05, T07, T13, T14, T16 | Yes, after dependencies |

## 4. Gap check

- Every AC-01 to AC-08 is covered by at least one task. No AC is uncovered.
- No task is Blocked on a missing decision. All tasks wait only on plan approval and on their dependencies.
- G3 and constraints C-1 to C-7 now have rows in the architecture coverage table (Section 9, P12), with AC-to-test traceability. Here C-1/C-2/C-7 are met by Section 0 rules and T01; C-3 by T11/T12; C-4 by T06; C-5 by T09; C-6 by T13/T14.
- Edge case E4 is covered by T06, T07 and T07b (D13, D14, D23). E12 by T05, E13 by T13 and T15, E14 by T09.
- R12 and R14 remain unresolved limitations (architecture 8). T16 tests what is testable and does not claim a guarantee.
- T11b produces the consistency Not Found item, which the Orchestrator (T15) and the happy-path report consume, so T15 depends on T11b. T14 renders whatever is in the validation report and needs no dependency on T11b.
- Exit 11 for a destination-guard refusal is consistent with architecture Section 6a ("Existing patch or patch write failure") and Section 2.6 (the writer refuses the path). Section 2.6 states no code of its own, so this is the closest approved class. No correction is needed unless the human wants a separate class.
- All-or-nothing (P4, D1): the patch is never created before a failure that is not an I/O failure can occur, because validation and report rendering both complete before it is written. After it is created, a failure triggers a rollback that deletes only the file this run created (T13, T15). Not guaranteed: a process kill or power loss after the patch is created; a rollback that cannot delete the file (a held-open file was observed to raise `PermissionError` in the prototype); a change to the file between the rollback's check and its delete; and file systems where file identity can be reused. The plan states these residuals and tests the rest.
- Prototype check of the publish and rollback rules (2026-10-22, Windows, throwaway directories outside the project, 24 checks, 0 failed) established: exclusive creation does not overwrite or change an existing file; file identity read from the open file equals the identity read from the path afterwards; rollback removes the file it created and does not remove a different file that replaced it (different content, and also identical content, which got a new identity here); a simulated write error leaves no partial file; a directory at the destination is refused; rollback fails with an error, not silently, when the file is held open; and the report-failure rule gives the exit codes and file states in T15. It did not establish: behavior with a symlink at the destination (the Windows account lacked the privilege to create one, so those checks were skipped), identity reuse beyond 0 of 300 observed delete-and-recreate cycles on this file system, behavior on other platforms or file systems, durability after fsync, or any race between check and delete. The prototype is not application code and is not kept in the project.
- Plan-level choices that the approved documents do not state, flagged for the human: (1) the report is rendered in memory before the patch is created, the patch is rolled back (deleted, only if it is still the file this run created) if emitting the report fails, and a report failure on a stop path never changes the designated exit code; this keeps all-or-nothing for report failures and is not stated in the architecture (if rejected, a failure to print the report after the patch exists would have to be accepted as a limitation); (2) the destination guard covers `README.md` and `docs/` as the architecture states, so a run from a subdirectory such as `src/` creates the patch there, and refusing every destination inside the repository would be a new requirement; (3) the preflight completeness test uses the `core.repositoryformatversion` record; (4) the exact Git templates and environment allow-list in T05; (5) the Git timeout value is fixed in T04; (6) a repository whose configuration has a multi-line value is refused by the fail-closed preflight, because the approved `config` form has no `-z`. None changes an approved decision.
- Consistency findings (IS-6, AC-02 reporting) are a single Not Found item in v1 (D28, T11b).

## 5. Ready tasks and suggested start order

Dependency order: T01 first; then T02, T03, T04, T06, T07, T11 in any order; T05 after T04; T07b and T08 after T07; T09 after T08; T10 after T07, T08, T09; T11b after T10 and T11; T12 after T11; T13 after T02, T10, T11, T12; T14 after T02; T15 after T03, T05 to T14 (including T11b); T16 after T15. This plan is approved, so Step 5 may proceed. Run one task per implementer run.

## 5a. Human decisions

Recorded history. These are human decisions, not planner output.

- **2026-10-21, at the earlier Step 4 approval of the previous plan text:**
  - Git hardening (NF-2, P1 in that record): disable external diff, textconv and the pager, and run Git with a clean environment (now D22).
  - Secret pattern list (NF-6): deferred to an implementation task with tests.
  - Mapping (P5): path-based only.
  - T06: an entry with unknown line counts raises a typed error, not zero (now D23).
  - T11: a check that is not performed is reported as "not checked" (file and rule only), and validation does not pass.
- **2026-10-22:** the human decided D11-D31 (requirements 8b), including D19 Option B, D20 deterministic output, and the resolution of NF-1, NF-2, NF-8 to NF-15 and P4, P5, P9, P12. This plan was revised to apply them. The earlier approval does not cover this revision.
- **2026-10-22, after the approvals of requirements, architecture, and design review:** this plan was synchronized with the approved architecture (Git security preflight in T04 and T05, the allow-list exception for `git config --list --show-origin`, the sequence in T13 and T15, the exit-code tests in T09 and T15, and the determinism test in T16). The Git templates were then run against real temporary repositories (Git 2.56.0 for Windows) and the plan was corrected from the results; report rendering was moved before the patch write, with rollback. The human then approved this plan on 2026-10-22 (the flagged plan-level choices in Section 4 were accepted with the approval).

## 6. Sign-off

Status: Approved (2026-10-22). The human approved this revision as written, by instruction of 2026-10-22, including the flagged plan-level choices in Section 4. Requirements, architecture, and design review are approved. No Git commit records this approval yet.
