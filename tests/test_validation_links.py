"""T12 tests: relative link check. Local temporary fixtures only; no network."""

import itertools
import os
import tempfile
import time
import unittest

from docsync import validation as v
from docsync.contracts import CHECK_RELATIVE_LINKS, CheckStatus


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(tmp.name, "repo")
        self.outside = os.path.join(tmp.name, "outside")
        os.makedirs(os.path.join(self.root, "docs", "guide"))
        os.makedirs(self.outside)
        self.touch("README.md")
        self.touch("docs/api.md")
        self.touch("docs/guide/intro.md")
        self.touch("docs/guide/my file.md")
        self.touch("img/logo.png")
        self.touch("secret.txt", base=self.outside)

    def touch(self, rel, base=None):
        path = os.path.join(base or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")

    def check(self, text, file="README.md", added=None):
        if added is None:
            added = range(1, len(v._lf_lines(text)) + 1)
        return v.check_relative_links({file: text}, self.root, {file: added})

    def failures(self, check):
        return [(r.file, r.line, r.rule) for r in check.results if r.status is CheckStatus.FAILED]


class ResolutionTests(Base):
    def test_missing_file_fails_with_file_line_rule(self):
        c = self.check("ok\n[x](docs/nope.md)\n")
        self.assertEqual(self.failures(c), [("README.md", 2, v.RULE_LINK_MISSING)])

    def test_existing_file_and_image_pass(self):
        c = self.check("[a](docs/api.md) ![l](img/logo.png)\n")
        self.assertEqual([r.status for r in c.results], [CheckStatus.PASSED])
        self.assertEqual(c.results[0].file, "README.md")

    def test_missing_image_fails(self):
        self.assertEqual(self.failures(self.check("![l](img/none.png)\n")), [("README.md", 1, v.RULE_LINK_MISSING)])

    def test_fragment_passes_when_file_exists_and_is_not_checked(self):
        c = self.check("[a](docs/api.md#no-such-anchor)\n")
        self.assertEqual(self.failures(c), [])
        self.assertEqual([r.status for r in c.results], [CheckStatus.PASSED])

    def test_fragment_on_missing_file_still_fails(self):
        self.assertEqual(len(self.failures(self.check("[a](docs/zzz.md#top)\n"))), 1)

    def test_query_is_stripped(self):
        self.assertEqual(self.failures(self.check("[a](docs/api.md?plain=1)\n")), [])

    def test_nested_doc_resolves_against_its_directory(self):
        # from docs/guide/, intro.md exists and docs/api.md does not resolve as written
        ok = self.check("[i](intro.md) [a](../api.md)\n", file="docs/guide/intro.md")
        self.assertEqual(self.failures(ok), [])
        bad = self.check("[a](docs/api.md)\n", file="docs/guide/intro.md")
        self.assertEqual(self.failures(bad), [("docs/guide/intro.md", 1, v.RULE_LINK_MISSING)])

    def test_dot_slash_and_inner_dotdot_inside_root(self):
        self.assertEqual(self.failures(self.check("[a](./docs/guide/../api.md)\n")), [])

    def test_directory_target_exists(self):
        self.assertEqual(self.failures(self.check("[d](docs/)\n")), [])

    def test_angle_bracket_destination_with_space_and_title(self):
        self.assertEqual(self.failures(self.check('[a](<docs/guide/my file.md> "t")\n')), [])
        self.assertEqual(self.failures(self.check('[a](docs/api.md "title")\n')), [])

    def test_percent_encoding_decoded_once(self):
        self.assertEqual(self.failures(self.check("[a](docs/guide/my%20file.md)\n")), [])
        self.assertEqual(len(self.failures(self.check("[a](docs/guide/my%2520file.md)\n"))), 1)

    def test_duplicate_failures_on_a_line_reported_once(self):
        c = self.check("[a](n.md) [b](n.md)\n")
        self.assertEqual(len(self.failures(c)), 1)

    def test_links_in_code_are_ignored(self):
        text = "`[a](missing.md)`\n```\n[b](missing.md)\n```\n"
        c = self.check(text)
        self.assertEqual(self.failures(c), [])

    def test_empty_destination_is_syntax_check_business(self):
        self.assertEqual(self.failures(self.check("[a]()\n")), [])


class LimitationTests(Base):
    def limits(self, c):
        return [(f, n, r) for f, n, r in c.limitations]

    def test_external_autolink_reference_skipped_and_listed(self):
        text = (
            "[e](https://example.invalid/x)\n"
            "<https://example.invalid/y>\n"
            "[r][ref]\n"
            "[ref]: missing.md\n"
            "[m](mailto:a@example.invalid)\n"
            "[p](//example.invalid/z)\n"
        )
        c = self.check(text)
        self.assertEqual(self.failures(c), [])
        got = set(self.limits(c))
        self.assertIn(("README.md", 1, v.LIMIT_EXTERNAL), got)
        self.assertIn(("README.md", 2, v.LIMIT_AUTOLINK), got)
        self.assertIn(("README.md", 3, v.LIMIT_REFERENCE), got)
        self.assertIn(("README.md", 4, v.LIMIT_REFERENCE), got)
        self.assertIn(("README.md", 5, v.LIMIT_EXTERNAL), got)
        self.assertIn(("README.md", 6, v.LIMIT_EXTERNAL), got)

    def test_skipped_items_never_reported_as_passing(self):
        c = self.check("[e](https://example.invalid/x)\n")
        # the only PASSED result is the per-file 'no broken link on added lines';
        # it carries no line or link (only the scope label rule), and the skipped link is a limitation only
        self.assertEqual([(r.status, r.line, r.rule) for r in c.results],
                         [(CheckStatus.PASSED, None, v.RULE_LINKS_SCOPE)])
        self.assertEqual(len(c.limitations), 1)

    def test_anchor_only_is_a_limitation(self):
        c = self.check("[a](#section)\n")
        self.assertEqual(self.limits(c), [("README.md", 1, v.LIMIT_ANCHOR)])
        self.assertEqual(self.failures(c), [])

    def test_broken_link_on_line_not_added_is_not_failure_but_limitation(self):
        text = "[a](gone.md)\n[b](gone2.md)\nplain\n"
        c = self.check(text, added=[2])
        self.assertEqual(self.failures(c), [("README.md", 2, v.RULE_LINK_MISSING)])
        self.assertIn(("README.md", 1, v.LIMIT_NOT_ADDED), self.limits(c))
        c2 = self.check(text, added=[3])  # only a link-free line is added
        self.assertEqual(self.failures(c2), [])
        self.assertEqual(sorted(self.limits(c2)),
                         [("README.md", 1, v.LIMIT_NOT_ADDED), ("README.md", 2, v.LIMIT_NOT_ADDED)])
        self.assertEqual([r.status for r in c2.results], [CheckStatus.PASSED])

    def test_external_on_non_added_line_is_not_listed(self):
        c = self.check("[e](https://example.invalid/x)\nplain\n", added=[2])
        self.assertEqual(c.limitations, [])

    def test_limitations_become_nonblocking_not_found_items(self):
        text = "[e](https://example.invalid/x)\n[ok](docs/api.md)\n"
        report = v.validate_content({"README.md": text}, self.root, {"README.md": [1, 2]})
        subjects = [n.subject for n in report.not_found]
        self.assertIn(v.LINKS_LIMITATION_SUBJECT, subjects)
        self.assertIn(v.CONSISTENCY_SUBJECT, subjects)
        self.assertTrue(report.passed)
        item = [n for n in report.not_found if n.subject == v.LINKS_LIMITATION_SUBJECT][0]
        self.assertTrue(item.detail.startswith("Not Found:"))
        self.assertEqual(item.files, ("README.md",))
        self.assertNotIn("example.invalid", item.detail)  # no document content echoed


class SecurityTests(Base):
    def assertOutside(self, dest, rule=None):
        c = self.check("[a](%s)\n" % dest)
        self.assertEqual(self.failures(c), [("README.md", 1, rule or v.RULE_LINK_OUTSIDE_ROOT)], dest)

    def test_dotdot_escape(self):
        self.assertOutside("../outside/secret.txt")
        self.assertOutside("docs/../../outside/secret.txt")
        self.assertOutside("%2e%2e/outside/secret.txt")
        self.assertOutside("..%2Foutside/secret.txt")

    def test_dotdot_from_nested_doc_to_root_is_ok_but_one_more_escapes(self):
        c = self.check("[a](../../README.md)\n", file="docs/guide/intro.md")
        self.assertEqual(self.failures(c), [])
        c = self.check("[a](../../../outside/secret.txt)\n", file="docs/guide/intro.md")
        self.assertEqual(len(self.failures(c)), 1)

    def test_absolute_drive_and_unc(self):
        target = os.path.join(self.outside, "secret.txt").replace("\\", "/")
        self.assertOutside("/" + target.lstrip("/"))
        self.assertOutside("/etc/passwd")
        self.assertOutside("C:/Windows/win.ini")
        self.assertOutside("c:secret.txt")
        self.assertOutside("%2Fetc%2Fpasswd")
        self.assertOutside("%5C%5Cserver%5Cshare", v.RULE_LINK_INVALID)  # decoded backslashes
        # the two-slash form is protocol-relative and external (never opened)
        c = self.check("[a](//server/share/x)\n")
        self.assertEqual(self.failures(c), [])
        self.assertEqual([x[2] for x in c.limitations], [v.LIMIT_EXTERNAL])

    def test_backslash_forms_are_invalid(self):
        self.assertOutside("docs\\api.md", v.RULE_LINK_INVALID)
        self.assertOutside("\\\\server\\share\\x", v.RULE_LINK_INVALID)

    def test_nul_and_control_characters(self):
        self.assertOutside("docs/api.md%00.png", v.RULE_LINK_INVALID)
        self.assertOutside("docs/api.md%0a", v.RULE_LINK_INVALID)
        c = v.check_relative_links({"README.md": "[a](docs/\x00x)\n"}, self.root, {"README.md": [1]})
        self.assertEqual([x[2] for x in self.failures(c)], [v.RULE_LINK_INVALID])

    def test_bad_percent_encoding_utf8(self):
        self.assertOutside("docs/%ff%fe", v.RULE_LINK_INVALID)

    def test_stream_device_and_trailing_dot_names_invalid(self):
        self.assertOutside("docs/api.md:stream", v.RULE_LINK_INVALID)
        self.assertOutside("docs/nul", v.RULE_LINK_INVALID)
        self.assertOutside("docs/NUL.txt", v.RULE_LINK_INVALID)
        self.assertOutside("docs/api.md.", v.RULE_LINK_INVALID)
        self.assertOutside("docs/api.md%20", v.RULE_LINK_INVALID)

    def test_overlong_target(self):
        self.assertOutside("a/" * 3000 + "x.md", v.RULE_LINK_INVALID)

    def test_document_path_must_be_inside_root(self):
        for bad in ("../x.md", "/abs/x.md", "C:/x.md", "docs/../../x.md", "a\x00.md"):
            c = v.check_relative_links({bad: "[a](api.md)\n"}, self.root, {bad: [1]})
            (r,) = c.results
            self.assertIs(r.status, CheckStatus.NOT_CHECKED, bad)
            self.assertEqual((r.file, r.line, r.rule), (bad, None, v.RULE_DOC_PATH))

    def test_target_contents_never_read(self):
        real_open = open
        import builtins
        seen = []

        def spy(file, *a, **k):
            seen.append(file)
            return real_open(file, *a, **k)

        builtins.open = spy
        try:
            self.check("[a](docs/api.md)\n")
        finally:
            builtins.open = real_open
        self.assertEqual(seen, [])

    def test_junction_escape(self):
        try:
            import _winapi
            create = _winapi.CreateJunction
        except (ImportError, AttributeError):
            self.skipTest("Windows junctions unavailable (_winapi.CreateJunction exists only on Windows)")
        link = os.path.join(self.root, "docs", "junc")
        try:
            create(self.outside, link)
        except OSError as exc:
            self.skipTest("junction creation failed: %s" % type(exc).__name__)
        self.assertOutside("docs/junc/secret.txt")


class NotCheckedTests(Base):
    def only(self, c):
        (r,) = c.results
        self.assertIs(r.status, CheckStatus.NOT_CHECKED)
        self.assertIsNone(r.line)
        self.assertIsNotNone(r.rule)
        return r

    def test_no_root(self):
        r = self.only(v.check_relative_links({"README.md": "[a](x.md)\n"}, None, {"README.md": [1]}))
        self.assertEqual((r.file, r.rule), ("README.md", v.RULE_LINKS_ROOT))

    def test_bad_root(self):
        missing = os.path.join(self.root, "does-not-exist")
        for root in (missing, 5, os.path.join(self.root, "README.md"), "a\x00b"):
            self.only(v.check_relative_links({"README.md": "x\n"}, root, {"README.md": [1]}))

    def test_no_added_lines_info(self):
        r = self.only(v.check_relative_links({"README.md": "[a](x.md)\n"}, self.root, None))
        self.assertEqual(r.rule, v.RULE_NO_ADDED_LINES)
        r = self.only(v.check_relative_links({"README.md": "[a](x.md)\n"}, self.root, {"other.md": [1]}))
        self.assertEqual(r.rule, v.RULE_NO_ADDED_LINES)

    def test_non_text(self):
        r = self.only(v.check_relative_links({"README.md": b"x"}, self.root, {"README.md": [1]}))
        self.assertEqual(r.rule, v.RULE_NOT_TEXT)

    def test_bad_added_lines_shapes(self):
        with self.assertRaises(TypeError):
            v.check_relative_links({"a.md": "x"}, self.root, [1, 2])
        for bad in (0, -1, True, "1", 1.5):
            with self.assertRaises(TypeError, msg=repr(bad)):
                v.check_relative_links({"a.md": "x"}, self.root, {"a.md": [bad]})

    def test_no_documents_emits_no_link_result(self):
        self.assertEqual(v.check_relative_links({}, self.root, {}).results, [])


SEPARATORS = ["\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]


class LfNumberingTests(Base):
    """MEDIUM-1: added_lines numbering is LF-only, like Git."""

    def test_each_separator_does_not_shift_git_numbering(self):
        for sep in SEPARATORS:
            text = "a%sb\nplain\n[x](gone.md)\n" % sep  # broken link is Git line 3
            c = self.check(text, added=[3])
            self.assertEqual(self.failures(c), [("README.md", 3, v.RULE_LINK_MISSING)], repr(sep))
            self.assertEqual(c.limitations, [], repr(sep))

    def test_separator_does_not_downgrade_to_not_added(self):
        for sep in SEPARATORS:
            text = "a%sb%sc\n[x](gone.md)\n" % (sep, sep)  # broken link is Git line 2
            c = self.check(text, added=[2])
            self.assertEqual([x[2] for x in self.failures(c)], [v.RULE_LINK_MISSING], repr(sep))
            self.assertNotIn(v.LIMIT_NOT_ADDED, [x[2] for x in c.limitations], repr(sep))
            other = self.check(text, added=[1])  # only line 1 added: link is on a non-added line
            self.assertEqual(self.failures(other), [], repr(sep))
            self.assertIn(("README.md", 2, v.LIMIT_NOT_ADDED), other.limitations)

    def test_crlf_content_works(self):
        text = "# T\r\n[ok](docs/api.md)\r\n[x](gone.md)\r\n"
        c = self.check(text)
        self.assertEqual(self.failures(c), [("README.md", 3, v.RULE_LINK_MISSING)])
        ok = self.check('[a](docs/api.md)\r\n[b](docs/api.md "t")\r\n[c](<docs/api.md>)\r\n')
        self.assertEqual(self.failures(ok), [])
        self.assertEqual([r.status for r in ok.results], [CheckStatus.PASSED])

    def test_crlf_does_not_hide_fences(self):
        c = self.check("```\r\n[a](gone.md)\r\n```\r\n[b](docs/api.md)\r\n")
        self.assertEqual(self.failures(c), [])

    def test_line_counting_rule(self):
        self.assertEqual(v._lf_lines(""), [])
        self.assertEqual(v._lf_lines("a"), ["a"])        # final line without LF counts
        self.assertEqual(v._lf_lines("a\n"), ["a"])      # trailing LF adds no line
        self.assertEqual(v._lf_lines("a\n\n"), ["a", ""])
        self.assertEqual(v._lf_lines("a\r\nb\r\n"), ["a", "b"])
        self.assertEqual(v._lf_lines("a\rb\n"), ["a\rb"])

    def test_final_line_without_newline_can_be_added(self):
        c = self.check("ok\n[x](gone.md)", added=[2])
        self.assertEqual(self.failures(c), [("README.md", 2, v.RULE_LINK_MISSING)])

    def test_trailing_newline_makes_no_extra_line(self):
        c = self.check("[x](gone.md)\n", added=[1, 2])  # 2 is beyond the 1-line document
        (r,) = c.results
        self.assertEqual((r.status, r.rule), (CheckStatus.NOT_CHECKED, v.RULE_ADDED_LINES_AMBIGUOUS))

    def test_lone_cr_in_text_is_not_a_line_break_for_destinations(self):
        # a lone CR is whitespace between destination and title, not a new line
        c = self.check("[x](docs/api.md\rfoo)\n[y](gone.md)\n", added=[2])
        self.assertEqual(self.failures(c), [("README.md", 2, v.RULE_LINK_MISSING)])

    def test_other_control_character_inside_destination_is_invalid(self):
        c = self.check("[x](docs/api.md\x01foo)\n")
        self.assertEqual(self.failures(c), [("README.md", 1, v.RULE_LINK_INVALID)])


class AmbiguousAddedLinesTests(Base):
    def one(self, text, added):
        c = v.check_relative_links({"README.md": text}, self.root, {"README.md": added})
        (r,) = c.results
        return r

    def assertAmbiguous(self, text, added):
        r = self.one(text, added)
        self.assertEqual((r.status, r.file, r.line, r.rule),
                         (CheckStatus.NOT_CHECKED, "README.md", None, v.RULE_ADDED_LINES_AMBIGUOUS))

    def test_empty_list_set_and_iterator_for_nonblank_document(self):
        self.assertAmbiguous("# T\n", [])
        self.assertAmbiguous("# T\n", set())
        self.assertAmbiguous("# T\n", iter(()))
        self.assertAmbiguous("x", ())

    def test_all_beyond_length(self):
        self.assertAmbiguous("a\nb\n", [3, 4])

    def test_any_beyond_length_makes_whole_set_ambiguous(self):
        self.assertAmbiguous("[x](gone.md)\nb\n", [1, 3])

    def test_in_range_set_is_checked(self):
        r = self.one("[x](gone.md)\nb\n", [1, 2])
        self.assertEqual((r.status, r.line, r.rule), (CheckStatus.FAILED, 1, v.RULE_LINK_MISSING))

    def test_empty_or_blank_document_with_empty_set_passes_but_output_check_fails(self):
        for text in ("", "  \n\n"):
            self.assertIs(self.one(text, []).status, CheckStatus.PASSED)
        report = v.validate_content({"README.md": ""}, self.root, {"README.md": []})
        self.assertFalse(report.passed)  # the non-empty-output check fails

    def test_empty_document_with_out_of_range_number_is_ambiguous(self):
        self.assertAmbiguous("", [1])

    def test_ambiguous_never_passes_report(self):
        report = v.validate_content({"README.md": "# T\n"}, self.root, {"README.md": range(1, 10)})
        self.assertFalse(report.passed)

    def test_bad_shapes_still_raise(self):
        with self.assertRaises(TypeError):
            v.check_relative_links({"a.md": "x"}, self.root, {"a.md": [None]})


class ScopeLabelTests(Base):
    def test_passed_results_carry_scope_label_and_others_do_not(self):
        self.assertEqual(v.RULE_LINKS_SCOPE, "added-inline-relative-links")
        self.assertIn("RULE_LINKS_SCOPE", v.__all__)
        passed = [
            self.check("[a](docs/api.md)\n"),                  # clean document
            self.check("[e](https://example.invalid/x)\n"),    # only external links
            self.check("  \n\n", added=[]),                      # blank document, empty set
            self.check("", added=[]),                          # empty document, empty set
        ]
        for c in passed:
            (r,) = c.results
            self.assertEqual((r.status, r.file, r.line, r.rule),
                             (CheckStatus.PASSED, "README.md", None, v.RULE_LINKS_SCOPE))
        failed = self.check("[a](gone.md)\n")
        notchecked = v.check_relative_links({"README.md": "x\n"}, None, {"README.md": [1]})
        for c, status in ((failed, CheckStatus.FAILED), (notchecked, CheckStatus.NOT_CHECKED)):
            (r,) = c.results
            self.assertIs(r.status, status)
            self.assertNotEqual(r.rule, v.RULE_LINKS_SCOPE)
        self.assertIsNone(notchecked.results[0].line)


class IntegrationTests(Base):
    def test_clean_report_passes_with_root_and_added_lines(self):
        text = "# Title\n\nSee [api](docs/api.md#x).\n"
        report = v.validate_content({"README.md": text}, self.root, {"README.md": [1, 2, 3]})
        self.assertTrue(report.passed)
        self.assertIn(CHECK_RELATIVE_LINKS, {r.check for r in report.results})
        self.assertEqual([n.detail for n in report.not_found], [v.CONSISTENCY_DETAIL])

    def test_broken_link_blocks_pass_and_consistency_item_kept(self):
        report = v.validate_content({"README.md": "[a](nope.md)\n"}, self.root, {"README.md": [1]})
        self.assertFalse(report.passed)
        self.assertIn(v.CONSISTENCY_SUBJECT, [n.subject for n in report.not_found])

    def test_without_root_never_passes(self):
        report = v.validate_content({"README.md": "# T\n"})
        self.assertFalse(report.passed)
        links = [r for r in report.results if r.check == CHECK_RELATIVE_LINKS]
        self.assertTrue(links and all(r.status is CheckStatus.NOT_CHECKED for r in links))

    def test_not_checked_stay_file_and_rule_only(self):
        report = v.validate_content({"README.md": "# T\n"}, self.root, None)
        for r in report.results:
            if r.status is CheckStatus.NOT_CHECKED:
                self.assertIsNone(r.line)
                self.assertIsNotNone(r.rule)

    def test_empty_change_set_for_nonblank_document_is_not_checked_and_never_passes(self):
        # was: asserted passed is True (Attempt 1); an empty set is now ambiguous (MEDIUM-2)
        report = v.validate_content({"README.md": "# T\n[a](gone.md)\n"}, self.root, {"README.md": []})
        self.assertFalse(report.passed)
        links = [r for r in report.results if r.check == CHECK_RELATIVE_LINKS]
        self.assertEqual([(r.status, r.file, r.line, r.rule) for r in links],
                         [(CheckStatus.NOT_CHECKED, "README.md", None, v.RULE_ADDED_LINES_AMBIGUOUS)])

    def test_many_limitation_lines_are_capped(self):
        text = "[e](https://example.invalid/x)\n" * 50
        report = v.validate_content({"README.md": text}, self.root, {"README.md": range(1, 51)})
        item = [n for n in report.not_found if n.subject == v.LINKS_LIMITATION_SUBJECT][0]
        self.assertIn("and 30 more", item.detail)


class HostileInputTests(Base):
    def timed(self, text):
        start = time.perf_counter()
        self.check(text, added=[1])
        self.assertLess(time.perf_counter() - start, 2.0)

    def test_hostile_long_lines_are_linear(self):
        n = 200000
        self.timed("<" * n + ">")
        self.timed("<a:" * n)
        self.timed("[" * n)
        self.timed("](" * n)
        self.timed("](" + "(" * n)
        self.timed("[a]" * n + "[")
        self.timed("`" * n)
        self.timed("\\" * n)
        self.timed("[a](" + "%" * n + ")")

    def test_hostile_lines_with_separators_and_many_lines(self):
        n = 100000
        self.timed("\r" * n + "[a](x.md)")
        self.timed("\r\n" * n)
        self.timed("\x0b[a](" * n)
        self.timed("\u2028](" * n)

class SharedNumberingTests(Base):
    """MEDIUM-3: T11 (syntax) and T12 (links) share one LF line walk and one fence state."""

    def syntax_lines(self, text):
        return sorted(n for n, rule in v.scan_markdown(text) if rule == v.RULE_UNCLOSED_LINK)

    def link_lines(self, text):
        return sorted(n for _, n, _ in self.failures(self.check(text)))

    def assert_same_lines(self, template, expected, sep):
        bad = template.replace("LINK", "[x](oops").replace("SEP", sep)
        good = template.replace("LINK", "[x](gone.md)").replace("SEP", sep)
        self.assertEqual(self.syntax_lines(bad), expected, repr(sep))
        self.assertEqual(self.link_lines(good), expected, repr(sep))

    def test_same_line_numbers_next_to_each_separator(self):
        templates = [
            ("aSEPb\nLINK\n", [2]),
            ("LINK\naSEPb\nLINK\n", [1, 3]),
            ("aSEPb\n```\nLINK\n```\nLINK\n", [5]),
            ("```SEP\nLINK\n```SEP\nLINK\n", [4]),
            ("~~~SEP\nLINK\n~~~\nSEPLINK\n", [4]),
            ("SEP\nSEP\nLINK\n", [3]),
        ]
        for sep in SEPARATORS:
            for template, expected in templates:
                self.assert_same_lines(template, expected, sep)

    def test_same_fence_state_for_unclosed_fence(self):
        for sep in SEPARATORS:
            text = "aSEPb\n```\n[x](gone.md)\n".replace("SEP", sep)
            self.assertEqual(v.scan_markdown(text), [(2, v.RULE_UNCLOSED_FENCE)], repr(sep))
            self.assertEqual(self.failures(self.check(text)), [], repr(sep))  # swallowed by the fence

    def test_vertical_tab_audit_examples_are_consistent(self):
        vt = "\x0b"
        # fence markers glued to a separator are not fences; a link between them is prose
        broken = "x" + vt + "```\n[x](gone.md)\n```" + vt + "\n"
        self.assertEqual(self.failures(self.check(broken)), [("README.md", 2, v.RULE_LINK_MISSING)])
        self.assertEqual(v.scan_markdown(broken), [(3, v.RULE_UNCLOSED_FENCE)])
        malformed = "x" + vt + "```\n[x](oops\n```" + vt + "\n"
        self.assertEqual(v.scan_markdown(malformed), [(2, v.RULE_UNCLOSED_LINK), (3, v.RULE_UNCLOSED_FENCE)])
        # reverse: a real fence line carrying a separator suffix
        rev = "```" + vt + "\n[x](gone.md)\n```" + vt + "\n[y](gone.md)\n"
        self.assertEqual(self.failures(self.check(rev)), [("README.md", 4, v.RULE_LINK_MISSING)])
        self.assertEqual(v.scan_markdown(rev.replace("[y](gone.md)", "[y](oops").replace("[x](gone.md)", "[x](oops")),
                         [(4, v.RULE_UNCLOSED_LINK)])
        # fence opened, link then separator, then closing fence: still one state in both
        both = "```\n[x](gone.md)" + vt + "```\n[y](gone.md)\n"
        self.assertEqual(self.failures(self.check(both)), [])
        self.assertEqual(v.scan_markdown(both), [(1, v.RULE_UNCLOSED_FENCE)])

    def test_no_link_is_prose_in_one_check_and_skipped_in_the_other(self):
        for sep in SEPARATORS:
            for template in ("```SEP\nLINK\n```\nLINK\n", "aSEP```\nLINK\n```SEP\nLINK\n", "SEP```\nLINK\nSEP```\n"):
                bad = template.replace("LINK", "[x](oops").replace("SEP", sep)
                good = template.replace("LINK", "[x](gone.md)").replace("SEP", sep)
                self.assertEqual(self.syntax_lines(bad), self.link_lines(good), repr((sep, template)))

    def test_lone_cr_is_not_a_line_break(self):
        # decided: a lone CR is data, like every separator other than LF; CRLF still ends a line
        self.assertEqual(v.scan_markdown("a" + chr(13) + "[x](oops" + chr(10)), [(1, v.RULE_UNCLOSED_LINK)])
        self.assertEqual(v.scan_markdown("~~~" + chr(13) + "~~~" + chr(10)), [(1, v.RULE_UNCLOSED_FENCE)])
        self.assertEqual(v._lf_lines("a" + chr(13) + "b" + chr(10)), ["a" + chr(13) + "b"])
        self.assertEqual(v.scan_markdown("```\r\nx\r\n```\r\n"), [])
        self.assertEqual(v.scan_markdown("ok\r\n[x](oops\r\n"), [(2, v.RULE_UNCLOSED_LINK)])
        c = self.check("a" + chr(13) + "b\n[x](gone.md)\n", added=[2])
        self.assertEqual(self.failures(c), [("README.md", 2, v.RULE_LINK_MISSING)])

    def test_validate_content_reports_lf_line_numbers(self):
        for sep in SEPARATORS:
            text = "aSEPb\n```\n[x](gone.md)\n```\n[y](gone.md)\n[z](oops\n".replace("SEP", sep)
            report = v.validate_content({"README.md": text}, self.root, {"README.md": range(1, 7)})
            failed = sorted((r.check, r.line, r.rule) for r in report.results if r.status is CheckStatus.FAILED)
            self.assertEqual(failed, [("markdown_syntax", 6, v.RULE_UNCLOSED_LINK),
                                      (CHECK_RELATIVE_LINKS, 5, v.RULE_LINK_MISSING)], repr(sep))
            partial = v.validate_content({"README.md": text}, self.root, {"README.md": [1]})
            detail = " ".join(n.detail for n in partial.not_found)
            self.assertIn("(%s) at line(s) 5" % v.LIMIT_NOT_ADDED, detail, repr(sep))
            self.assertFalse(report.passed)


class BoundedAddedLinesTests(Base):
    """New Low 1: added_lines is consumed lazily and bounded."""
    BOUND = 5.0

    def assert_ambiguous_fast(self, added, text="[x](gone.md)\nb\nc\n"):
        start = time.perf_counter()
        c = v.check_relative_links({"README.md": text}, self.root, {"README.md": added})
        self.assertLess(time.perf_counter() - start, self.BOUND)
        (r,) = c.results
        self.assertEqual((r.status, r.file, r.line, r.rule),
                         (CheckStatus.NOT_CHECKED, "README.md", None, v.RULE_ADDED_LINES_AMBIGUOUS))

    def test_huge_range(self):
        self.assert_ambiguous_fast(range(1, 10 ** 12))

    def test_infinite_generator(self):
        self.assert_ambiguous_fast(itertools.count(1))

    def test_huge_duplicate_heavy_inputs(self):
        self.assert_ambiguous_fast([1] * 3000000)
        self.assert_ambiguous_fast(itertools.repeat(1, 10 ** 12))  # in range, endless duplicates: item cap

    def test_out_of_range_number_stops_consumption(self):
        seen = []

        def gen():
            for n in (1, 99, 2, 3):
                seen.append(n)
                yield n
        self.assert_ambiguous_fast(gen())
        self.assertEqual(seen, [1, 99])

    def test_small_duplicates_and_in_range_still_work(self):
        c = self.check("[x](gone.md)\nb\n", added=[1, 1, 2, 2])
        self.assertEqual(self.failures(c), [("README.md", 1, v.RULE_LINK_MISSING)])
        c = self.check("[x](gone.md)\nb\n", added=(n for n in (1, 2)))
        self.assertEqual(self.failures(c), [("README.md", 1, v.RULE_LINK_MISSING)])

    def test_bad_shapes_still_raise(self):
        for bad in ([0], [-3], [True], ["1"], [1.5], 5):
            with self.assertRaises(TypeError, msg=repr(bad)):
                v.check_relative_links({"a.md": "x\n"}, self.root, {"a.md": bad})


if __name__ == "__main__":
    unittest.main()
