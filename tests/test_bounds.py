"""Regression tests for code review M-1: bounded Git output, bounded file reads."""

import contextlib
import io
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from docsync import analysis, cli, gitadapter, proposal
from docsync.contracts import ExitCode, ProposedEdit, OverCapError
from tests.helpers.gitrepo import TempGitRepo, git_available

SENTINEL = "BOUNDSENTINEL"


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
        return gitadapter._bounded_run(argv, shell=False, stdin=subprocess.DEVNULL, timeout=60, **kw)

    def test_constants_are_documented_values(self):
        self.assertEqual(gitadapter.MAX_STDOUT_BYTES, 64 * 1024 * 1024)
        self.assertEqual(gitadapter.MAX_STDERR_BYTES, 64 * 1024)

    def test_endless_writer_is_stopped_at_the_bound_and_its_handle_is_terminated(self):
        procs = []
        real_popen = subprocess.Popen

        def spy(*a, **k):
            p = real_popen(*a, **k)
            procs.append(p)
            return p

        with mock.patch.object(gitadapter, "MAX_STDOUT_BYTES", 8192), \
                mock.patch.object(subprocess, "Popen", spy):
            with self.assertRaises(OverCapError) as ctx:
                self.run_bounded(writer_argv())
        self.assertIsInstance(ctx.exception, gitadapter.GitOutputOverCapError)
        self.assertEqual(ctx.exception.exit_code, ExitCode.OVER_CAP)
        self.assertEqual(len(procs), 1)
        self.assertIsNotNone(procs[0].poll(), "the child must have been terminated")

    def test_nothing_beyond_the_bound_plus_one_chunk_is_accumulated(self):
        kept = []
        real_drain = gitadapter._drain

        def spy(pipe, limit, sink, exceeded):
            kept.append(sink)
            return real_drain(pipe, limit, sink, exceeded)

        with mock.patch.object(gitadapter, "MAX_STDOUT_BYTES", 8192), \
                mock.patch.object(gitadapter, "_CHUNK", 1000), \
                mock.patch.object(gitadapter, "_drain", spy):
            with self.assertRaises(gitadapter.GitOutputOverCapError):
                self.run_bounded(writer_argv())
        stdout_sink = kept[0]
        self.assertGreater(len(stdout_sink), 0, "accumulation must actually be exercised")
        self.assertLessEqual(sum(len(c) for c in stdout_sink), 8192)

    def test_output_exactly_at_the_bound_is_returned(self):
        with mock.patch.object(gitadapter, "MAX_STDOUT_BYTES", 4096):
            proc = self.run_bounded(writer_argv(4096))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(proc.stdout), 4096)

    def test_one_byte_over_the_bound_is_over_cap(self):
        with mock.patch.object(gitadapter, "MAX_STDOUT_BYTES", 4095):
            with self.assertRaises(gitadapter.GitOutputOverCapError):
                self.run_bounded(writer_argv(4096))

    def test_stderr_is_bounded_and_the_child_still_finishes(self):
        code = "import sys; sys.stderr.write('e' * 300000); sys.stdout.write('ok')"
        with mock.patch.object(gitadapter, "MAX_STDERR_BYTES", 1000):
            proc = self.run_bounded([sys.executable, "-c", code])
        self.assertEqual(proc.stdout, b"ok")
        self.assertEqual(len(proc.stderr), 1000)

    def test_timeout_still_raises_and_kills_the_child(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            gitadapter._bounded_run([sys.executable, "-c", "import time; time.sleep(60)"],
                                    shell=False, stdin=subprocess.DEVNULL, timeout=0.5)

    def test_exit_code_is_returned(self):
        proc = self.run_bounded([sys.executable, "-c", "import sys; sys.exit(3)"])
        self.assertEqual(proc.returncode, 3)

    def test_error_message_is_fixed_and_holds_no_data(self):
        text = str(gitadapter.GitOutputOverCapError())
        self.assertNotIn(SENTINEL, text)
        self.assertIn("over the size limit", text)

    def test_adapter_backstop_for_an_injected_runner(self):
        big = subprocess.CompletedProcess([], 0, b"y" * 20, b"")
        with mock.patch.object(gitadapter, "MAX_STDOUT_BYTES", 10):
            a = gitadapter.GitAdapter(".", redactor=lambda s: s, runner=lambda argv, **k: big)
            with self.assertRaises(gitadapter.GitOutputOverCapError):
                a.run(gitadapter.TEMPLATES["diff-text"])

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

    def test_over_cap_returns_even_if_a_grandchild_holds_the_pipes(self):
        argv = holder_argv(self.pid_file, "while True: sys.stdout.buffer.write(b'x' * 1024); sys.stdout.flush()")
        with mock.patch.object(gitadapter, "_GRACE_SECONDS", 2), \
                mock.patch.object(gitadapter, "MAX_STDOUT_BYTES", 8192):
            box = self._run(argv, timeout=30)
        self.assertIsInstance(box["result"], gitadapter.GitOutputOverCapError, box["result"])
        self.assertLess(box["elapsed"], 2 + 2 + 3)


@unittest.skipUnless(git_available(), "git is not available")
class MainOverCapTests(unittest.TestCase):
    def test_main_exits_5_when_the_diff_text_reaches_the_bound(self):
        origin = os.getcwd()
        work = tempfile.mkdtemp(prefix="docsync_bounds_")
        self.addCleanup(lambda: __import__("shutil").rmtree(work, ignore_errors=True))
        repo = TempGitRepo({"README.md": "# Demo\n", "pkg.py": "x = 1\n"})
        self.addCleanup(repo.cleanup)
        repo.write("pkg.py", "".join("v%d = %d\n" % (i, i) for i in range(2000)))
        out, err = io.StringIO(), io.StringIO()
        os.chdir(work)
        try:
            with mock.patch.object(gitadapter, "MAX_STDOUT_BYTES", 8192), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main([str(repo.path)])
        finally:
            os.chdir(origin)
        self.assertEqual(code, int(ExitCode.OVER_CAP), out.getvalue() + err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(work, "output", "docsync.patch")))


class ReaderBoundTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_bound_is_documented(self):
        self.assertEqual(analysis.MAX_READ_BYTES, 4_000_000)
        self.assertGreaterEqual(analysis.MAX_READ_BYTES, proposal.MAX_ORIGINAL_CHARS)

    def test_file_at_the_bound_is_read_and_one_over_is_none(self):
        (self.root / "at.md").write_bytes(b"a" * 20)
        (self.root / "over.md").write_bytes(b"a" * 21)
        with mock.patch.object(analysis, "MAX_READ_BYTES", 20):
            read = analysis.working_tree_reader(self.root)
            self.assertEqual(read("at.md"), "a" * 20)
            self.assertIsNone(read("over.md"))

    def test_read_is_bounded_even_if_stat_reports_small(self):
        (self.root / "grew.md").write_bytes(b"a" * 50)
        fake = mock.Mock(st_size=1, st_mode=stat.S_IFREG)
        with mock.patch.object(analysis, "MAX_READ_BYTES", 20), \
                mock.patch.object(Path, "stat", return_value=fake):
            self.assertIsNone(analysis.working_tree_reader(self.root)("grew.md"))

    def test_other_behaviors_are_kept(self):
        (self.root / "crlf.md").write_bytes(b"a\r\nb\r\n")
        (self.root / "bad.md").write_bytes(b"\xff")
        read = analysis.working_tree_reader(self.root)
        self.assertEqual(read("crlf.md"), "a\r\nb\r\n")
        self.assertIsNone(read("bad.md"))
        self.assertIsNone(read("../x.md"))
        self.assertIsNone(read("."))

    def test_proposal_reports_not_found_for_an_oversized_document(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "big.md").write_bytes(b"a" * 21)
        edit = ProposedEdit(target="docs/big.md", reason="Document the change.", symbol_names=("f",))
        with mock.patch.object(analysis, "MAX_READ_BYTES", 20):
            result = proposal.build_proposals([edit], analysis.working_tree_reader(self.root))
        self.assertEqual(len(result.documents), 0)
        self.assertEqual([s.reason for s in result.skipped], [proposal.SKIP_UNREADABLE])


if __name__ == "__main__":
    unittest.main()
