"""Tests for D12/D14 (no repository-size and no per-file limit; the diff cap is the only limit).

History: code review M-1 had added a 64 MiB Git stdout cap and a 4,000,000-byte reader cap.
Both were removed. What replaced them: the size gate runs BEFORE the diff text is fetched
(``retrieve_diff(gate=...)``), and a MemoryError ends the run as the unexpected failure (12).
Kept and tested here: stderr bound, timeout, no-hang pipe handling, exit-code passthrough,
the allow-list, and ``proposal.MAX_ORIGINAL_CHARS``.
"""

import contextlib
import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from docsync import analysis, cli, gitadapter, proposal
from docsync.contracts import ExitCode, ProposedEdit
from tests.helpers.gitrepo import TempGitRepo, git_available

SENTINEL = "BOUNDSENTINEL"
MIB = 1024 * 1024
MemoryErrorText = "MEMORYERRORSECRETTEXT"  # must never reach any output


def writer_argv(total=None):
    """A child that writes 1 KiB blocks of 'x' (forever if total is None)."""
    code = (
        "import sys\n"
        "o = sys.stdout.buffer\n"
        "n = 0\n"
        "while %s:\n"
        "    o.write(b'x' * 1024); o.flush(); n += 1024\n" % ("True" if total is None else "n < %d" % total)
    )
    return [sys.executable, "-c", code]


class BoundedRunnerTests(unittest.TestCase):
    def run_bounded(self, argv, **kw):
        return gitadapter._bounded_run(argv, shell=False, stdin=subprocess.DEVNULL, timeout=120, **kw)

    def test_removed_stdout_cap_names_no_longer_exist(self):
        self.assertFalse(hasattr(gitadapter, "MAX_STDOUT_BYTES"))
        self.assertFalse(hasattr(gitadapter, "GitOutputOverCapError"))
        self.assertFalse(hasattr(analysis, "MAX_READ_BYTES"))

    def test_stderr_bound_is_documented_value(self):
        self.assertEqual(gitadapter.MAX_STDERR_BYTES, 64 * 1024)

    def test_tens_of_mebibytes_of_stdout_are_returned_in_full(self):
        total = 40 * MIB  # far above the old 64 MiB-class bound's neighbours; no cap applies
        proc = self.run_bounded(writer_argv(total))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(proc.stdout), total)

    def test_large_stdout_is_returned_in_full_through_the_adapter_runner(self):
        total = 20 * MIB
        big = subprocess.CompletedProcess([], 0, b"y" * total, b"")
        adapter = gitadapter.GitAdapter(".", redactor=lambda s: s, runner=lambda argv, **k: big)
        self.assertEqual(len(adapter.run(gitadapter.TEMPLATES["diff-text"])), total)

    def test_stderr_is_bounded_and_the_child_still_finishes(self):
        code = "import sys; sys.stderr.write('e' * 300000); sys.stdout.write('ok')"
        with mock.patch.object(gitadapter, "MAX_STDERR_BYTES", 1000):
            proc = self.run_bounded([sys.executable, "-c", code])
        self.assertEqual(proc.stdout, b"ok")
        self.assertEqual(len(proc.stderr), 1000)

    def test_timeout_still_raises_and_kills_the_child(self):
        procs = []
        real_popen = subprocess.Popen

        def spy(*a, **k):
            p = real_popen(*a, **k)
            procs.append(p)
            return p

        with mock.patch.object(subprocess, "Popen", spy):
            with self.assertRaises(subprocess.TimeoutExpired):
                gitadapter._bounded_run([sys.executable, "-c", "import time; time.sleep(60)"],
                                        shell=False, stdin=subprocess.DEVNULL, timeout=0.5)
        self.assertEqual(len(procs), 1)
        self.assertIsNotNone(procs[0].poll(), "the child must have been killed by its handle")

    def test_exit_code_is_returned(self):
        proc = self.run_bounded([sys.executable, "-c", "import sys; sys.exit(3)"])
        self.assertEqual(proc.returncode, 3)

    def test_memory_error_while_accumulating_kills_the_child_and_raises(self):
        procs = []
        real_popen = subprocess.Popen
        real_drain = gitadapter._drain

        def spy_popen(*a, **k):
            p = real_popen(*a, **k)
            procs.append(p)
            return p

        class Exploding(list):
            def append(self, item):
                raise MemoryError()

        def spy_drain(pipe, limit, sink, failed):
            # stdout is the drain without a limit; make its accumulation run out of memory
            return real_drain(pipe, limit, Exploding() if limit is None else sink, failed)

        started = time.monotonic()
        with mock.patch.object(subprocess, "Popen", spy_popen), \
                mock.patch.object(gitadapter, "_drain", spy_drain):
            with self.assertRaises(MemoryError) as ctx:
                self.run_bounded(writer_argv())  # endless writer: would block if nobody reads
        self.assertEqual(str(ctx.exception), "")
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(len(procs), 1)
        self.assertIsNotNone(procs[0].poll(), "the child must have been killed by its handle")

    def test_memory_error_in_the_runner_is_not_turned_into_a_git_error(self):
        def runner(argv, **k):
            raise MemoryError()

        adapter = gitadapter.GitAdapter(".", redactor=lambda s: s, runner=runner)
        with self.assertRaises(MemoryError):
            adapter.run(gitadapter.TEMPLATES["diff-text"])

    def test_allow_list_is_unchanged(self):
        self.assertEqual(len(gitadapter.TEMPLATES), 6)


GRANDCHILD_LIFETIME = 20  # seconds; the grandchild exits by itself after this


def holder_argv(pid_file, then):
    """A child that spawns a grandchild inheriting its pipes, records its PID, then runs ``then``."""
    code = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(%d)'])\n"
        "open(%r, 'w').write(str(g.pid))\n"
        "%s\n" % (GRANDCHILD_LIFETIME, pid_file, then)
    )
    return [sys.executable, "-c", code]


class PipeHeldByDescendantTests(unittest.TestCase):
    """F1/N2: a descendant holding the pipe write end must not make the runner hang."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pid_file = os.path.join(self._tmp.name, "grandchild.pid")
        self.addCleanup(self._kill_grandchild)

    def _kill_grandchild(self):
        try:
            with open(self.pid_file) as fh:
                pid = int(fh.read())
        except (OSError, ValueError):
            return
        try:
            if os.name == "nt":  # by PID only, never by image name
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            else:
                os.kill(pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            pass

    def _run(self, argv, timeout):
        box = {}

        def target():
            started = time.monotonic()
            try:
                gitadapter._bounded_run(argv, shell=False, stdin=subprocess.DEVNULL, timeout=timeout)
                box["result"] = "returned"
            except BaseException as exc:  # recorded for the assertions
                box["result"] = exc
            box["elapsed"] = time.monotonic() - started

        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        worker.join(timeout=GRANDCHILD_LIFETIME - 8)  # hard outer bound
        self.assertFalse(worker.is_alive(), "_bounded_run hung while a descendant held the pipe")
        return box

    def test_hanging_child_with_pipe_holding_grandchild_times_out(self):
        argv = holder_argv(self.pid_file, "time.sleep(60)")
        with mock.patch.object(gitadapter, "_GRACE_SECONDS", 2):
            box = self._run(argv, timeout=1)
        self.assertIsInstance(box["result"], subprocess.TimeoutExpired, box["result"])
        self.assertLess(box["elapsed"], 1 + 2 + 2 + 3)

    def test_exited_child_with_pipe_holding_grandchild_fails_closed(self):
        argv = holder_argv(self.pid_file, "sys.stdout.write('partial'); sys.stdout.flush()")
        with mock.patch.object(gitadapter, "_GRACE_SECONDS", 2):
            box = self._run(argv, timeout=1)
        self.assertIsInstance(box["result"], subprocess.TimeoutExpired, box["result"])
        self.assertLess(box["elapsed"], 1 + 2 + 2 + 3)


# --------------------------------------------------------------- pre-fetch gate (A1)
def _raw_record(path):
    return ":100644 100644 %s %s M\0%s\0" % ("a" * 40, "b" * 40, path)


class FakeGit:
    """An injectable runner returning canned output for the allow-listed templates."""

    def __init__(self, paths=("a.py",), added=1, deleted=0, cwd=None):
        self.paths = paths
        self.added = added
        self.deleted = deleted
        self.cwd = cwd
        self.names = []

    def __call__(self, argv, **kw):
        name = gitadapter.match_template(argv[1:])
        self.names.append(name)
        out = b""
        if name == "rev-parse-toplevel":
            out = (self.cwd.replace("\\", "/") + "\n").encode()
        elif name == "config-list":
            out = b"file:.git/config\tcore.repositoryformatversion=0\n"
        elif name == "diff-raw":
            out = "".join(_raw_record(p) for p in self.paths).encode()
        elif name == "diff-numstat":
            out = "".join("%d\t%d\t%s\0" % (self.added, self.deleted, p) for p in self.paths).encode()
        elif name == "diff-text":
            out = b"diff text\n"
        elif name == "ls-files-others":
            out = b"new.txt\0"
        return subprocess.CompletedProcess(argv, 0, out, b"")


class GateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cwd = os.path.realpath(self._tmp.name)

    def adapter(self, fake):
        return gitadapter.GitAdapter(self.cwd, redactor=lambda s: s, runner=fake)

    def test_gate_runs_after_raw_and_numstat_and_before_text_and_untracked(self):
        fake = FakeGit(paths=("a.py", "b.py"), cwd=self.cwd)
        seen = []

        def gate(files):
            seen.append((tuple(fake.names), files))

        result = self.adapter(fake).retrieve_diff(gate=gate)
        self.assertEqual(len(seen), 1)
        before, files = seen[0]
        self.assertEqual(before, ("rev-parse-toplevel", "config-list", "diff-raw", "diff-numstat"))
        self.assertIsInstance(files, tuple)
        self.assertEqual([f.path for f in files], ["a.py", "b.py"])
        self.assertEqual(fake.names[-2:], ["diff-text", "ls-files-others"])
        self.assertEqual(result.diff_text, "diff text\n")
        self.assertEqual(result.untracked, ("new.txt",))

    def test_a_raising_gate_propagates_unchanged_and_no_text_is_fetched(self):
        fake = FakeGit(cwd=self.cwd)
        marker = RuntimeError("from the gate")

        def gate(files):
            raise marker

        with self.assertRaises(RuntimeError) as ctx:
            self.adapter(fake).retrieve_diff(gate=gate)
        self.assertIs(ctx.exception, marker)
        self.assertNotIn("diff-text", fake.names)
        self.assertNotIn("ls-files-others", fake.names)

    def test_no_gate_is_the_old_behavior(self):
        fake = FakeGit(cwd=self.cwd)
        result = self.adapter(fake).retrieve_diff()
        self.assertEqual(fake.names, ["rev-parse-toplevel", "config-list", "diff-raw",
                                      "diff-numstat", "diff-text", "ls-files-others"])
        self.assertEqual([f.path for f in result.files], ["a.py"])
        fake2 = FakeGit(cwd=self.cwd)
        self.adapter(fake2).retrieve_diff(gate=None)
        self.assertEqual(fake2.names, fake.names)

    def test_a_gate_that_is_not_callable_is_a_type_error_before_any_git_call(self):
        fake = FakeGit(cwd=self.cwd)
        with self.assertRaises(TypeError):
            self.adapter(fake).retrieve_diff(gate="no")
        self.assertEqual(fake.names, [])

    def test_empty_change_set_still_calls_the_gate_with_no_records(self):
        fake = FakeGit(paths=(), cwd=self.cwd)
        seen = []
        result = self.adapter(fake).retrieve_diff(gate=seen.append)
        self.assertEqual(seen, [()])
        self.assertTrue(result.is_empty)


# ------------------------------------------------------- main(): helpers and fixtures
def spy_on_git_calls(calls):
    real_run = gitadapter.GitAdapter.run

    def run(self, args):
        calls.append(gitadapter.match_template(args))
        return real_run(self, args)

    return mock.patch.object(gitadapter.GitAdapter, "run", run)


class MainBase(unittest.TestCase):
    def setUp(self):
        self._origin = os.getcwd()
        self.work = tempfile.mkdtemp(prefix="docsync_bounds_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.work, ignore_errors=True))
        self.addCleanup(os.chdir, self._origin)

    @property
    def patch_path(self):
        return os.path.join(self.work, "output", "docsync.patch")

    def main(self, repo, *patches):
        out, err = io.StringIO(), io.StringIO()
        os.chdir(self.work)
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = cli.main([str(repo.path)])
        return code, out.getvalue() + err.getvalue()

    def small_repo(self):
        repo = TempGitRepo({"README.md": "# Demo\n\nText.\n", "pkg.py": "x = 1\n"})
        self.addCleanup(repo.cleanup)
        repo.write("pkg.py", "x = 1\n\n\ndef added_function(a):\n    return a\n")
        return repo


@unittest.skipUnless(git_available(), "git is not available")
class MainOverCapBeforeFetchTests(MainBase):
    def test_more_than_50_files_exits_5_with_counts_and_never_requests_diff_text(self):
        repo = TempGitRepo({"README.md": "# Demo\n"})
        self.addCleanup(repo.cleanup)
        for i in range(51):
            repo.write("src/m%02d.py" % i, "v = %d\n" % i)
        repo.commit("many")
        for i in range(51):
            repo.write("src/m%02d.py" % i, "v = %d\nw = %d\n" % (i, i))
        calls = []
        with spy_on_git_calls(calls):
            code, text = self.main(repo)
        self.assertEqual(code, int(ExitCode.OVER_CAP), text)
        self.assertIn("51 files", text)
        self.assertIn("51 changed lines", text)
        self.assertIn("diff-numstat", calls)
        self.assertNotIn("diff-text", calls)
        self.assertNotIn("ls-files-others", calls)
        self.assertFalse(os.path.exists(self.patch_path))

    def test_more_than_2000_changed_lines_exits_5_with_counts_and_never_requests_diff_text(self):
        repo = TempGitRepo({"README.md": "# Demo\n", "pkg.py": "x = 1\n"})
        self.addCleanup(repo.cleanup)
        repo.write("pkg.py", "".join("v%d = %d\n" % (i, i) for i in range(2000)))  # +2000 -1
        calls = []
        with spy_on_git_calls(calls):
            code, text = self.main(repo)
        self.assertEqual(code, int(ExitCode.OVER_CAP), text)
        self.assertIn("1 files", text)
        self.assertIn("2001 changed lines", text)
        self.assertNotIn("diff-text", calls)
        self.assertFalse(os.path.exists(self.patch_path))

    def test_unsupported_entry_still_wins_over_over_cap_and_is_exit_6(self):
        repo = TempGitRepo({"README.md": "# Demo\n", "pkg.py": "x = 1\n", "img.bin": b"\x00\x01"})
        self.addCleanup(repo.cleanup)
        repo.write("pkg.py", "".join("v%d = %d\n" % (i, i) for i in range(2000)))
        repo.write("img.bin", b"\x00\x02\x03")
        calls = []
        with spy_on_git_calls(calls):
            code, text = self.main(repo)
        self.assertEqual(code, int(ExitCode.UNSUPPORTED_ENTRY), text)
        self.assertNotIn("diff-text", calls)
        self.assertFalse(os.path.exists(self.patch_path))

    def test_a_diff_at_the_cap_is_fetched_and_processed(self):
        repo = self.small_repo()
        calls = []
        with spy_on_git_calls(calls):
            code, text = self.main(repo)
        self.assertEqual(code, int(ExitCode.OK), text)
        self.assertIn("diff-text", calls)
        self.assertTrue(os.path.exists(self.patch_path))


# ------------------------------------------------------------ MemoryError (A3)
@unittest.skipUnless(git_available(), "git is not available")
class MainMemoryErrorTests(MainBase):
    LEAK = MemoryErrorText

    def assert_unexpected(self, code, text, stage):
        self.assertEqual(code, int(ExitCode.UNEXPECTED), text)
        self.assertIn(stage, text)
        self.assertNotIn(self.LEAK, text)
        self.assertNotIn("MemoryError", text)
        self.assertFalse(os.path.exists(self.patch_path))

    def test_memory_error_in_the_git_runner(self):
        repo = self.small_repo()
        real_run = gitadapter.GitAdapter.run

        def run(self_, args):
            if gitadapter.match_template(args) == "diff-text":
                raise MemoryError(MemoryErrorText)
            return real_run(self_, args)

        code, text = self.main(repo, mock.patch.object(gitadapter.GitAdapter, "run", run))
        self.assert_unexpected(code, text, "gitadapter")

    def test_memory_error_in_the_reader(self):
        repo = self.small_repo()

        def factory(root):
            def read_text(path):
                raise MemoryError(MemoryErrorText)
            return read_text

        code, text = self.main(repo, mock.patch.object(analysis, "working_tree_reader", factory))
        self.assertEqual(code, int(ExitCode.UNEXPECTED), text)
        self.assertTrue("analysis" in text or "proposal" in text, text)
        self.assertNotIn(self.LEAK, text)
        self.assertFalse(os.path.exists(self.patch_path))

    def test_memory_error_in_the_reader_during_proposal(self):
        repo = self.small_repo()
        real = analysis.working_tree_reader
        made = []

        def factory(root):
            made.append(root)
            if len(made) == 1:  # the analysis stage reads normally
                return real(root)

            def read_text(path):
                raise MemoryError(MemoryErrorText)
            return read_text

        code, text = self.main(repo, mock.patch.object(analysis, "working_tree_reader", factory))
        self.assert_unexpected(code, text, "proposal")

    def test_memory_error_in_analysis(self):
        repo = self.small_repo()

        def analyze(*a, **k):
            raise MemoryError(MemoryErrorText)

        code, text = self.main(repo, mock.patch.object(analysis, "analyze", analyze))
        self.assert_unexpected(code, text, "analysis")

    def test_memory_error_in_proposal(self):
        repo = self.small_repo()

        def build(*a, **k):
            raise MemoryError(MemoryErrorText)

        code, text = self.main(repo, mock.patch.object(proposal, "build_proposals", build))
        self.assert_unexpected(code, text, "proposal")

    def test_memory_error_in_render(self):
        repo = self.small_repo()
        real = cli.report.render_report

        def render(report_input, **k):
            if report_input.outcome == ExitCode.OK:  # the success report only
                raise MemoryError(MemoryErrorText)
            return real(report_input, **k)

        code, text = self.main(repo, mock.patch.object(cli.report, "render_report", render))
        self.assert_unexpected(code, text, "render")

    def test_memory_error_after_publish_rolls_the_patch_back(self):
        repo = self.small_repo()
        def emit(text):
            raise MemoryError(MemoryErrorText)

        out, err = io.StringIO(), io.StringIO()
        os.chdir(self.work)
        with mock.patch.object(cli.report, "emit_report", emit), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([str(repo.path)])
        # emit failures are handled as "report could not be written": exit 12 and rollback
        self.assertEqual(code, int(ExitCode.UNEXPECTED), out.getvalue() + err.getvalue())
        self.assertFalse(os.path.exists(self.patch_path))
        self.assertNotIn(self.LEAK, out.getvalue() + err.getvalue())


# ----------------------------------------------------------- reader (A2) and proposal
class ReaderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_a_file_above_the_old_4_000_000_byte_bound_is_read_in_full(self):
        size = 5_000_000
        (self.root / "big.md").write_bytes(b"a" * size)
        text = analysis.working_tree_reader(self.root)("big.md")
        self.assertIsNotNone(text)
        self.assertEqual(len(text), size)

    def test_other_behaviors_are_kept(self):
        (self.root / "crlf.md").write_bytes(b"a\r\nb\r\n")
        (self.root / "bad.md").write_bytes(b"\xff")
        (self.root / "adir").mkdir()
        read = analysis.working_tree_reader(self.root)
        self.assertEqual(read("crlf.md"), "a\r\nb\r\n")  # no newline translation
        self.assertIsNone(read("bad.md"))               # strict UTF-8
        self.assertIsNone(read("../x.md"))              # root-confined
        self.assertIsNone(read("."))                    # not a regular file
        self.assertIsNone(read("adir"))                 # not a regular file
        self.assertIsNone(read("missing.md"))

    def test_invalid_utf8_is_rejected_even_in_a_large_file(self):
        (self.root / "badbig.md").write_bytes(b"a" * 5_000_000 + b"\xff")
        self.assertIsNone(analysis.working_tree_reader(self.root)("badbig.md"))

    def test_proposal_still_skips_a_document_above_max_original_chars(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "big.md").write_bytes(b"a" * (proposal.MAX_ORIGINAL_CHARS + 1))
        edit = ProposedEdit(target="docs/big.md", reason="Document the change.", symbol_names=("f",))
        result = proposal.build_proposals([edit], analysis.working_tree_reader(self.root))
        self.assertEqual(len(result.documents), 0)
        self.assertEqual([s.reason for s in result.skipped], [proposal.SKIP_TOO_LARGE])

    def test_max_original_chars_is_unchanged(self):
        self.assertEqual(proposal.MAX_ORIGINAL_CHARS, 1_000_000)


if __name__ == "__main__":
    unittest.main()
