"""T10b tests: Proposal Builder (docsync/proposal.py). Small local fixtures, no external calls."""

import ast
import builtins
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docsync import proposal, redact, validation
from docsync.contracts import CheckStatus, NotFoundItem, ProposedEdit
from docsync.output import DocumentChange, render_patch
from docsync.proposal import (
    HEADING,
    MAX_ORIGINAL_CHARS,
    MAX_REASON_CHARS,
    MAX_SYMBOL_CHARS,
    MAX_SYMBOLS,
    ProposalResult,
    ProposedDocument,
    RejectedEdit,
    SkippedDocument,
    build_proposals,
)

DOC = "docs/api.md"
REASON = "Source change in src/a.py: update docs/api.md for the changed symbols"
FAKE_SECRET = "AKIA" + "ZZ9QXY7WMN3PLK2R"  # built at runtime, fake


class Reader:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        return self.files.get(path)


def edit(target=DOC, reason=REASON, symbols=()):
    return ProposedEdit(target, reason, (), tuple(symbols))


def one(original, edits=None, target=DOC):
    result = build_proposals(edits or [edit(target, symbols=("b", "a"))], Reader({target: original}))
    return result


def everything(result):
    """All text the result exposes outside the structured path fields."""
    parts = [repr(result), str(result)]
    for item in result.not_found:
        parts += [item.subject, item.detail]
    parts += [s.reason for s in result.skipped] + [r.rule for r in result.rejected]
    # repr of NotFoundItem (a contracts type) shows its structured ``files`` field, so it is excluded
    parts += [repr(d) for d in result.documents + result.skipped + result.rejected]
    return "\n".join(parts)


class GoldenTests(unittest.TestCase):
    def test_one_edit_with_symbols(self):
        r = one("# T\n\ntext\n")
        (d,) = r.documents
        self.assertEqual(
            d.proposed,
            "# T\n\ntext\n\n" + HEADING + "\n\n- " + REASON + "\n  Changed symbols: a, b\n",
        )
        self.assertEqual(d.added_lines, (4, 5, 6, 7, 8))
        self.assertEqual(r.skipped, ())
        self.assertEqual(r.rejected, ())
        self.assertEqual(r.not_found, ())

    def test_one_edit_without_symbols(self):
        (d,) = one("x\n\n", [edit()]).documents
        self.assertEqual(d.proposed, "x\n\n" + HEADING + "\n\n- " + REASON + "\n")
        self.assertEqual(d.added_lines, (3, 4, 5))

    def test_two_edits_one_section(self):
        e1 = edit(reason="First change", symbols=["z"])
        e2 = edit(reason="Second change")
        (d,) = one("x\n\n", [e1, e2]).documents
        self.assertEqual(d.proposed.count(HEADING), 1)
        self.assertEqual(
            d.proposed,
            "x\n\n" + HEADING + "\n\n- First change\n  Changed symbols: z\n- Second change\n",
        )
        self.assertEqual(d.added_lines, (3, 4, 5, 6, 7))

    def test_duplicate_edit_written_once(self):
        e1 = edit(symbols=["b", "a"])
        e2 = edit(symbols=["a", "b", "a"])
        (d,) = one("x\n\n", [e1, e2]).documents
        self.assertEqual(d.proposed.count("- " + REASON), 1)

    def test_newline_golden_cases(self):
        block = HEADING + "\n\n- " + REASON + "\n"
        # "abc" and "abc\n": the separator is line 2 (the LF ending "abc" is not counted)
        for original, prefix, added in (
            ("abc", "abc\n\n", (2, 3, 4, 5)),
            ("abc\n", "abc\n\n", (2, 3, 4, 5)),
            ("abc\n\n", "abc\n\n", (3, 4, 5)),
        ):
            with self.subTest(original=original):
                (d,) = one(original, [edit()]).documents
                self.assertEqual(d.proposed, prefix + block)
                self.assertEqual(d.added_lines, added)

    def test_added_lines_match_generated_lines(self):
        for original in ("abc", "abc\n", "abc\n\n", "", "a\r\n\r\n", "a\r\n", "a\r", "\ufeff", "\n"):
            with self.subTest(original=original):
                (d,) = one(original, [edit(symbols=["q"])]).documents
                lines = d.proposed.split("\n")[:-1]
                self.assertTrue(d.proposed.startswith(original))
                generated = [lines[n - 1] for n in d.added_lines]
                self.assertIn(HEADING, generated)
                self.assertEqual(d.added_lines[-1], len(lines))
                self.assertEqual(list(d.added_lines), list(range(d.added_lines[0], len(lines) + 1)))

    def test_prefix_and_separator_rules(self):
        cases = {
            "": "",
            "lf\n": "lf\n\n",
            "crlf\r\n": "crlf\r\n\n",
            "mixed\r\nx\n": "mixed\r\nx\n\n",
            "nofinal": "nofinal\n\n",
            "blank\n\n": "blank\n\n",
            "blank\r\n\r\n": "blank\r\n\r\n",
            "a\r": "a\r\n\n",
            "\ufeff": "\ufeff\n\n",
            "sp\n  \n": "sp\n  \n",
        }
        for original, prefix in cases.items():
            with self.subTest(original=original):
                (d,) = one(original, [edit()]).documents
                self.assertTrue(d.proposed.startswith(original))
                self.assertTrue(d.proposed.startswith(prefix))
                self.assertTrue(d.proposed[len(prefix):].startswith(HEADING + "\n"))
                self.assertTrue(d.proposed.endswith("\n"))

    def test_empty_original_block_starts_at_line_one(self):
        (d,) = one("", [edit()]).documents
        self.assertEqual(d.added_lines, (1, 2, 3))

    def test_existing_heading_gets_second_section(self):
        original = HEADING + "\n\n- old\n"
        (d,) = one(original, [edit()]).documents
        self.assertEqual(d.proposed.count(HEADING), 2)

    def test_deterministic_and_sorted(self):
        files = {"docs/b.md": "b\n", "README.md": "r\n", "docs/a.md": "a\n"}
        edits = [edit("docs/b.md"), edit("README.md"), edit("docs/a.md")]
        r1 = build_proposals(edits, Reader(files))
        r2 = build_proposals(list(edits), Reader(dict(files)))
        self.assertEqual(r1, r2)
        self.assertEqual([d.path for d in r1.documents], ["README.md", "docs/a.md", "docs/b.md"])

    def test_empty_change_set(self):
        reader = Reader({})
        r = build_proposals([], reader)
        self.assertEqual((r.documents, r.skipped, r.rejected, r.not_found), ((), (), (), ()))
        self.assertEqual(reader.calls, [])


class UnreadableTests(unittest.TestCase):
    def assert_skipped(self, result, path=DOC):
        self.assertEqual(result.documents, ())
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0].path, path)
        (nf,) = result.not_found
        self.assertTrue(nf.detail.startswith("Not Found:"))

    def test_missing_document_and_none_reader(self):
        self.assert_skipped(build_proposals([edit()], Reader({})))
        self.assert_skipped(build_proposals([edit()], lambda p: None))

    def test_non_string_reader_result(self):
        self.assert_skipped(build_proposals([edit()], lambda p: b"bytes"))

    def test_nul_in_text(self):
        self.assert_skipped(one("a\x00b"))

    def test_text_over_limit(self):
        self.assert_skipped(one("a" * (MAX_ORIGINAL_CHARS + 1)))
        self.assertEqual(len(one("a" * MAX_ORIGINAL_CHARS).documents), 1)

    def test_invalid_paths_never_call_reader(self):
        bad = ["/abs.md", "docs/../x.md", "docs\\a.md", "docs/a\x07.md", "docs/a\x00.md",
               "docs/a.txt", "src/a.md", "", "docs/", "docs", "x.md", "README.MD", "readme.md"]
        for target in bad:
            if not target.strip():
                continue  # ProposedEdit itself refuses a blank target
            with self.subTest(target=target):
                reader = Reader({target: "x\n"})
                r = build_proposals([edit(target)], reader)
                self.assertEqual(reader.calls, [])
                self.assertEqual(r.documents, ())
                self.assertEqual(r.skipped, (SkippedDocument(None, proposal.SKIP_INVALID_PATH),))
                (nf,) = r.not_found
                self.assertEqual(nf.files, ())
                self.assertNotIn(target, everything(r))

    def test_path_table_matches_document_change(self):
        targets = ["README.md", "docs/a.md", "docs/sub/a.md", "docs//a.md", "docs/./a.md", "docs/A.MD",
                   "a:b/x.md", "docs/a:b.md", "docs/a.md/", "./docs/a.md", "docs/ a.md", "docs/\u00e9.md",
                   "docs/a\x7f.md", "docs/a\x1b.md", "docs/..", "docs/.md", "docs/a.md ", " docs/a.md",
                   "/docs/a.md", "C:/docs/a.md", "docs\\a.md", "docs/a\n.md", "README.md/x", "docs/x/../a.md"]
        for target in targets:
            with self.subTest(target=target):
                try:
                    DocumentChange(target, "o", "p")
                    expected = True
                except ValueError:
                    expected = False
                reader = Reader({target: "x\n"})
                r = build_proposals([edit(target)], reader)
                self.assertEqual(len(r.documents) == 1, expected)
                self.assertEqual(bool(reader.calls), expected)

    def test_reader_exception_propagates(self):
        def boom(path):
            raise RuntimeError("reader failed")

        with self.assertRaises(RuntimeError):
            build_proposals([edit()], boom)

    def test_bad_arguments(self):
        with self.assertRaises(TypeError):
            build_proposals([edit()], None)
        with self.assertRaises(TypeError):
            build_proposals(["docs/a.md"], lambda p: "x")
        with self.assertRaises(TypeError):
            build_proposals("docs/a.md", lambda p: "x")


class ValueRuleTests(unittest.TestCase):
    def rejected(self, reason=REASON, symbols=(), rule=None):
        r = build_proposals([edit(reason=reason, symbols=symbols)], Reader({DOC: "x\n"}))
        self.assertEqual(r.documents, ())
        self.assertEqual(len(r.rejected), 1)
        if rule:
            self.assertEqual(r.rejected[0].rule, rule)
        self.assertEqual(r.rejected[0].target, DOC)
        return r

    def test_bad_reasons(self):
        bad = ["a\nb", "a\rb", "a\x0bb", "a\x0cb", "a\x85b", "a\u2028b", "a\u2029b", "a\x1bb", "a\x00b",
               "a\x9bb", "a\u202eb", "a\u200bb", "caf\u00e9", "a`b", "a<b", "a>b", "a[b", "a]b", "a(b",
               "a)b", "a|b", "a~b", "a\\b", "a&b", "#head", ">quote", "-item", "+item", "*item", "=eq",
               "1. item", "12) item", " lead", "\tlead", "a" * (MAX_REASON_CHARS + 1), "a\tb"]
        for reason in bad:
            with self.subTest(reason=reason):
                r = self.rejected(reason=reason, rule=proposal.RULE_REASON)
                if len(reason.strip()) > 3:
                    self.assertNotIn(reason.strip(), everything(r))

    def test_good_reason_boundary(self):
        r = build_proposals([edit(reason="a" * MAX_REASON_CHARS), edit(reason="1 item; x: y, z!")], Reader({DOC: "x\n"}))
        self.assertEqual(len(r.documents), 1)
        self.assertEqual(r.rejected, ())

    def test_bad_symbols(self):
        for name in ["", "a,b", "a b", "1a", "a-b", "a.", ".a", "a..b", "caf\u00e9", "a\nb", "a`b", "x" * (MAX_SYMBOL_CHARS + 1), " a"]:
            with self.subTest(name=name):
                self.rejected(symbols=[name], rule=proposal.RULE_SYMBOL)

    def test_good_symbols(self):
        names = ["a", "_x", "A.b_c.D9", "x" * MAX_SYMBOL_CHARS]
        r = build_proposals([edit(symbols=names)], Reader({DOC: "x\n"}))
        self.assertEqual(len(r.documents), 1)

    def test_too_many_symbols(self):
        self.rejected(symbols=["s%d" % i for i in range(MAX_SYMBOLS + 1)], rule=proposal.RULE_TOO_MANY)
        r = build_proposals([edit(symbols=["s%d" % i for i in range(MAX_SYMBOLS)])], Reader({DOC: "x\n"}))
        self.assertEqual(len(r.documents), 1)

    def test_partial_rejection(self):
        good = edit(reason="Good change", symbols=["ok"])
        bad = edit(reason="bad`tick")
        r = build_proposals([bad, good], Reader({DOC: "x\n"}))
        (d,) = r.documents
        self.assertIn("- Good change", d.proposed)
        self.assertNotIn("bad", d.proposed)
        self.assertEqual(r.rejected, (RejectedEdit(DOC, proposal.RULE_REASON),))
        self.assertEqual(len(r.not_found), 1)
        self.assertEqual(r.skipped, ())
        self.assertNotEqual(d.proposed, d.original)

    def test_total_rejection_builds_no_change(self):
        reader = Reader({DOC: "x\n"})
        r = build_proposals([edit(reason="#h"), edit(reason="a<b")], reader)
        self.assertEqual(r.documents, ())
        self.assertEqual(r.skipped, (SkippedDocument(DOC, proposal.SKIP_ALL_REJECTED),))
        self.assertEqual(len(r.rejected), 2)
        self.assertTrue(all(n.detail.startswith("Not Found:") for n in r.not_found))

    def test_no_change_equals_original(self):
        for original in ("", "a", "a\n", "a\n\n"):
            (d,) = one(original, [edit()]).documents
            self.assertNotEqual(d.proposed, d.original)
        with self.assertRaises(ValueError):
            ProposedDocument(DOC, "same", "same", (1,))


class SecretAndOutputTests(unittest.TestCase):
    def test_secret_in_reason_symbol_and_invalid_target_not_echoed(self):
        cases = [
            [edit(reason="key " + FAKE_SECRET + "<")],
            [edit(reason="ok", symbols=[FAKE_SECRET + "-x"])],
            [edit(target="/" + FAKE_SECRET + ".md")],
            [edit(target="docs/../" + FAKE_SECRET + ".txt")],
        ]
        for edits in cases:
            with self.subTest(target=edits[0].target):
                r = build_proposals(edits, Reader({e.target: "x\n" for e in edits}))
                self.assertNotIn(FAKE_SECRET, everything(r))
                for item in r.not_found:
                    self.assertNotIn(FAKE_SECRET, "|".join(item.files))
                for s in r.skipped:
                    self.assertIn(s.path, (None, DOC))
                if not proposal._path_ok(edits[0].target):
                    self.assertEqual([s.path for s in r.skipped], [None])
                    self.assertEqual([n.files for n in r.not_found], [()])

    def test_accepted_edit_text_only_in_proposed(self):
        symbol = "Sym" + FAKE_SECRET[4:8]
        r = one("orig\n", [edit(reason="Marker reason", symbols=[symbol])])
        text = everything(r)
        self.assertNotIn("Marker", text)
        self.assertNotIn(symbol, text)
        self.assertNotIn("orig", text)

    def test_path_valid_secret_like_target_only_in_structured_fields(self):
        target = "docs/" + FAKE_SECRET + ".md"
        r = build_proposals([edit(target)], Reader({}))  # missing document
        self.assertEqual(r.skipped[0].path, target)
        self.assertEqual(r.not_found[0].files, (target,))
        self.assertNotIn(FAKE_SECRET, everything(r))
        r = build_proposals([edit(target, reason="bad`")], Reader({target: "x\n"}))
        self.assertEqual(r.rejected[0].target, target)
        self.assertNotIn(FAKE_SECRET, everything(r))
        r = build_proposals([edit(target)], Reader({target: "x\n"}))
        self.assertEqual(r.documents[0].path, target)
        self.assertNotIn(FAKE_SECRET, everything(r))
        self.assertNotIn("x\\n", repr(r.documents[0]))

    def test_repr_hides_texts(self):
        r = one("SECRETTEXT\n")
        d = r.documents[0]
        for shown in (repr(d), str(d), repr(r), str(r)):
            self.assertNotIn("SECRETTEXT", shown)
            self.assertNotIn(HEADING, shown)
            self.assertNotIn(DOC, shown)

    def test_sorting_with_none_paths(self):
        edits = [edit("/bad1.md"), edit("docs/z.md", reason="x`"), edit("docs/a.md"), edit("../bad2.md")]
        r = build_proposals(edits, Reader({"docs/a.md": None}))
        paths = [s.path for s in r.skipped]
        self.assertEqual(paths, sorted(paths, key=lambda p: (p is None, p or "")))
        self.assertEqual(paths[-2:], [None, None])
        rejected = [x.target for x in r.rejected]
        self.assertEqual(rejected, ["docs/z.md"])

    def test_module_performs_no_io(self):
        def forbidden(*a, **k):
            raise AssertionError("I/O attempted")

        reader = Reader({DOC: "x\n"})
        with mock.patch.object(builtins, "open", forbidden), mock.patch.object(builtins, "print", forbidden), \
                mock.patch("sys.stdout.write", forbidden), mock.patch("sys.stderr.write", forbidden):
            r = build_proposals([edit(), edit("/bad.md"), edit("docs/b.md")], reader)
        self.assertEqual(reader.calls, [DOC, "docs/b.md"])
        self.assertEqual(len(r.documents), 1)

    def test_imports_only_contracts_and_stdlib(self):
        source = Path(proposal.__file__).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("docsync"):
                self.assertEqual(node.module, "docsync.contracts")
            if isinstance(node, ast.Import):
                self.assertFalse(any(a.name.startswith("docsync") for a in node.names))
        self.assertFalse(hasattr(proposal, "output"))

    def test_result_types_validated(self):
        with self.assertRaises(ValueError):
            SkippedDocument(DOC, "free text")
        with self.assertRaises(ValueError):
            RejectedEdit(DOC, "free text")
        with self.assertRaises(ValueError):
            ProposedDocument("src/a.py", "a", "b", (1,))
        with self.assertRaises(ValueError):
            ProposedDocument(DOC, "a", "b", (0,))
        with self.assertRaises(TypeError):
            ProposalResult(documents=(1,))
        self.assertIsInstance(ProposalResult().not_found, tuple)
        self.assertIsInstance(NotFoundItem("s", "d"), NotFoundItem)


class IntegrationTests(unittest.TestCase):
    def validate(self, document, root):
        return validation.validate_content(
            {document.path: document.proposed}, root, {document.path: document.added_lines}
        )

    def test_unclosed_fence_fails_validation(self):
        with tempfile.TemporaryDirectory() as root:
            (d,) = one("# T\n\n```\ncode\n").documents
            report = self.validate(d, root)
            self.assertFalse(report.passed)
            self.assertTrue(any(
                r.status is CheckStatus.FAILED and r.rule == validation.RULE_UNCLOSED_FENCE for r in report.results))

    def test_clean_document_passes_without_ambiguity(self):
        with tempfile.TemporaryDirectory() as root:
            for original in ("# T\n\ntext\n", "# T\n\ntext", ""):
                with self.subTest(original=original):
                    (d,) = one(original, [edit(symbols=["a"])]).documents
                    report = self.validate(d, root)
                    self.assertTrue(report.passed, report.results)
                    self.assertFalse(any(
                        r.rule == validation.RULE_ADDED_LINES_AMBIGUOUS for r in report.results))

    def test_link_in_reason_is_not_insertable(self):
        # brackets and parentheses are refused, so a markdown link can never be generated
        r = build_proposals([edit(reason="see [x](missing.md)")], Reader({DOC: "x\n"}))
        self.assertEqual(r.documents, ())

    def test_preexisting_broken_link_is_checked_only_on_added_lines(self):
        with tempfile.TemporaryDirectory() as root:
            (d,) = one("see [gone](nope.md)\n").documents
            report = self.validate(d, root)
            links = [r for r in report.results if r.check == "relative_links"]
            self.assertTrue(links)
            self.assertTrue(all(r.status is CheckStatus.PASSED for r in links))

    def test_document_change_accepted_by_render_patch(self):
        r = build_proposals(
            [edit("docs/b.md", symbols=["f"]), edit("README.md")],
            Reader({"docs/b.md": "b", "README.md": "# R\r\n\r\n"}),
        )
        changes = [DocumentChange(d.path, d.original, d.proposed) for d in r.documents]
        rendered = render_patch(changes, redact)
        self.assertEqual(rendered.withheld, ())
        self.assertIn("Proposed documentation update", rendered.text)
        self.assertEqual({h.file for h in rendered.hunks}, {"README.md", "docs/b.md"})


if __name__ == "__main__":
    unittest.main()
