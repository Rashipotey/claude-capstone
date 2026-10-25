"""T15 tests: the orchestrator ``docsync.cli.main`` (sequencing, exit codes, all-or-nothing).

Every test runs in a temporary working directory (the repository's own ``output/`` is never
touched; the original working directory is restored) against small temporary Git repositories
built by ``tests.helpers.gitrepo``. No network. Secret values are fake and built at run time.
"""

import contextlib
import dataclasses
import errno
import hashlib
import inspect
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docsync import analysis, cli, generation, gitadapter, mapping, output, proposal, report, sizegate, validation
from docsync import input as input_stage
from docsync.contracts import CheckResult, CheckStatus, ExitCode, ValidationReport
from tests.helpers.gitrepo import TempGitRepo, git_available

FAKE = "FAKE" + "KEYVALUE1234567890"
SECRET_LINE = 'api_key = "%s"\n' % FAKE
EXC_SECRET = "EXC" + "SECRETVALUE9876543210"

BASE = {"README.md": "# Demo\n", "pkg.py": "def f():\n    return 1\n"}
CHANGED = {"pkg.py": "def f():\n    return 2\n"}


class _Broken:
    """A standard output that fails on every write (closed pipe)."""

    def write(self, text):
        raise OSError(errno.EPIPE, "broken pipe")

    def flush(self):
        raise OSError(errno.EPIPE, "broken pipe")


class _Narrow:
    """A standard output with a narrow encoding: a write that cannot be encoded raises
    UnicodeEncodeError before anything is stored (like a text stream). ``fail_all`` makes
    every write fail, to model a retry that fails too."""

    def __init__(self, encoding="ascii", fail_all=False):
        self.encoding = encoding
        self.fail_all = fail_all
        self.writes = []

    def write(self, text):
        if self.fail_all:
            raise UnicodeEncodeError(self.encoding, text, 0, 1, "cannot encode")
        text.encode(self.encoding)
        self.writes.append(text)

    def flush(self):
        pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(git_available(), "git is not available")
class Base(unittest.TestCase):
    def setUp(self):
        # realpath: on Windows the temp directory may be an 8.3 short name, which would make
        # the token path differ from the default path in every run (the re-render case).
        self.work = os.path.realpath(tempfile.mkdtemp(prefix="docsync_work_"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        origin = os.getcwd()
        self.addCleanup(os.chdir, origin)  # runs before the rmtree above
        os.chdir(self.work)
        self.patch_path = Path(self.work) / "output" / "docsync.patch"

    # -- fixtures ---------------------------------------------------------------------
    def repo(self, files=None, changes=None, *, commit=True):
        r = TempGitRepo(BASE if files is None else files, commit=commit)
        self.addCleanup(r.cleanup)
        for rel, content in (CHANGED if changes is None else changes).items():
            r.write(rel, content)
        return r

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def run_with_stdout(self, argv, stdout):
        err = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, err.getvalue()

    def spy(self, obj, name, label=None, calls=None, stack=None):
        original = getattr(obj, name)
        record = calls if calls is not None else self.calls

        def wrapper(*args, **kwargs):
            record.append((label or name, args, kwargs))
            return original(*args, **kwargs)

        patcher = mock.patch.object(obj, name, wrapper)
        if stack is not None:
            stack.enter_context(patcher)
        else:
            patcher.start()
            self.addCleanup(patcher.stop)
        return record

    def spy_all(self):
        self.calls = []
        self.spy(output, "check_no_existing_patch")
        self.spy(gitadapter.GitAdapter, "run", "git")
        self.spy(sizegate, "check_size")
        self.spy(analysis, "analyze")
        self.spy(mapping, "discover_candidates")
        self.spy(mapping, "map_changes")
        self.spy(generation, "generate")
        self.spy(proposal, "build_proposals")
        self.spy(output, "render_patch")
        self.spy(validation, "validate_content")
        self.spy(output, "approve_patch")
        self.spy(report, "render_report")
        self.spy(output, "publish_patch")
        self.spy(output, "rollback_patch")
        self.spy(report, "emit_report")

    def names(self):
        out = []
        for label, _a, _k in self.calls:
            if label == "git" and out and out[-1] == "git":
                continue
            out.append(label)
        return out

    def count(self, label):
        return sum(1 for c in self.calls if c[0] == label)

    def assert_no_patch(self):
        self.assertFalse(os.path.lexists(self.patch_path))

    def write_patch(self, text="existing\n"):
        self.patch_path.parent.mkdir(parents=True, exist_ok=True)
        self.patch_path.write_text(text, encoding="utf-8")
        return sha(self.patch_path)


# ------------------------------------------------------------------------ happy path
class HappyPathTests(Base):
    def test_success_writes_patch_reports_and_exits_0(self):
        r = self.repo()
        code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 0, err)
        patch = self.patch_path.read_text(encoding="utf-8")
        self.assertIn("## Proposed documentation update", patch)
        self.assertIn("README.md", patch)
        self.assertIn("Outcome: OK (exit 0)", out)
        self.assertIn("Not Found: consistency is not computed in v1", out)
        self.assertIn("Planned patch:", out)
        self.assertEqual(err, "")

    def test_consistency_item_changes_neither_validation_nor_exit_code(self):
        r = self.repo()
        self.spy_all()
        code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 0)
        report_input = next(c for c in self.calls if c[0] == "render_report")[1][0]
        self.assertTrue(report_input.validation.passed)
        self.assertEqual(sum(1 for n in report_input.validation.not_found if n.subject == "consistency"), 1)

    def test_success_call_order(self):
        r = self.repo()
        self.spy_all()
        code, _out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), [
            "check_no_existing_patch", "git", "check_size", "analyze", "discover_candidates",
            "map_changes", "generate", "build_proposals", "render_patch", "validate_content",
            "approve_patch", "render_report", "publish_patch", "emit_report",
        ])
        self.assertEqual(self.count("render_report"), 1)
        self.assertEqual(self.count("rollback_patch"), 0)

    def test_build_proposals_gets_the_working_tree_reader_and_validation_gets_complete_text(self):
        r = self.repo()
        self.spy_all()
        self.assertEqual(self.run_main([str(r.path)])[0], 0)
        _l, args, _k = next(c for c in self.calls if c[0] == "build_proposals")
        self.assertEqual(args[1]("README.md"), "# Demo\n")  # the injected reader reads the working tree
        self.assertIsNone(args[1]("../outside.md"))
        _l, vargs, _k = next(c for c in self.calls if c[0] == "validate_content")
        content, root, added = vargs
        self.assertEqual(list(content), ["README.md"])
        self.assertTrue(content["README.md"].startswith("# Demo\n\n## Proposed documentation update\n"))
        self.assertEqual(os.path.normcase(root), os.path.normcase(os.path.realpath(r.path)))
        self.assertEqual(added["README.md"], (2, 3, 4, 5, 6))

    def test_out_of_scope_changes_under_target_exit_0_and_are_reported(self):
        files = {"README.md": "# Demo\n", "docs/pkg.md": "# Pkg\n",
                 "pkg.py": "def f():\n    return 1\n", "other.py": "def g():\n    return 1\n"}
        r = self.repo(files, {"pkg.py": "def f():\n    return 2\n", "other.py": "def g():\n    return 2\n"})
        code, out, err = self.run_main([str(r.path), "--target", "docs/pkg.md"])
        self.assertEqual(code, 0, err)
        self.assertIn("Not addressed in this run (1):", out)
        self.assertIn("other.py -> README.md", out)
        patch = self.patch_path.read_text(encoding="utf-8")
        self.assertIn("docs/pkg.md", patch)
        self.assertNotIn("README.md", patch)

    def test_not_found_for_one_in_scope_change_does_not_block(self):
        files = dict(BASE, **{"app.js": "var a = 1;\n"})
        r = self.repo(files, {"pkg.py": "def f():\n    return 2\n", "app.js": "var a = 2;\n"})
        code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 0)
        self.assertIn("Not Found: no changed symbol names could be extracted", out)

    def test_only_not_found_for_in_scope_changes_gives_empty_output_exit_9(self):
        r = self.repo({"README.md": "# Demo\n", "app.js": "var a = 1;\n"}, {"app.js": "var a = 2;\n"})
        self.spy_all()
        code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 9)
        self.assertIn("Not Found: no changed symbol names could be extracted", out)
        self.assertEqual(self.count("publish_patch"), 0)
        self.assert_no_patch()

    def test_untracked_files_are_listed_and_not_analyzed(self):
        r = self.repo()
        r.write("new_untracked.py", "x = 1\n")
        code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 0)
        self.assertIn("new_untracked.py: untracked file, not analyzed", out)
        self.assertNotIn("new_untracked", self.patch_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------- stop paths
class StopPathTests(Base):
    def test_withheld_hunk_exit_10_lists_file_and_line_never_the_value(self):
        r = self.repo({"README.md": "# Demo\n\n" + SECRET_LINE, "pkg.py": BASE["pkg.py"]})
        self.spy_all()
        code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 10)
        self.assertEqual(self.count("validate_content"), 0)
        self.assertEqual(self.count("publish_patch"), 0)
        self.assertEqual(self.count("approve_patch"), 0)
        self.assertEqual(self.count("render_report"), 1)
        self.assertEqual(self.count("emit_report"), 1)
        self.assertIs(next(c for c in self.calls if c[0] == "render_report")[1][0].outcome, ExitCode.WITHHELD_HUNK)
        self.assertIn("README.md line 3", out)
        self.assertNotIn(FAKE, out + err)
        self.assert_no_patch()

    def test_failed_validation_exit_9_validates_but_does_not_publish(self):
        r = self.repo({"README.md": "```\nunclosed\n", "pkg.py": BASE["pkg.py"]})
        self.spy_all()
        code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 9)
        self.assertEqual(self.count("validate_content"), 1)
        self.assertEqual(self.count("publish_patch"), 0)
        self.assertEqual(self.count("render_report"), 1)
        self.assertIn("unclosed-code-fence", out)
        self.assertIn("README.md", out)
        self.assert_no_patch()

    def test_not_checked_result_exit_9(self):
        r = self.repo()
        self.spy_all()
        not_checked = ValidationReport(results=(
            CheckResult("markdown_syntax", CheckStatus.NOT_CHECKED, rule="check-not-performed", file="README.md"),))
        with mock.patch.object(validation, "validate_content", return_value=not_checked):
            code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 9)
        self.assertEqual(self.count("publish_patch"), 0)
        self.assertEqual(self.count("render_report"), 1)
        self.assertIn("NOT CHECKED", out)
        self.assert_no_patch()

    def test_stop_path_render_failure_prints_fallback_and_keeps_code(self):
        r = self.repo({"README.md": "```\nunclosed\n", "pkg.py": BASE["pkg.py"]})
        with mock.patch.object(report, "render_report", side_effect=RuntimeError(EXC_SECRET)):
            code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 9)
        self.assertEqual(out, "Run stopped: VALIDATION_FAILED\n")
        self.assertNotIn(EXC_SECRET, out + err)
        self.assert_no_patch()

    def test_stop_path_emit_failure_keeps_code(self):
        r = self.repo({"README.md": "```\nunclosed\n", "pkg.py": BASE["pkg.py"]})
        code, err = self.run_with_stdout([str(r.path)], _Broken())
        self.assertEqual(code, 9)
        self.assert_no_patch()

    def test_stop_path_unicode_error_on_emit_prints_fallback(self):
        r = self.repo({"README.md": "```\nunclosed\n", "pkg.py": BASE["pkg.py"]})
        printed = []

        def emit(text):
            printed.append(text)
            if len(printed) == 1:
                raise UnicodeEncodeError("ascii", "x", 0, 1, "cannot encode")

        with mock.patch.object(report, "emit_report", emit):
            code, _out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 9)
        self.assertEqual(printed[1], "Run stopped: VALIDATION_FAILED\n")
        self.assert_no_patch()

    def test_existing_patch_exit_11_before_any_git_call_even_with_report_failures(self):
        r = self.repo()
        digest = self.write_patch()
        self.spy_all()
        code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 11)
        self.assertEqual(self.count("git"), 0)
        self.assertEqual(self.names(), ["check_no_existing_patch", "render_report", "emit_report"])
        self.assertIn("output/docsync.patch", out)
        self.assertEqual(sha(self.patch_path), digest)
        with mock.patch.object(report, "render_report", side_effect=RuntimeError(EXC_SECRET)):
            code, out, err = self.run_main([str(r.path)])
        self.assertEqual((code, out), (11, "Run stopped: PATCH_WRITE\n"))
        code, err = self.run_with_stdout([str(r.path)], _Broken())
        self.assertEqual(code, 11)
        self.assertEqual(sha(self.patch_path), digest)

    def test_dangling_symlink_counts_as_existing_patch(self):
        r = self.repo()
        self.patch_path.parent.mkdir(parents=True)
        try:
            os.symlink(os.path.join(self.work, "nowhere"), self.patch_path)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available")
        code, _out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 11)
        self.assertTrue(os.path.islink(self.patch_path))

    def test_content_filter_exit_3_no_diff_call(self):
        r = self.repo()
        r.git("config", "filter.demo.clean", "cat")
        self.spy_all()
        code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 3)
        diff_vectors = [list(gitadapter.TEMPLATES[n]) for n in ("diff-raw", "diff-numstat", "diff-text")]
        for label, args, _k in self.calls:
            if label == "git":
                self.assertNotIn(list(args[1]), diff_vectors)
        self.assertIn("a content filter is defined", out)
        self.assertEqual(self.count("check_size"), 0)
        self.assert_no_patch()

    def test_unverified_preflight_exit_3_no_diff_call(self):
        r = self.repo()
        self.spy_all()
        error = gitadapter.PreflightUnverifiedError("x", check="command failed or timed out")
        with mock.patch.object(gitadapter.GitAdapter, "preflight", side_effect=error):
            code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 3)
        self.assertIn("content-filter protection could not be verified", out)
        self.assertEqual(self.count("check_size"), 0)
        self.assert_no_patch()

    def test_report_names_failed_stage_and_completed_units(self):
        r = self.repo({"README.md": "```\nunclosed\n", "pkg.py": BASE["pkg.py"]})
        code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 9)
        self.assertIn("Stage: validation", out)
        self.assertIn("completed: cli, precheck, input, gitadapter, sizegate, analysis, mapping, scope, "
                      "generation, proposal, redact", out)


# ------------------------------------------------------------ exit-code table
class ExitCodeTableTests(Base):
    def fixture(self, code):
        """Return (argv_tail_after_repo, repo, patches) for the expected outcome ``code``."""
        if code == 2:
            return ["--target", "docs/none.md"], self.repo(), None
        if code == 3:
            return None, None, None  # a missing repository path
        if code == 4:
            return [], self.repo(changes={}), None
        if code == 5:
            return [], self.repo(dict(BASE, **{"b.py": "x = 1\n"}), {"pkg.py": "def f():\n    return 2\n", "b.py": "x = 2\n"}), \
                mock.patch.object(sizegate, "MAX_FILES", 1)
        if code == 6:
            return [], self.repo({"README.md": "# Demo\n", "data.bin": b"\x00\x01"}, {"data.bin": b"\x00\x02"}), None
        if code == 7:
            return [], self.repo({"pkg.py": BASE["pkg.py"]}), None
        if code == 8:
            files = {"README.md": "# Demo\n", "docs/pkg.md": "# Pkg\n",
                     "pkg.py": "def f():\n    return 1\n", "other.py": "def g():\n    return 1\n"}
            return [], self.repo(files, {"pkg.py": "def f():\n    return 2\n", "other.py": "def g():\n    return 2\n"}), None
        if code == 9:
            return [], self.repo({"README.md": "```\nx\n", "pkg.py": BASE["pkg.py"]}), None
        if code == 10:
            return [], self.repo({"README.md": "# Demo\n\n" + SECRET_LINE, "pkg.py": BASE["pkg.py"]}), None
        if code == 11:
            self.write_patch()
            return [], self.repo(), None
        raise AssertionError(code)

    def test_every_expected_outcome_keeps_its_designated_code(self):
        seen = []
        for expected in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
            with self.subTest(code=expected):
                shutil.rmtree(os.path.join(self.work, "output"), ignore_errors=True)
                tail, repo, patcher = self.fixture(expected)
                argv = ([os.path.join(self.work, "does-not-exist")] if repo is None else [str(repo.path)]) + (tail or [])
                self.calls = []
                with contextlib.ExitStack() as stack:
                    for owner, name in ((report, "render_report"), (output, "publish_patch"),
                                        (output, "rollback_patch")):
                        self.spy(owner, name, stack=stack)
                    if patcher is not None:
                        stack.enter_context(patcher)
                    code, out, _err = self.run_main(argv)
                self.assertEqual(code, expected, out)
                self.assertNotEqual(code, 12)
                self.assertEqual(self.count("render_report"), 1)
                shown = next(c for c in self.calls if c[0] == "render_report")[1][0]
                self.assertIs(shown.outcome, ExitCode(expected))
                self.assertEqual(self.count("publish_patch"), 0)
                if expected != 11:
                    self.assert_no_patch()
                seen.append(code)
        self.assertEqual(len(set(seen)), len(seen))

    def test_usage_errors_exit_2(self):
        for argv in (["--force"], ["a", "b"], ["--target"], ["--executable=git"], ["--environment", "x"]):
            with self.subTest(argv=argv):
                self.spy_all()
                code, out, _err = self.run_main(argv)
                self.assertEqual(code, 2)
                self.assertEqual(self.count("git"), 0)
                self.assertIn("exit 2", out)
        self.assertEqual(list(inspect.signature(cli.main).parameters), ["argv"])

    def test_every_changed_file_skipped_is_exit_4(self):
        r = self.repo({"README.md": "# Demo\n", "tests/test_a.py": "x = 1\n"}, {"tests/test_a.py": "x = 2\n"})
        code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 4)
        self.assertIn("tests/test_a.py", out)
        self.assert_no_patch()

    def test_input_error_names_stage(self):
        code, out, _err = self.run_main([os.path.join(self.work, "missing")])
        self.assertEqual(code, 3)
        self.assertIn("Stage: input", out)


# ----------------------------------------------------------- unexpected failures
class UnexpectedFailureTests(Base):
    def test_untyped_exception_in_each_stage_exits_12_names_stage_leaves_no_patch(self):
        boom = RuntimeError(EXC_SECRET)
        cases = (
            ("input", input_stage, "resolve_input"),
            ("gitadapter", gitadapter.GitAdapter, "retrieve_diff"),
            ("sizegate", sizegate, "check_size"),
            ("analysis", analysis, "analyze"),
            ("mapping", mapping, "map_changes"),
            ("generation", generation, "generate"),
            ("proposal", proposal, "build_proposals"),
            ("redact", output, "render_patch"),
            ("validation", validation, "validate_content"),
        )
        r = self.repo()
        for stage, obj, name in cases:
            with self.subTest(stage=stage):
                with mock.patch.object(obj, name, side_effect=boom):
                    code, out, err = self.run_main([str(r.path)])
                self.assertEqual(code, 12)
                self.assertIn("Stage: %s" % stage, out)
                self.assertIn("Outcome: UNEXPECTED (exit 12)", out)
                self.assertNotIn(EXC_SECRET, out + err)
                self.assert_no_patch()

    def test_reader_exception_from_proposal_is_a_safe_typed_failure(self):
        r = self.repo()
        real = analysis.working_tree_reader
        readers = []

        def reader_factory(root):
            readers.append(root)
            if len(readers) == 1:
                return real(root)

            def bad(path):
                raise OSError(EXC_SECRET)
            return bad

        with mock.patch.object(analysis, "working_tree_reader", reader_factory):
            code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assertIn("Stage: proposal", out)
        self.assertNotIn(EXC_SECRET, out + err)
        self.assert_no_patch()

    def test_redactor_failure_exits_12_with_fallback(self):
        r = self.repo()
        with mock.patch("docsync.redact.contains_secret", side_effect=RuntimeError(EXC_SECRET)):
            code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assertEqual(out, "Run stopped: UNEXPECTED\n")
        self.assertNotIn(EXC_SECRET, out + err)
        self.assert_no_patch()


# ------------------------------------------------------- success-path report failures
class SuccessPathReportFailureTests(Base):
    def test_render_failure_exits_12_and_publish_never_ran(self):
        r = self.repo()
        self.spy_all()
        with mock.patch.object(report, "render_report", side_effect=RuntimeError(EXC_SECRET)):
            code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assertEqual(self.count("publish_patch"), 0)
        self.assertEqual(out, "Run stopped: UNEXPECTED\n")
        self.assertNotIn(EXC_SECRET, out + err)
        self.assert_no_patch()

    def test_emit_failure_after_publish_removes_the_patch_and_exits_12(self):
        r = self.repo()
        self.spy_all()
        code, err = self.run_with_stdout([str(r.path)], _Broken())
        self.assertEqual(code, 12)
        self.assertEqual(self.count("publish_patch"), 1)
        self.assertEqual(self.count("rollback_patch"), 1)
        self.assert_no_patch()

    def test_unicode_error_on_emit_prints_fallback_rolls_back_exits_12(self):
        r = self.repo()
        printed = []

        def emit(text):
            printed.append(text)
            if len(printed) == 1:
                raise UnicodeEncodeError("ascii", "x", 0, 1, "cannot encode")

        with mock.patch.object(report, "emit_report", emit):
            code, _out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assertEqual(printed[1], "Run stopped: UNEXPECTED\n")
        self.assert_no_patch()

    def _wide_render(self):
        """render_report with a printable non-ASCII name (built at runtime) appended."""
        wide = "doc" + chr(0xE9) + chr(0x6587) + ".md"
        original = report.render_report

        def render(*args, **kwargs):
            return original(*args, **kwargs) + "name: " + wide + "\n"

        return wide, render

    def test_non_ascii_report_on_narrow_stdout_is_escaped_and_succeeds(self):
        r = self.repo()
        wide, render = self._wide_render()
        for encoding in ("ascii", "cp1252"):
            with self.subTest(encoding=encoding):
                shutil.rmtree(self.patch_path.parent, ignore_errors=True)
                stdout = _Narrow(encoding)
                with mock.patch.object(report, "render_report", render):
                    code, _err = self.run_with_stdout([str(r.path)], stdout)
                self.assertEqual(code, 0)
                self.assertTrue(self.patch_path.exists())
                self.assertEqual(len(stdout.writes), 1)
                shown = stdout.writes[0]
                shown.encode(encoding)
                self.assertNotIn(wide, shown)
                self.assertIn("\\u6587", shown)

    def test_non_ascii_stop_report_on_narrow_stdout_is_escaped_keeps_code(self):
        r = self.repo({"README.md": "```\nunclosed\n", "pkg.py": BASE["pkg.py"]})
        wide, render = self._wide_render()
        stdout = _Narrow("ascii")
        with mock.patch.object(report, "render_report", render):
            code, _err = self.run_with_stdout([str(r.path)], stdout)
        self.assertEqual(code, 9)
        self.assert_no_patch()
        self.assertEqual(len(stdout.writes), 1)
        stdout.writes[0].encode("ascii")
        self.assertIn("\\u6587", stdout.writes[0])

    def test_retry_failure_keeps_rollback_and_exit_12(self):
        r = self.repo()
        wide, render = self._wide_render()
        stdout = _Narrow("ascii", fail_all=True)
        with mock.patch.object(report, "render_report", render):
            code, _err = self.run_with_stdout([str(r.path)], stdout)
        self.assertEqual(code, 12)
        self.assert_no_patch()
        self.assertEqual(stdout.writes, [])

    def test_replaced_file_is_not_deleted_when_emit_fails(self):
        r = self.repo()
        state = {}

        def emit(text):
            self.patch_path.unlink()
            self.patch_path.write_text("a different file\n", encoding="utf-8")
            state["sha"] = sha(self.patch_path)
            raise OSError(errno.EPIPE, "closed")

        with mock.patch.object(report, "emit_report", emit):
            code, _out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assertTrue(self.patch_path.exists())
        self.assertEqual(sha(self.patch_path), state["sha"])

    def test_rollback_failure_exits_12_names_leftover_and_reports_not_achieved(self):
        r = self.repo()
        with mock.patch.object(report, "emit_report", side_effect=OSError(errno.EPIPE, "closed")), \
                mock.patch("docsync.output.os.remove", side_effect=PermissionError(errno.EACCES, "held open")):
            code, _out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assertTrue(self.patch_path.exists())
        self.assertIn("all-or-nothing outcome NOT achieved", err)
        self.assertIn("docsync.patch", err)

    def test_pre_existing_file_appearing_before_write_exits_11_and_is_untouched(self):
        r = self.repo()
        self.spy_all()
        original = output.render_patch
        digest = {}

        def render_then_create(*args, **kwargs):
            result = original(*args, **kwargs)
            digest["sha"] = self.write_patch("someone else\n")
            return result

        with mock.patch.object(output, "render_patch", render_then_create):
            code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 11)
        self.assertEqual(sha(self.patch_path), digest["sha"])
        self.assertEqual(self.count("rollback_patch"), 0)
        self.assertEqual(self.count("emit_report"), 1)

    def test_write_error_during_publish_removes_partial_file_exit_11(self):
        r = self.repo()
        with mock.patch("docsync.output.os.fsync", side_effect=OSError(errno.ENOSPC, "disk full")):
            code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 11)
        self.assert_no_patch()
        self.assertIn("Outcome: PATCH_WRITE (exit 11)", out)

    def test_untyped_exception_inside_publish_removes_partial_file_exit_12(self):
        r = self.repo()
        with mock.patch("docsync.output.os.fsync", side_effect=RuntimeError(EXC_SECRET)):
            code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assert_no_patch()
        self.assertIn("Stage: publish", out)
        self.assertNotIn(EXC_SECRET, out + err)


# ---------------------------------------------------------------- destination re-render
class DestinationRenderTests(Base):
    def run_with_token_path(self, r, make_path):
        """Run with publish_patch returning a token whose path is changed (simulated)."""
        real_publish = output.publish_patch
        real_rollback = output.rollback_patch
        info = {"rolled_back_with": None, "real": None}

        def publish(content):
            token = real_publish(content)
            info["real"] = token
            return dataclasses.replace(token, path=make_path(token.path))

        def rollback(token):
            info["rolled_back_with"] = token
            return real_rollback(info["real"])

        renders = []
        real_render = report.render_report

        def render(result, *, redactor):
            renders.append(result)
            return real_render(result, redactor=redactor)

        patches = [mock.patch.object(output, "publish_patch", publish),
                   mock.patch.object(output, "rollback_patch", rollback),
                   mock.patch.object(report, "render_report", render)]
        return patches, info, renders

    def test_equal_paths_render_once(self):
        r = self.repo()
        self.spy_all()
        self.assertEqual(self.run_main([str(r.path)])[0], 0)
        self.assertEqual(self.count("render_report"), 1)
        shown = next(c for c in self.calls if c[0] == "render_report")[1][0]
        self.assertEqual(shown.patch_path, os.path.join(os.getcwd(), "output", "docsync.patch"))
        self.assertEqual(shown.patch_path, shown.default_patch_path)

    def test_different_destination_renders_a_second_time_with_the_token_path(self):
        r = self.repo()
        patches, _info, renders = self.run_with_token_path(r, lambda p: p + ".resolved")
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            code, out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 0)
        self.assertEqual(len(renders), 2)
        default = os.path.join(os.getcwd(), "output", "docsync.patch")
        self.assertEqual(renders[0].patch_path, default)
        self.assertEqual(renders[1].patch_path, default + ".resolved")
        self.assertEqual(renders[1].default_patch_path, default)
        self.assertIn("docsync.patch.resolved", out)
        self.assertTrue(self.patch_path.exists())

    def test_second_render_failure_rolls_back_with_the_token_and_exits_12(self):
        r = self.repo()
        patches, info, renders = self.run_with_token_path(r, lambda p: p + ".resolved")
        real_render = report.render_report

        def render(result, *, redactor):
            renders.append(result)
            if result.patch_path is not None and result.patch_path.endswith(".resolved"):
                raise RuntimeError(EXC_SECRET)
            return real_render(result, redactor=redactor)

        patches[2] = mock.patch.object(report, "render_report", render)
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            code, out, err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assertEqual(info["rolled_back_with"].path, info["real"].path + ".resolved")
        self.assertNotIn(EXC_SECRET, out + err)
        self.assert_no_patch()

    def test_second_render_failure_does_not_delete_a_replaced_file(self):
        r = self.repo()
        patches, _info, renders = self.run_with_token_path(r, lambda p: p + ".resolved")
        real_render = report.render_report
        state = {}

        def render(result, *, redactor):
            if result.patch_path is not None and result.patch_path.endswith(".resolved"):
                self.patch_path.unlink()
                state["sha"] = self.write_patch("replacement\n")
                raise RuntimeError("fail")
            return real_render(result, redactor=redactor)

        patches[2] = mock.patch.object(report, "render_report", render)
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            code, _out, _err = self.run_main([str(r.path)])
        self.assertEqual(code, 12)
        self.assertEqual(sha(self.patch_path), state["sha"])

    def _second_render_fails(self, r, remove_fails):
        patches, info, renders = self.run_with_token_path(r, lambda p: p + ".resolved")
        real_render = report.render_report

        def render(result, *, redactor):
            if result.patch_path is not None and result.patch_path.endswith(".resolved"):
                raise RuntimeError(EXC_SECRET)
            return real_render(result, redactor=redactor)

        patches[2] = mock.patch.object(report, "render_report", render)
        emits = []
        real_emit = report.emit_report
        patches.append(mock.patch.object(report, "emit_report", lambda t: (emits.append(t), real_emit(t))[1]))
        if remove_fails:
            patches.append(mock.patch("docsync.output.os.remove",
                                      side_effect=PermissionError(errno.EACCES, "held open")))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            code, out, err = self.run_main([str(r.path)])
        return code, out, err, emits

    def test_second_render_failure_with_failed_rollback_prints_only_the_fixed_line(self):
        r = self.repo()
        code, out, err, emits = self._second_render_fails(r, remove_fails=True)
        self.assertEqual(code, 12)
        self.assertEqual(emits, [cli._NOT_ACHIEVED_LINE])
        self.assertIn(cli._NOT_ACHIEVED_LINE, out)
        self.assertNotIn("no patch was written", out)
        self.assertTrue(self.patch_path.exists())
        self.assertIn("all-or-nothing outcome NOT achieved", err)
        self.assertNotIn(EXC_SECRET, out + err)

    def test_second_render_failure_with_successful_rollback_prints_the_ordinary_report(self):
        r = self.repo()
        code, out, err, emits = self._second_render_fails(r, remove_fails=False)
        self.assertEqual(code, 12)
        self.assertEqual(len(emits), 1)
        self.assertIn("no patch was written", out)
        self.assertNotIn("NOT achieved", out)
        self.assert_no_patch()

    def test_not_achieved_line_is_constant(self):
        self.assertEqual(
            cli._NOT_ACHIEVED_LINE,
            "Run stopped: UNEXPECTED. All-or-nothing outcome NOT achieved: "
            "a patch may remain at output/docsync.patch.")
        self.assertNotIn(os.sep + "output", cli._NOT_ACHIEVED_LINE.replace("output/", ""))
        self.assertNotIn(tempfile.gettempdir(), cli._NOT_ACHIEVED_LINE)
        self.assertNotIn(EXC_SECRET, cli._NOT_ACHIEVED_LINE)


class IsolationTests(unittest.TestCase):
    def test_this_suite_does_not_use_the_repository_output_directory(self):
        # Base.setUp changes into a temporary directory; nothing here writes to ./output.
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("os.chdir(self.work)", source)


if __name__ == "__main__":
    unittest.main()
