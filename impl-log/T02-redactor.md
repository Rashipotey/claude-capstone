# T02 Redactor

- Plan: `docs/impl-plan.md` Section 2, T02. Depends on: T01. AC-08, NFR-01; E11.
- Current status: see `docs/pipeline-state.md`. At backfill: done, approved 2026-10-22.
- Evidence labels: see `README.md`.

## Attempt 1 (2026-10-22) [PS][BACKFILL]

### Changes
- `docsync/redact.py` (masks secret-like strings; reports whether text contains one, for hunk withholding, D8).
- `tests/test_redact.py` (17 tests).
- Minimal edit to `tests/test_module_boundaries.py`: an `implemented` skip set, because T02 legitimately makes the redact stub's `__all__` non-empty. [ORCH-READ: the set exists at line 111 and now lists seven modules.]

### Test results
- Full suite: 66 tests, OK [IMPL]. The orchestrator had no shell and did not re-run it.

### Skipped tests
- None reported at this point.

### Security findings [SG] (static)
- Verdict: Pass.
- Low: unittest failure messages could echo a fake value; untracked `__pycache__` directories, `.gitignore` Not Found.
- `docs/security-audit.md` not written (guardian has no write tool).

### Limitations
- The full secret pattern list is deliberately finalized in T13 (plan NF-6, D15).

### Verification status
- Unverified by the orchestrator (implementer report plus static guardian review).

### Human approvals
- [HUMAN] Approved T02 on 2026-10-22, including the `tests/test_module_boundaries.py` skip-set edit.
- T02 uncommitted at the time. T03 was then started on the human's instruction.

## Corrections
- None recorded as of the backfill (2026-10-23).
- 2026-10-25 `[HUMAN]` authorization of an ADDITIVE extension of approved T02, made inside the T13 correction (see `impl-log/T13-patch-writer.md`, Attempt 2): `docsync/redact.py` and `tests/test_redact.py` may gain detection and tests for Bearer tokens, JWTs, URL credentials and split PEM blocks (T13 finding M4, plan D15 / NF-6). Existing patterns and tests must not be weakened or removed. T02's original approval (2026-10-22) is not rewritten. Results of that extension will be logged in the T13 log and referenced here.
- 2026-10-25 `[IMPL][SG]` result of that extension (details in `impl-log/T13-patch-writer.md`, Attempt 2): `docsync/redact.py` gained `_BEARER`, `_JWT`, `_URL_CRED`, `_EXTRA_ASSIGNMENT` (public API `MASK`, `redact`, `contains_secret`, `secret_line_numbers` unchanged); `tests/test_redact.py` gained `ExtendedPatternTests` and `HostileInputTests`. Additive-only is the implementer's claim; the guardian's reading is consistent with it but neither could diff, and the orchestrator did not check. The guardian found a MEDIUM about the PRE-EXISTING T02 `_ASSIGNMENT` pattern (quadratic on long lines separated by `_`, `.` or `-`), left unfixed pending the human's decision; this entry does not change T02's approval.
- 2026-10-25 `[HUMAN]` second authorization, inside the T13 correction (Attempt 3 in `impl-log/T13-patch-writer.md`): bound the repetition in the approved T02 `_ASSIGNMENT` regex in `docsync/redact.py` to remove the quadratic behavior on long lines, preserving existing detection as much as possible, with adversarial timing and regression tests; existing tests must not be weakened; any unavoidable detection trade-off must be documented. This is a human-authorized change to approved T02 behavior (it may narrow what the pattern detects); T02's original approval (2026-10-22) is not rewritten. Results will be recorded in the T13 log.
- 2026-10-25 `[IMPL][SG]` result of the second authorization (details in `impl-log/T13-patch-writer.md`, Attempt 3): the approved-T02 `_ASSIGNMENT` regex was changed (the prefix `(?:[\w.-]*[_.-])?` removed; the suffix `\w*` bounded to `\w{0,64}`), with new tests `AssignmentBoundTests` and `AssignmentHostileInputTests` in `tests/test_redact.py` and a deterministic old-versus-new differential test. Trade-off: a secret word, one separator, MORE than 64 word characters, then `=`/`:`/`:=` is no longer detected (a false negative, rated Low by the guardian, trivially evadable by whoever controls the text). The implementer reports no existing test was edited (unverified, no diff). Static audit: Pass. Timings are implementer-reported and unverified. T02's original approval is not rewritten.
- 2026-10-25 `[HUMAN]` third authorization, inside the T13 correction (Attempt 4 in `impl-log/T13-patch-writer.md`): fix the `secret_line_numbers` per-match newline counting (performance, results unchanged), extend `_URL_CRED` to cover an empty-user URL credential such as `scheme://:password@host`, and document the remaining redaction gaps in the `redact.py` docstring. Again a human-authorized change to approved T02 behavior; T02's original approval is not rewritten. Results will be recorded in the T13 log.
- 2026-10-25 `[IMPL][SG]` result of the third authorization (details in `impl-log/T13-patch-writer.md`, Attempt 4): `secret_line_numbers` now uses lazily computed newline offsets and `bisect.bisect_left` (results identical to the old per-match `count`; verified by a differential test against a verbatim copy on 4000 random inputs, seed 20261026); `_URL_CRED` accepts an empty user (so `redis://:secret@host` is detected; `scheme://:8080@host` is now a documented false positive); the docstring lists the remaining false negatives; new tests added (`DocumentedGapTests` pins the known gaps). The implementer reports no existing test was edited (unverified, no diff). Static audit: Pass. Timings are implementer-reported and unverified. T02's original approval is not rewritten.
- 2026-10-25 `[HUMAN]` fourth authorization, inside the T13 correction (Attempt 5 in `impl-log/T13-patch-writer.md`): fix Markdown-formatted secret detection (a backticked name, a bold name, a table cell) and short JWT segments in `docsync/redact.py`, with regression tests in `tests/test_redact.py`, and rename the pinned-gap test(s) so a documented limitation is clearly identified. Existing tests must not be weakened. T02's original approval is not rewritten. Results will be recorded in the T13 log.
- 2026-10-25 `[IMPL][SG]` result of the fourth authorization (details in `impl-log/T13-patch-writer.md`, Attempt 5): `_JWT` accepts short payload and signature segments, an empty signature and `=` padding; `_MD_ASSIGNMENT` and `_MD_TABLE` were added; the unquoted-value alternative of `_ASSIGNMENT` and `_EXTRA_ASSIGNMENT` gained the lookahead `(?!\*+(?:\s|\Z))` (a narrowing of approved T02 behavior not named in the instruction: `password: ***`, `key: **`, `token: *` stopped being flagged); two pinned-gap tests were replaced by positive tests. Static audit: Pass (ten Lows). Additive-only is the implementer's claim; the guardian could not diff. T02's original approval is not rewritten.
- 2026-10-25 `[HUMAN]` fifth authorization, inside the T13 correction (Attempt 6 in `impl-log/T13-patch-writer.md`): close the unclosed-backtick gap, restore ordinary detection of `password: ***`, `key: **` and `token: *` (undoing the Attempt 5 narrowing while still fully masking bold-formatted names), and detect short or default-like table values (`admin`, `12345`, `default`, `none`). T02's original approval is not rewritten. Results will be recorded in the T13 log.
- 2026-10-25 `[IMPL][SG]` result of the fifth authorization (details in `impl-log/T13-patch-writer.md`, Attempt 6): `_ASSIGNMENT` is textually the pre-Attempt-5 pattern again and `_EXTRA_ASSIGNMENT` lost the narrowing lookahead; a Python post-filter `_is_bold_marker` handles the bold-name closing `**`; `_MD_BACKTICK_OPEN` handles unclosed and long backtick values; `_MD_TABLE` now detects short and default-like values (`admin`, `12345`, `default`, `none`, ...). Test changes and removals are listed in the T13 log. Static audit: Pass (eight Lows; one new regression class: `**Password:** "abc` and `**Password:** ,abc` are no longer flagged). Test counts and timings are implementer-reported and unverified. T02's original approval is not rewritten.
- 2026-10-25 `[HUMAN]` sixth authorization, inside the T13 correction (Attempt 7 in `impl-log/T13-patch-writer.md`; scope `docsync/redact.py` and `tests/test_redact.py` only): fix the Attempt 6 regression where a secret after a bold-formatted name escapes detection when the value starts with an unclosed quote or a comma. `[IMPL][SG]` result: added `_MD_ODD_VALUE`, `_MD_STAR_VALUE` and `_NO_VALUE_AFTER`, a stricter `_is_bold_marker` rule, and three unrequested `_MD_ASSIGNMENT` changes; `_ASSIGNMENT` and `_EXTRA_ASSIGNMENT` untouched; one existing KNOWN_GAP test converted and one differential-test skip rule widened (both listed in the T13 log). Static audit: Pass, with two PRE-EXISTING Mediums reported (a plain unclosed or multi-line quoted value `password: "abc`, and camelCase names such as `dbPassword: x` / `accessToken=x`), neither introduced by Attempt 7. Test counts and timings are implementer-reported and unverified. T02's original approval is not rewritten.
