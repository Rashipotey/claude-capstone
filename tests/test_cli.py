"""T09 tests: argument handling, --target validation, scope resolution, exit codes.

Local fixtures only (temporary directories); no Git, no network, no stdin.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docsync import cli, mapping
from docsync.contracts import (
    ChangedFile,
    ExitCode,
    EXPECTED_ERRORS,
    FileCategory,
    NoSuitableTargetError,
    UnresolvedCandidatesError,
    UsageError,
)
from docsync.redact import redact

SRC = FileCategory.SOURCE
FAKE = "AKIA" + "ABCDEFGHIJKLMNOP"  # fake AWS-style id, built so no literal is stored


def cf(path, category=SRC):
    return ChangedFile(path=path, status="M", added=1, deleted=0, category=category)


def outcome_for(paths, docs, categories=None):
    files = [cf(p, (categories or {}).get(p, SRC)) for p in paths]
    return mapping.map_changes(files, docs)


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "repo"
        self.root.mkdir()
        self.outside = Path(self._tmp.name).resolve() / "outside"
        self.outside.mkdir()

    def make_docs(self, *names):
        for name in names:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# doc\n", encoding="utf-8")

    def resolve(self, outcome, target=None):
        return cli.resolve_scope(outcome, self.root, target, redactor=redact)

    def snapshot(self):
        return sorted(str(p.relative_to(self._tmp.name)) for p in Path(self._tmp.name).rglob("*"))


class ParseArgsTests(unittest.TestCase):
    def parse(self, argv):
        return cli.parse_args(argv, redactor=redact)

    def test_no_arguments(self):
        self.assertEqual(self.parse([]), cli.ParsedArgs(None, None))

    def test_path_and_target_forms(self):
        self.assertEqual(self.parse(["repo"]).repo_path, "repo")
        a = self.parse(["repo", "--target", "docs/a.md"])
        self.assertEqual((a.repo_path, a.target), ("repo", "docs/a.md"))
        b = self.parse(["--target=README.md", "repo"])
        self.assertEqual((b.repo_path, b.target), ("repo", "README.md"))

    def test_double_dash_allows_a_dash_path(self):
        self.assertEqual(self.parse(["--", "-weird"]).repo_path, "-weird")

    def test_force_and_unknown_options_are_usage_errors_exit_2(self):
        for argv in (["--force"], ["repo", "--force"], ["--bogus"], ["-x"], ["--target"],
                     ["--target="], ["--target", "  "], ["--target", "a", "--target", "b"],
                     ["a", "b"], [""], ["--targets", "x"], ["--force=1"]):
            with self.assertRaises(UsageError, msg=argv) as cm:
                self.parse(argv)
            self.assertEqual(cm.exception.exit_code, 2)
            self.assertEqual(cli.exit_code_for(cm.exception), 2)

    def test_parse_or_code(self):
        args, code, msg = cli.parse_or_code(["--force"], redactor=redact)
        self.assertIsNone(args)
        self.assertEqual(code, 2)
        self.assertIn("unknown option", msg)
        self.assertEqual(cli.parse_or_code([], redactor=redact)[1], 0)

    def test_option_text_is_redacted_and_bounded(self):
        with self.assertRaises(UsageError) as cm:
            self.parse(["--token=" + FAKE + "x" * 500])
        self.assertNotIn(FAKE, str(cm.exception))
        self.assertLess(len(str(cm.exception)), 400)

    def test_bad_types(self):
        with self.assertRaises(TypeError):
            self.parse("repo")
        with self.assertRaises(TypeError):
            self.parse([1])
        with self.assertRaises(TypeError):
            cli.parse_args([], redactor=None)

    def test_no_code_path_reads_stdin(self):
        class Boom:
            def __getattr__(self, name):
                raise AssertionError("stdin was touched")

        with mock.patch.object(sys, "stdin", Boom()), mock.patch("builtins.input", side_effect=AssertionError):
            self.parse(["repo", "--target", "README.md"])
            with self.assertRaises(UsageError):
                self.parse(["--force"])
        import ast
        tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, {"input", "stdin"})
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"stdin", "readline", "readlines"})


class NoCandidateTests(Fixture):
    def test_zero_candidates_exit_7_without_target(self):
        out = outcome_for(["a.py"], [])
        with self.assertRaises(NoSuitableTargetError) as cm:
            self.resolve(out)
        self.assertEqual(cm.exception.exit_code, 7)
        self.assertIn(cli.NO_SUITABLE_TARGET_MESSAGE, str(cm.exception))

    def test_zero_candidates_exit_7_with_target_and_nothing_written(self):
        before = self.snapshot()
        out = outcome_for(["a.py"], [])
        with self.assertRaises(NoSuitableTargetError) as cm:
            self.resolve(out, "README.md")
        self.assertEqual(cli.exit_code_for(cm.exception), 7)
        self.assertEqual(self.snapshot(), before)

    def test_only_skipped_changes_have_no_candidate(self):
        out = outcome_for(["README.md"], ["README.md"], {"README.md": FileCategory.DOCUMENTATION})
        with self.assertRaises(NoSuitableTargetError):
            self.resolve(out)

    def test_empty_change_set(self):
        with self.assertRaises(NoSuitableTargetError):
            self.resolve(outcome_for([], ["README.md"]))


class WithoutTargetTests(Fixture):
    def test_two_distinct_docs_listed_exit_8(self):
        self.make_docs("README.md", "docs/a.md")
        before = self.snapshot()
        out = outcome_for(["a.py", "b.py"], ["README.md", "docs/a.md"])
        with self.assertRaises(UnresolvedCandidatesError) as cm:
            self.resolve(out)
        text = str(cm.exception)
        self.assertEqual(cm.exception.exit_code, 8)
        self.assertIn("docs/a.md", text)
        self.assertIn("README.md", text)
        self.assertIn("'a.py'", text)
        self.assertIn("'b.py'", text)
        self.assertEqual(self.snapshot(), before)

    def test_one_mapped_one_unmapped_exit_8(self):
        out = outcome_for(["a.py", "b.py"], ["docs/a.md"])
        with self.assertRaises(UnresolvedCandidatesError) as cm:
            self.resolve(out)
        self.assertEqual(cli.exit_code_for(cm.exception), 8)
        self.assertIn("no candidate: 'b.py'", str(cm.exception))

    def test_listing_redacts_user_derived_paths(self):
        out = outcome_for([FAKE + ".py", "b.py"], ["README.md", "docs/b.md"])
        with self.assertRaises(UnresolvedCandidatesError) as cm:
            self.resolve(out)
        self.assertNotIn(FAKE, str(cm.exception))
        out = outcome_for(["p.py"], ["docs/P.md", "docs/p.md"])
        out = mapping.MappingOutcome(results=out.results, ambiguous=(("x/" + FAKE + ".py", ("docs/P.md", "docs/p.md")),))
        with self.assertRaises(UnresolvedCandidatesError) as cm:
            self.resolve(out)
        self.assertNotIn(FAKE, str(cm.exception))

    def test_all_changes_to_one_doc_proceed_with_everything_in_scope(self):
        self.make_docs("README.md")
        out = outcome_for(["b.py", "a.py"], ["README.md"])
        scope = self.resolve(out)
        self.assertIsNone(scope.target)
        self.assertEqual(scope.in_scope, ("a.py", "b.py"))
        self.assertEqual(scope.not_addressed, ())

    def test_skipped_changes_do_not_block(self):
        out = outcome_for(["a.py", "tests/test_a.py"], ["README.md"], {"tests/test_a.py": FileCategory.TEST})
        scope = self.resolve(out)
        self.assertEqual(scope.in_scope, ("a.py",))
        self.assertEqual([r.source_path for r in scope.skipped], ["tests/test_a.py"])


class AmbiguityTests(Fixture):
    """Regression: ambiguity is checked before has_candidates and blocks with or without --target."""

    DOCS = ["docs/P.md", "docs/p.md"]

    def test_only_ambiguous_run_is_exit_8_not_7(self):
        out = outcome_for(["p.py"], self.DOCS)
        self.assertTrue(out.has_ambiguity)
        self.assertFalse(out.has_candidates)  # the trap: has_candidates alone would say exit 7
        with self.assertRaises(UnresolvedCandidatesError) as cm:
            self.resolve(out)
        self.assertEqual(cm.exception.exit_code, 8)
        self.assertEqual(cli.exit_code_for(cm.exception), 8)
        self.assertNotEqual(cli.exit_code_for(cm.exception), 7)
        self.assertIn("docs/P.md", str(cm.exception))
        self.assertIn("docs/p.md", str(cm.exception))

    def test_only_ambiguous_run_with_target_is_exit_8(self):
        out = outcome_for(["p.py"], self.DOCS)
        for target in ("docs/p.md", "README.md", "../x.md"):
            with self.assertRaises(UnresolvedCandidatesError, msg=target) as cm:
                self.resolve(out, target)
            self.assertEqual(cm.exception.exit_code, 8)

    def test_ambiguity_blocks_even_when_other_changes_map_to_one_doc(self):
        self.make_docs("README.md")
        out = outcome_for(["p.py", "other.py"], ["README.md", "docs/P.md", "docs/p.md"])
        self.assertTrue(out.has_candidates)
        self.assertEqual(out.candidates, ("README.md",))
        for target in (None, "README.md"):
            with self.assertRaises(UnresolvedCandidatesError, msg=target) as cm:
                self.resolve(out, target)
            self.assertEqual(cm.exception.exit_code, 8)

    def test_ambiguity_message_is_redacted(self):
        out = outcome_for(["p.py"], self.DOCS)
        redactor = mock.Mock(side_effect=lambda t: t)
        with self.assertRaises(UnresolvedCandidatesError):
            cli.resolve_scope(out, self.root, None, redactor=redactor)
        self.assertTrue(redactor.called)


class WithTargetTests(Fixture):
    def setUp(self):
        super().setUp()
        self.make_docs("README.md", "docs/a.md")

    def test_valid_target_scopes_and_reports_the_rest(self):
        out = outcome_for(["a.py", "b.py", "c.py"], ["README.md", "docs/a.md"])
        scope = self.resolve(out, "docs/a.md")
        self.assertEqual(scope.target, "docs/a.md")
        self.assertEqual(scope.in_scope, ("a.py",))
        self.assertEqual(scope.not_addressed, (("b.py", "README.md"), ("c.py", "README.md")))
        analyzed = {r.source_path for r in out.results}
        placed = set(scope.in_scope) | {p for p, _ in scope.not_addressed}
        self.assertEqual(placed, analyzed)  # none dropped silently
        self.assertFalse(set(scope.in_scope) & {p for p, _ in scope.not_addressed})

    def test_target_readme_with_backslash_docs_form(self):
        out = outcome_for(["a.py", "b.py"], ["README.md", "docs/a.md"])
        self.assertEqual(self.resolve(out, "docs\\a.md").target, "docs/a.md")

    def test_target_with_unmapped_change_is_exit_8(self):
        before = self.snapshot()
        out = outcome_for(["a.py", "b.py"], ["docs/a.md"])
        with self.assertRaises(UnresolvedCandidatesError) as cm:
            self.resolve(out, "docs/a.md")
        self.assertEqual(cm.exception.exit_code, 8)
        self.assertIn("no candidate: 'b.py'", str(cm.exception))
        self.assertEqual(self.snapshot(), before)

    def test_single_doc_with_matching_target_proceeds(self):
        out = outcome_for(["a.py"], ["docs/a.md"])
        self.assertEqual(self.resolve(out, "docs/a.md").in_scope, ("a.py",))

    def test_tool_never_selects_a_target(self):
        out = outcome_for(["a.py", "b.py"], ["README.md", "docs/a.md"])
        with self.assertRaises(UnresolvedCandidatesError):
            self.resolve(out)


class InvalidTargetTests(Fixture):
    def setUp(self):
        super().setUp()
        self.make_docs("README.md", "docs/a.md", "docs/notes.txt", "other.md")
        self.out = outcome_for(["a.py", "b.py"], ["README.md", "docs/a.md"])

    def assert_invalid(self, target, fragment=None):
        before = self.snapshot()
        with self.assertRaises(UsageError, msg=target) as cm:
            self.resolve(self.out, target)
        self.assertEqual(cm.exception.exit_code, 2)
        self.assertEqual(cli.exit_code_for(cm.exception), 2)
        text = str(cm.exception)
        self.assertIn("README.md", text)  # valid candidates are listed
        self.assertIn("docs/a.md", text)
        if fragment:
            self.assertIn(fragment, text)
        self.assertEqual(self.snapshot(), before)

    def test_non_candidate(self):
        self.assert_invalid("docs/missing.md", "not a documentation candidate")
        self.assert_invalid("other.md", "not README.md or a Markdown")
        self.assert_invalid("./README.md")
        self.assert_invalid("readme.md")

    def test_absolute_paths(self):
        self.assert_invalid(str(self.root / "README.md"), "absolute")
        self.assert_invalid("/etc/passwd.md", "absolute")
        self.assert_invalid("C:\\x\\README.md", "absolute")
        self.assert_invalid("\\\\server\\share\\a.md", "absolute")

    def test_dotdot_segments(self):
        self.assert_invalid("docs/../README.md", "'..'")
        self.assert_invalid("../repo/README.md", "'..'")
        self.assert_invalid("docs\\..\\README.md", "'..'")

    def test_non_markdown(self):
        self.assert_invalid("docs/notes.txt", "not README.md or a Markdown")
        self.assert_invalid("src/a.py", "not README.md or a Markdown")

    def test_empty_and_nul(self):
        self.assert_invalid("", "empty")
        self.assert_invalid("docs/a.md\x00.txt", "null")

    def test_nested_docs_is_not_a_candidate(self):
        self.make_docs("docs/sub/b.md")
        self.assert_invalid("docs/sub/b.md")

    def test_candidate_missing_on_disk(self):
        (self.root / "docs" / "a.md").unlink()
        self.assert_invalid("docs/a.md", "not an existing file")

    def test_target_text_is_redacted(self):
        with self.assertRaises(UsageError) as cm:
            self.resolve(self.out, "docs/" + FAKE + ".md")
        self.assertNotIn(FAKE, str(cm.exception))

    def test_invalid_target_validated_before_unmapped_check(self):
        out = outcome_for(["a.py", "b.py"], ["docs/a.md"])  # b.py unmapped
        with self.assertRaises(UsageError):
            self.resolve(out, "docs/zzz.md")


def _try_junction(link, target):
    """Create a Windows directory junction without privileges; return True on success."""
    if os.name != "nt":
        return False
    try:
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              capture_output=True, timeout=30, shell=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and os.path.isdir(link)


class LinkEscapeTests(Fixture):
    def test_junction_docs_directory_is_rejected(self):
        (self.outside / "a.md").write_text("# outside\n", encoding="utf-8")
        if not _try_junction(self.root / "docs", self.outside):
            self.skipTest("directory junction creation unavailable (junctions are Windows-only, or creation failed on this machine)")
        self.addCleanup(lambda: os.rmdir(self.root / "docs"))  # removes only the junction
        # discover_candidates does not detect a junction (T08 note); target validation must.
        self.assertIn("docs/a.md", mapping.discover_candidates(self.root))
        with self.assertRaises(UsageError) as cm:
            cli.validate_target("docs/a.md", self.root, ("docs/a.md",), redactor=redact)
        self.assertEqual(cm.exception.exit_code, 2)
        self.assertIn("outside the repository", str(cm.exception))
        self.assertTrue((self.outside / "a.md").exists())

    def test_junction_inside_the_repository_is_still_rejected(self):
        (self.root / "real").mkdir()
        (self.root / "real" / "a.md").write_text("# x\n", encoding="utf-8")
        if not _try_junction(self.root / "docs", self.root / "real"):
            self.skipTest("directory junction creation unavailable (junctions are Windows-only, or creation failed on this machine)")
        self.addCleanup(lambda: os.rmdir(self.root / "docs"))
        with self.assertRaises(UsageError) as cm:
            cli.validate_target("docs/a.md", self.root, ("docs/a.md",), redactor=redact)
        self.assertIn("link", str(cm.exception))

    def test_plain_file_is_accepted(self):
        self.make_docs("docs/a.md")
        self.assertEqual(cli.validate_target("docs/a.md", self.root, ("docs/a.md",), redactor=redact),
                         "docs/a.md")


class ExitCodeTests(unittest.TestCase):
    def test_each_expected_error_keeps_its_own_distinct_code(self):
        codes = [cli.exit_code_for(cls("cli", "x")) for cls in EXPECTED_ERRORS]
        self.assertEqual(len(set(codes)), len(codes))
        self.assertNotIn(12, codes)
        self.assertEqual(cli.exit_code_for(UsageError("cli", "x")), 2)
        self.assertEqual(cli.exit_code_for(NoSuitableTargetError("cli", "x")), 7)
        self.assertEqual(cli.exit_code_for(UnresolvedCandidatesError("cli", "x")), 8)

    def test_untyped_exception_is_12(self):
        self.assertEqual(cli.exit_code_for(RuntimeError("boom")), int(ExitCode.UNEXPECTED))

    def test_t09_outcomes_map_to_architecture_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                (outcome_for(["a.py"], []), None, 7),
                (outcome_for(["a.py"], []), "README.md", 7),
                (outcome_for(["p.py"], ["docs/P.md", "docs/p.md"]), None, 8),
                (outcome_for(["a.py", "b.py"], ["docs/a.md"]), None, 8),
                (outcome_for(["a.py", "b.py"], ["README.md", "docs/a.md"]), "docs/x.md", 2),
            ]
            for out, target, expected in cases:
                with self.assertRaises(Exception) as cm:
                    cli.resolve_scope(out, root, target, redactor=redact)
                self.assertEqual(cli.exit_code_for(cm.exception), expected)


if __name__ == "__main__":
    unittest.main()
