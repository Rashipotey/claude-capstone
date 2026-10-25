"""T11 tests: mandatory validation checks (syntax, non-empty). No files, no network."""

import time
import unittest

from docsync import validation as v
from docsync.contracts import (
    CHECK_MARKDOWN_SYNTAX,
    CHECK_NON_EMPTY_OUTPUT,
    CHECK_RELATIVE_LINKS,
    CheckResult,
    CheckStatus,
    ValidationReport,
)

CLEAN = "# Title\n\nSee [guide](docs/guide.md) and `code`.\n\n```python\nx = 1\n```\n"


def by_status(results, status):
    return [r for r in results if r.status is status]


class MarkdownSyntaxTests(unittest.TestCase):
    def test_clean_content_passes(self):
        results = v.check_markdown_syntax({"README.md": CLEAN})
        self.assertEqual(len(results), 1)
        self.assertIs(results[0].status, CheckStatus.PASSED)
        self.assertEqual(results[0].file, "README.md")

    def test_unclosed_fence_fails_with_file_line_rule(self):
        text = "intro\n\n```python\ncode\n"
        (r,) = v.check_markdown_syntax({"docs/a.md": text})
        self.assertIs(r.status, CheckStatus.FAILED)
        self.assertEqual((r.file, r.line, r.rule), ("docs/a.md", 3, v.RULE_UNCLOSED_FENCE))
        self.assertEqual(r.check, CHECK_MARKDOWN_SYNTAX)
        self.assertTrue(r.mandatory)

    def test_tilde_and_longer_fences(self):
        self.assertEqual(v.scan_markdown("~~~\nx\n~~~\n"), [])
        self.assertEqual(v.scan_markdown("````\n```\nx\n````\n"), [])  # inner ``` is content
        self.assertEqual(v.scan_markdown("````\nx\n```\n"), [(1, v.RULE_UNCLOSED_FENCE)])
        self.assertEqual(v.scan_markdown("~~~\nx\n```\n"), [(1, v.RULE_UNCLOSED_FENCE)])

    def test_malformed_link_fails_with_line(self):
        text = "ok\nSee [guide](docs/guide.md and more\n"
        (r,) = v.check_markdown_syntax([("README.md", text)])
        self.assertIs(r.status, CheckStatus.FAILED)
        self.assertEqual((r.file, r.line, r.rule), ("README.md", 2, v.RULE_UNCLOSED_LINK))

    def test_empty_destination_fails(self):
        self.assertEqual(v.scan_markdown("[x]()\n"), [(1, v.RULE_EMPTY_LINK)])

    def test_links_with_parentheses_and_escapes_are_fine(self):
        self.assertEqual(v.scan_markdown("[a](p_(1).md) [b](x\\)y)\n"), [])
        self.assertEqual(v.scan_markdown("![img](a/b.png) [c](d.md#frag)\n"), [])

    def test_code_is_not_scanned_for_links(self):
        self.assertEqual(v.scan_markdown("`[a](b` text\n"), [])
        self.assertEqual(v.scan_markdown("```\n[a](b\n```\n"), [])

    def test_multiple_findings_are_sorted_and_per_file(self):
        results = v.check_markdown_syntax(
            {"b.md": "[a](\n```\n", "a.md": CLEAN}
        )
        failed = by_status(results, CheckStatus.FAILED)
        self.assertEqual([(r.file, r.line, r.rule) for r in failed],
                         [("b.md", 1, v.RULE_UNCLOSED_LINK), ("b.md", 2, v.RULE_UNCLOSED_FENCE)])
        self.assertEqual([r.file for r in by_status(results, CheckStatus.PASSED)], ["a.md"])

    def test_scan_is_deterministic(self):
        text = "[a](b\n```\n"
        self.assertEqual(v.scan_markdown(text), v.scan_markdown(text))


class HostileLineTests(unittest.TestCase):
    """Regression: long hostile lines must scan in linear time (no regex backtracking).

    The bound is 2 seconds: the linear scan takes well under 0.5 s for 200,000
    characters, while the old backtracking pattern took far longer (quadratic or worse),
    so 2 s separates the two with margin for a slow machine."""

    BOUND = 2.0

    def timed(self, text):
        start = time.perf_counter()
        result = v.scan_markdown(text)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, self.BOUND)
        return result

    def test_long_unmatched_backticks(self):
        self.assertEqual(self.timed("a " + "`" * 200000 + "x"), [])
        self.assertEqual(self.timed("x " + "`" * 199999 + "\n"), [])
        self.assertEqual(self.timed("[a](" + "`" * 200000), [(1, v.RULE_UNCLOSED_LINK)])

    def test_long_interleaved_backticks(self):
        self.assertEqual(self.timed("`a" * 100000), [])  # pairs close; no links
        self.assertEqual(self.timed("`" * 1 + "a``" * 66000), [])
        self.assertEqual(self.timed("".join("`" * k + "x" for k in range(1, 600))), [])
        self.assertEqual(self.timed("`a" * 100000 + "[a](b"), [(1, v.RULE_UNCLOSED_LINK)])

    def test_long_other_hostile_lines(self):
        for piece in ("[", "](", "(", ")", " ", "~", "\\", "[a]("):
            self.timed(piece * 100000)
        self.assertEqual(self.timed("~" * 200000), [(1, v.RULE_UNCLOSED_FENCE)])

    def test_code_span_semantics_unchanged(self):
        self.assertEqual(v.scan_markdown("`[a](b` x\n"), [])
        self.assertEqual(v.scan_markdown("`` `[a](b` `` x\n"), [])
        self.assertEqual(v.scan_markdown("`a` [b](\n"), [(1, v.RULE_UNCLOSED_LINK)])
        self.assertEqual(v.scan_markdown("`[a](b\n"), [(1, v.RULE_UNCLOSED_LINK)])  # unmatched: literal
        self.assertEqual(v._blank_code_spans("a `b` c"), "a     c")


class LfNumberingTests(unittest.TestCase):
    """T11 numbers lines by LF only, the same rule as the T12 link check (MEDIUM-3)."""

    def test_separators_do_not_shift_line_numbers(self):
        for sep in ("\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            text = "a" + sep + "b\n```\n[x](oops\n```\n[y](oops\n"
            self.assertEqual(v.scan_markdown(text), [(5, v.RULE_UNCLOSED_LINK)], repr(sep))
            (r,) = v.check_markdown_syntax({"a.md": "a" + sep + "b\n```\nx\n"})
            self.assertEqual((r.line, r.rule), (2, v.RULE_UNCLOSED_FENCE), repr(sep))

    def test_crlf_and_trailing_newline(self):
        self.assertEqual(v.scan_markdown("a\r\n[x](oops\r\n"), [(2, v.RULE_UNCLOSED_LINK)])
        self.assertEqual(v.scan_markdown("[x](oops"), [(1, v.RULE_UNCLOSED_LINK)])
        self.assertEqual(v.scan_markdown(""), [])


class NonEmptyTests(unittest.TestCase):
    def test_empty_content_fails(self):
        r = v.check_non_empty_output({"README.md": ""})
        self.assertIs(r.status, CheckStatus.FAILED)
        self.assertEqual(r.rule, v.RULE_EMPTY_OUTPUT)
        self.assertEqual(r.check, CHECK_NON_EMPTY_OUTPUT)

    def test_no_documents_and_blank_documents_fail(self):
        self.assertIs(v.check_non_empty_output({}).status, CheckStatus.FAILED)
        self.assertIs(v.check_non_empty_output({"a.md": " \n\t"}).status, CheckStatus.FAILED)

    def test_non_empty_passes(self):
        self.assertIs(v.check_non_empty_output({"a.md": CLEAN}).status, CheckStatus.PASSED)

    def test_judged_as_a_whole(self):
        self.assertIs(v.check_non_empty_output({"a.md": "", "b.md": "text"}).status, CheckStatus.PASSED)


class NotCheckedTests(unittest.TestCase):
    def test_non_text_content_is_not_checked_file_and_rule_only(self):
        (r,) = v.check_markdown_syntax({"a.md": None})
        self.assertIs(r.status, CheckStatus.NOT_CHECKED)
        self.assertEqual((r.file, r.line, r.rule), ("a.md", None, v.RULE_NOT_TEXT))

    def test_non_empty_check_not_checked_for_non_text(self):
        r = v.check_non_empty_output({"a.md": b"bytes"})
        self.assertIs(r.status, CheckStatus.NOT_CHECKED)
        self.assertIsNone(r.line)
        self.assertIsNotNone(r.rule)

    def test_forced_not_checked_never_passes(self):
        forced = v.not_checked(CHECK_MARKDOWN_SYNTAX, "a.md")
        self.assertEqual((forced.file, forced.line, forced.rule), ("a.md", None, v.RULE_NOT_CHECKED))
        every_other_passes = [
            CheckResult(CHECK_RELATIVE_LINKS, CheckStatus.PASSED),
            CheckResult(CHECK_NON_EMPTY_OUTPUT, CheckStatus.PASSED),
        ]
        self.assertFalse(ValidationReport(results=[forced] + every_other_passes).passed)
        # the same report with a passing syntax check does pass (control)
        ok = CheckResult(CHECK_MARKDOWN_SYNTAX, CheckStatus.PASSED)
        self.assertTrue(ValidationReport(results=[ok] + every_other_passes).passed)

    def test_not_checked_result_requires_a_rule(self):
        with self.assertRaises(ValueError):
            CheckResult(CHECK_MARKDOWN_SYNTAX, CheckStatus.NOT_CHECKED, file="a.md")


class ValidateContentTests(unittest.TestCase):
    def test_clean_content_has_passed_results_but_report_not_passed_until_t12(self):
        report = v.validate_content({"README.md": CLEAN})
        # T12 intentionally changes this: without root and added lines the link check is
        # NOT_CHECKED (never a pass, D5), so the report still does not pass here.
        syntax = [r for r in report.results if r.check != CHECK_RELATIVE_LINKS]
        self.assertTrue(all(r.status is CheckStatus.PASSED for r in syntax))
        self.assertEqual({r.check for r in syntax}, {CHECK_MARKDOWN_SYNTAX, CHECK_NON_EMPTY_OUTPUT})
        self.assertFalse(report.passed)  # relative_links not performed (D5)

    def test_clean_content_passes_once_relative_links_pass(self):
        report = v.validate_content({"README.md": CLEAN})
        base = tuple(r for r in report.results if r.check != CHECK_RELATIVE_LINKS)  # T12: drop the NOT_CHECKED link result
        full = ValidationReport(results=base + (CheckResult(CHECK_RELATIVE_LINKS, CheckStatus.PASSED),))
        self.assertTrue(full.passed)

    def test_failures_fail_validation(self):
        report = v.validate_content({"a.md": "```\nopen\n"})
        extra = CheckResult(CHECK_RELATIVE_LINKS, CheckStatus.PASSED)
        self.assertFalse(ValidationReport(results=report.results + (extra,)).passed)

    def test_empty_content_reports_empty_output(self):
        report = v.validate_content({"a.md": ""})
        self.assertIn(v.RULE_EMPTY_OUTPUT, [r.rule for r in report.results])

    def test_no_documents(self):
        report = v.validate_content([])
        self.assertEqual([r.status for r in report.results], [CheckStatus.FAILED])
        self.assertFalse(report.passed)

    def test_bad_input_shapes_are_rejected(self):
        for bad in ("text", b"text", [("only-one",)], [("", "x")], [(1, "x")]):
            with self.assertRaises(TypeError, msg=repr(bad)):
                v.validate_content(bad)


class ConsistencyItemTests(unittest.TestCase):
    """T11b: one non-blocking 'Not Found: consistency is not computed in v1' item (D28)."""

    WORDING = "Not Found: consistency is not computed in v1"

    @staticmethod
    def passing_report():
        return ValidationReport(results=tuple(
            CheckResult(name, CheckStatus.PASSED) for name in
            (CHECK_MARKDOWN_SYNTAX, CHECK_RELATIVE_LINKS, CHECK_NON_EMPTY_OUTPUT)))

    @staticmethod
    def failing_report():
        return ValidationReport(results=(
            CheckResult(CHECK_MARKDOWN_SYNTAX, CheckStatus.FAILED, file="a.md", line=3, rule="unclosed-code-fence"),
            CheckResult(CHECK_RELATIVE_LINKS, CheckStatus.PASSED),
            CheckResult(CHECK_NON_EMPTY_OUTPUT, CheckStatus.PASSED)))

    def test_item_wording(self):
        item = v.consistency_not_found()
        self.assertEqual(item.detail, self.WORDING)
        self.assertEqual(item.files, ())

    def test_reported_exactly_once(self):
        report = v.with_consistency_item(self.passing_report())
        self.assertEqual(len(report.not_found), 1)
        self.assertEqual(report.not_found[0].detail, self.WORDING)

    def test_idempotent(self):
        once = v.with_consistency_item(self.passing_report())
        twice = v.with_consistency_item(once)
        self.assertEqual(twice, once)
        self.assertEqual(len(twice.not_found), 1)

    def test_does_not_change_passing_report(self):
        base = self.passing_report()
        self.assertTrue(base.passed)
        report = v.with_consistency_item(base)
        self.assertTrue(report.passed)
        self.assertEqual(report.results, base.results)

    def test_does_not_change_failing_report(self):
        base = self.failing_report()
        self.assertFalse(base.passed)
        report = v.with_consistency_item(base)
        self.assertFalse(report.passed)
        self.assertEqual(report.results, base.results)
        self.assertEqual(by_status(report.results, CheckStatus.FAILED), by_status(base.results, CheckStatus.FAILED))

    def test_keeps_other_not_found_items(self):
        from docsync.contracts import NotFoundItem
        other = NotFoundItem("x", "y")
        report = v.with_consistency_item(ValidationReport(not_found=(other,)))
        self.assertEqual(report.not_found[0], other)
        self.assertEqual(len(report.not_found), 2)

    def test_validate_content_carries_item_and_still_not_passed(self):
        for content in ({"a.md": CLEAN}, {}, {"a.md": "```\nx\n"}):
            report = v.validate_content(content)
            self.assertEqual([n.detail for n in report.not_found], [self.WORDING])
            self.assertFalse(report.passed)

    def test_not_checked_still_file_and_rule_only(self):
        report = v.validate_content({"a.md": b"bytes"})
        for r in by_status(report.results, CheckStatus.NOT_CHECKED):
            self.assertIsNone(r.line)
            self.assertIsNotNone(r.rule)

    def test_rejects_non_report(self):
        with self.assertRaises(TypeError):
            v.with_consistency_item(None)


if __name__ == "__main__":
    unittest.main()
