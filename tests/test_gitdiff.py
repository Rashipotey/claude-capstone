"""T05 tests: Git diff retrieval and the content-filter preflight (fail closed).

Method (plan T05): every hostile fixture has a live control run that omits the protections
and proves the fixture can fire. A fixture whose control does not fire is not evidence; it
is recorded in ``NON_EVIDENCE`` and announced on standard error as ``NON-EVIDENCE: <name>``,
and the test makes no claim from it. Assertion messages never echo values.

Fixtures are local temporary repositories. Hostile commands only write a marker file in a
temporary directory outside the repository. No network, no real secrets.
"""

import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docsync import gitadapter
from docsync.contracts import ExitCode
from docsync.gitadapter import (
    EMPTY_CHANGE_SET, TEMPLATES, ContentFilterError, DiffResult, GitAdapter, GitCommandError,
    NoHeadError, NotARepositoryError, PreflightUnverifiedError, check_config_listing, match_template,
)
from docsync.redact import redact
from tests.helpers.gitrepo import TempGitRepo, _env, git_available

NON_EVIDENCE = []
VALUE_TOKEN = "VALUETOKEN_9c1e"  # appears only inside hostile configuration values


def note_control(name, fired):
    """Record a control result; return True when the control fired (the fixture is evidence)."""
    if not fired:
        NON_EVIDENCE.append(name)
        sys.stderr.write("NON-EVIDENCE: %s (control did not fire)\n" % name)
    return fired


def git_version():
    out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def cfg_quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class SpyRunner:
    """Wraps subprocess.run and records every argument vector and environment."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.run(argv, **kwargs)

    def names(self):
        return [match_template(argv[1:]) for argv, _ in self.calls]


class StubRunner:
    """Returns a canned result (or raises) for every call."""

    def __init__(self, stdout=b"", returncode=0, raises=None):
        self.calls = []
        self.stdout, self.returncode, self.raises = stdout, returncode, raises

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, b"")


def make_adapter(path, **kw):
    kw.setdefault("redactor", redact)
    return GitAdapter(path, **kw)


class MarkerCase(unittest.TestCase):
    """Base class: a marker directory outside any repository, and control-run helpers."""

    def setUp(self):
        self._mk = tempfile.TemporaryDirectory(prefix="docsync_marker_")
        self.addCleanup(self._mk.cleanup)
        self.marker_dir = Path(self._mk.name)

    def cmd(self, name, with_value=False):
        """A shell command that writes marker ``name``; optionally carries VALUE_TOKEN."""
        text = "echo %s" % (VALUE_TOKEN if with_value else "x")
        return '%s > "%s"' % (text, (self.marker_dir / name).as_posix())

    def fired(self, name):
        path = self.marker_dir / name
        hit = path.exists()
        if hit:
            path.unlink()
        return hit

    def plain_git(self, repo, *args, env=None):
        """Control run: git without any of the adapter's protections."""
        return subprocess.run(["git", *args], cwd=repo.path, env=env or _env(),
                              capture_output=True, timeout=60)

    def no_leak(self, text, what="output"):
        # The message must not echo the value, so the check is a plain boolean.
        self.assertFalse(VALUE_TOKEN in text, "a configuration value leaked into %s" % what)


def modified_repo(files=None, **kw):
    repo = TempGitRepo(files or {"a.txt": "1\n"}, **kw)
    return repo


# =================================================================== hardening controls
@unittest.skipUnless(git_available(), "git executable not available in this environment")
class ArgumentVectorTests(unittest.TestCase):
    def test_every_call_equals_one_of_the_six_templates_and_has_no_pager(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo:
            repo.write("a.txt", "2\n")
            spy = SpyRunner()
            make_adapter(repo.path, runner=spy).retrieve_diff()
            self.assertEqual(spy.names(), ["rev-parse-toplevel", "config-list", "diff-raw",
                                           "diff-numstat", "diff-text", "ls-files-others"])
            for argv, kwargs in spy.calls:
                self.assertIn(argv[1:], [list(t) for t in TEMPLATES.values()])
                self.assertIn("--no-pager", argv)
                self.assertIs(kwargs["shell"], False)


@unittest.skipUnless(git_available(), "git executable not available in this environment")
class EnvironmentTests(MarkerCase):
    HOSTILE = ("GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_DIR", "GIT_CONFIG_PARAMETERS",
               "GIT_CONFIG_COUNT", "GIT_EXEC_PATH")
    ALLOWED = {"PATH", "SYSTEMROOT", "TEMP", "TMP", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL",
               "GIT_CONFIG_SYSTEM", "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT", "LC_ALL"}

    def hostile_parent(self, decoy):
        return {
            "GIT_EXTERNAL_DIFF": self.cmd("ext_env"),
            "GIT_PAGER": self.cmd("pager_env"),
            "GIT_DIR": str(decoy / ".git"),
            "GIT_CONFIG_PARAMETERS": "'diff.external'='%s'" % self.cmd("params"),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "filter.u.clean",
            "GIT_CONFIG_VALUE_0": self.cmd("count"),
            "GIT_WORK_TREE": str(decoy),
            "GIT_INDEX_FILE": str(decoy / "no-such-index"),
            "GIT_EXEC_PATH": str(self.marker_dir / "no-such-exec-path"),
        }

    def test_child_environment_has_no_hostile_variable_and_nothing_outside_the_allowed_set(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo, TempGitRepo({"x.txt": "1\n"}) as decoy:
            parent = self.hostile_parent(decoy.path)
            spy = SpyRunner()
            with mock.patch.dict(os.environ, parent):
                make_adapter(repo.path, runner=spy).retrieve_diff()
            self.assertTrue(spy.calls)
            for _argv, kwargs in spy.calls:
                keys = {k.upper() for k in kwargs["env"]}
                for name in self.HOSTILE:
                    self.assertNotIn(name, keys)
                self.assertEqual(keys - self.ALLOWED, set())
                self.assertEqual(kwargs["env"]["GIT_CONFIG_NOSYSTEM"], "1")
                self.assertEqual(kwargs["env"]["GIT_CONFIG_GLOBAL"], os.devnull)
                self.assertEqual(kwargs["env"]["GIT_CONFIG_SYSTEM"], os.devnull)

    def test_hostile_inherited_variables_do_not_fire_and_do_not_redirect_git(self):
        with TempGitRepo({"a.txt": "1\n", ".gitattributes": "*.txt filter=u\n"}) as repo, \
                TempGitRepo({"decoy.txt": "1\n"}) as decoy:
            repo.write("a.txt", "2\n")
            decoy.write("decoy.txt", "2\n")
            parent = self.hostile_parent(decoy.path)
            parent.pop("GIT_EXEC_PATH")  # would break the control run; covered by the env-key test
            # live control: the same variables, no protections
            for redirecting in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
                parent.pop(redirecting)  # these would aim the control at the decoy
            control_env = dict(_env(), **parent)
            self.plain_git(repo, "diff", "HEAD", env=control_env)
            note_control("inherited GIT_EXTERNAL_DIFF", self.fired("ext_env"))
            note_control("inherited GIT_CONFIG_COUNT filter", self.fired("count"))
            self.fired("params")
            with mock.patch.dict(os.environ, self.hostile_parent(decoy.path)):
                result = make_adapter(repo.path).retrieve_diff()
            for name in ("ext_env", "pager_env", "params", "count"):
                self.assertFalse(self.fired(name), "marker %s present after protected run" % name)
            self.assertEqual([f.path for f in result.files], ["a.txt"])  # GIT_DIR did not redirect


# ================================================================ behavioral hostile fixtures
@unittest.skipUnless(git_available(), "git executable not available in this environment")
class HostileFixtureTests(MarkerCase):
    def run_protected(self, repo):
        result = make_adapter(repo.path).retrieve_diff()
        self.assertEqual(result.files[0].path, "a.txt")
        return result

    def test_external_diff_driver(self):
        with TempGitRepo({"a.txt": "1\n", ".gitattributes": "*.txt diff=x\n"}) as repo:
            repo.git("config", "diff.x.command", self.cmd("ext"))
            repo.write("a.txt", "2\n")
            self.plain_git(repo, "diff", "HEAD")
            note_control("external diff driver", self.fired("ext"))
            self.run_protected(repo)
            self.assertFalse(self.fired("ext"), "external diff marker present")

    def test_textconv_filter(self):
        with TempGitRepo({"a.txt": "1\n", ".gitattributes": "*.txt diff=x\n"}) as repo:
            repo.git("config", "diff.x.textconv", self.cmd("tc"))
            repo.write("a.txt", "2\n")
            self.plain_git(repo, "diff", "HEAD")
            note_control("textconv", self.fired("tc"))
            self.run_protected(repo)
            self.assertFalse(self.fired("tc"), "textconv marker present")

    def test_pager_fixture_cannot_fire_while_output_is_captured(self):
        """The pager protection is verified only by --no-pager in every vector (see
        ArgumentVectorTests). A behavioral pager test is not possible: Git starts no pager
        while standard output is captured. This control is expected not to fire, so the
        pager fixture is recorded as non-evidence; no behavioral claim is made."""
        with TempGitRepo({"a.txt": "1\n"}) as repo:
            repo.git("config", "core.pager", self.cmd("pager"))
            repo.git("config", "pager.diff", "true")
            repo.write("a.txt", "2\n")
            self.plain_git(repo, "diff", "HEAD")
            if note_control("pager (behavioral)", self.fired("pager")):
                self.run_protected(repo)
                self.assertFalse(self.fired("pager"), "pager marker present")
            else:
                self.run_protected(repo)  # still must work; asserts nothing about the pager

    def test_core_fsmonitor_command(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo:
            repo.git("config", "core.fsmonitor", self.cmd("fsm"))
            repo.write("a.txt", "2\n")
            self.plain_git(repo, "diff", "HEAD")
            note_control("core.fsmonitor", self.fired("fsm"))
            self.run_protected(repo)
            self.assertFalse(self.fired("fsm"), "fsmonitor marker present")

    def test_hostile_user_level_configuration(self):
        attributes = "*.txt filter=u\n*.dat filter=p\n"
        with TempGitRepo({"a.txt": "1\n", "b.dat": "1\n", ".gitattributes": attributes}) as repo, \
                tempfile.TemporaryDirectory(prefix="docsync_home_") as home:
            gitconfig = Path(home) / ".gitconfig"
            gitconfig.write_text(
                "[diff]\n\texternal = %s\n[filter \"u\"]\n\tclean = %s\n[filter \"p\"]\n\tprocess = %s\n"
                % (cfg_quote(self.cmd("user_ext")), cfg_quote(self.cmd("user_clean")),
                   cfg_quote(self.cmd("user_proc"))), encoding="utf-8")
            repo.write("a.txt", "2\n")
            repo.write("b.dat", "2\n")
            user_env = {"HOME": home, "USERPROFILE": home, "XDG_CONFIG_HOME": home}
            control_env = dict(_env(), **user_env)
            control_env.pop("GIT_CONFIG_GLOBAL")
            control_env["GIT_CONFIG_GLOBAL"] = str(gitconfig)
            self.plain_git(repo, "diff", "HEAD", env=control_env)
            note_control("user-level diff.external", self.fired("user_ext"))
            note_control("user-level filter.clean", self.fired("user_clean"))
            note_control("user-level filter.process", self.fired("user_proc"))
            with mock.patch.dict(os.environ, dict(user_env, GIT_CONFIG_GLOBAL=str(gitconfig))):
                try:
                    result = make_adapter(repo.path).retrieve_diff()
                    outcome = "proceeded (user-level configuration ignored)"
                except ContentFilterError:
                    result = None
                    outcome = "stopped by the preflight (user-level configuration was read)"
            sys.stderr.write("USER-LEVEL CASE: %s; git %d.%d\n" % ((outcome,) + git_version()))
            for name in ("user_ext", "user_clean", "user_proc"):
                self.assertFalse(self.fired(name), "user-level marker %s present" % name)
            if git_version() >= (2, 32):
                self.assertIsNotNone(result, "expected the run to proceed on Git 2.32 or newer")
                self.assertEqual(result.files[0].path, "a.txt")

    def build_submodule_repo(self, sub_config, sub_attributes):
        src = TempGitRepo({"s.txt": "1\n"})
        sup = TempGitRepo({"a.txt": "1\n"})
        self.addCleanup(src.cleanup)
        self.addCleanup(sup.cleanup)
        sup.git("-c", "protocol.file.allow=always", "submodule", "add", str(src.path), "sub")
        sup.git("config", "diff.submodule", "diff")
        sup.commit("add sub")
        for key, value in sub_config:
            sup.git("-C", "sub", "config", key, value)
        sup.write("sub/.gitattributes", sub_attributes)
        sup.write("sub/s.txt", "2\n")
        sup.git("-C", "sub", "add", "-A")
        sup.git("-C", "sub", "commit", "-q", "-m", "two")
        sup.write("sub/s.txt", "3\n")
        return sup

    def test_submodule_with_hostile_fsmonitor_external_diff_and_driver(self):
        sup = self.build_submodule_repo(
            [("core.fsmonitor", self.cmd("sub_fsm")), ("diff.external", self.cmd("sub_ext")),
             ("diff.x.command", self.cmd("sub_drv"))], "*.txt diff=x\n")
        self.plain_git(sup, "--no-pager", "diff", "HEAD")  # control: diff.submodule=diff, no protections
        names = ("sub_fsm", "sub_ext", "sub_drv")
        for name in names:
            note_control("submodule hostile config: %s" % name, self.fired(name))
        result = make_adapter(sup.path).retrieve_diff()
        for name in names:
            self.assertFalse(self.fired(name), "submodule marker %s present" % name)
        self.assertEqual([(f.path, f.new_mode) for f in result.files], [("sub", "160000")])
        self.assertNotIn("diff --git a/sub/s.txt", result.diff_text)

    def test_submodule_clean_filter_does_not_run_with_ignore_submodules_dirty(self):
        """Regression/protection test. Evidence is limited to the Git version and the
        fixture used here (observed on Git 2.56.0 for Windows); no universal protection
        is claimed.

        A clean filter in a submodule's own configuration (invisible to the preflight) is
        run by the unprotected ``git diff HEAD`` (the control). With
        --ignore-submodules=dirty in the templates the adapter must leave the marker absent.
        Firing is timing/racy-stat dependent, so each trial uses a fresh fixture. The adapter
        runs first (it takes no index lock), then the control on the same fixture proves
        that fixture could fire. If no trial's control fires, NON-EVIDENCE is recorded.
        """
        trials = 5
        live = 0
        for _ in range(trials):
            sup = self.build_submodule_repo([("filter.f.clean", self.cmd("sub_clean"))], "*.txt filter=f\n")
            self.fired("sub_clean")  # clear any marker left by fixture construction
            make_adapter(sup.path).retrieve_diff()
            self.assertFalse(self.fired("sub_clean"), "submodule clean-filter marker present after adapter run")
            self.plain_git(sup, "--no-pager", "diff", "HEAD")
            if self.fired("sub_clean"):
                live += 1
                break
        sys.stderr.write("SUBMODULE CLEAN-FILTER CONTROL: fired in %d of up to %d trials\n" % (live, trials))
        note_control("submodule clean filter (ignore-submodules=dirty)", live > 0)

    def test_moved_submodule_pointer_is_still_reported(self):
        sup = self.build_submodule_repo([], "")
        result = make_adapter(sup.path).retrieve_diff()
        self.assertEqual([(f.path, f.old_mode, f.new_mode) for f in result.files],
                         [("sub", "160000", "160000")])
        self.assertIn("Subproject commit", result.diff_text)
        self.assertIn("sub", result.diff_text)

    def test_limitation_dirty_submodule_with_unchanged_head_is_not_reported(self):
        # Stated limitation: a submodule with a dirty worktree or untracked content whose HEAD
        # commit is unchanged is invisible to the adapter.
        src = TempGitRepo({"s.txt": "1\n"})
        sup = TempGitRepo({"a.txt": "1\n"})
        self.addCleanup(src.cleanup)
        self.addCleanup(sup.cleanup)
        sup.git("-c", "protocol.file.allow=always", "submodule", "add", str(src.path), "sub")
        sup.commit("add sub")
        sup.write("sub/s.txt", "dirty\n")
        sup.write("sub/untracked.txt", "u\n")
        control = self.plain_git(sup, "--no-pager", "diff", "HEAD")
        note_control("dirty submodule is visible without the flag", b"-dirty" in control.stdout)
        result = make_adapter(sup.path).retrieve_diff()
        self.assertEqual(result.files, ())
        self.assertTrue(result.is_empty)
        self.assertNotIn("sub", result.diff_text)


# ================================================================== preflight: positive
@unittest.skipUnless(git_available(), "git executable not available in this environment")
class PreflightPositiveTests(MarkerCase):
    def build(self, files=None):
        repo = TempGitRepo(files or {"a.txt": "1\n", ".gitattributes": "*.txt filter=x\n"})
        self.addCleanup(repo.cleanup)
        return repo

    def assert_stopped(self, repo, key_fragment, origin_fragment, control="diff", marker="clean"):
        repo.write("a.txt", "2\n")
        if control == "diff":
            self.plain_git(repo, "diff", "HEAD")
        else:  # smudge runs on checkout, not on diff
            self.plain_git(repo, "checkout-index", "--force", "--all")
        note_control("preflight fixture %s (%s control)" % (key_fragment, control), self.fired(marker))
        spy = SpyRunner()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(ContentFilterError) as ctx:
                make_adapter(repo.path, runner=spy).retrieve_diff()
        exc = ctx.exception
        self.assertEqual(exc.exit_code, ExitCode.INPUT_OR_GIT)
        message = str(exc)
        self.assertIn(key_fragment, message.lower())
        self.assertIn(origin_fragment, message.lower())
        for text, what in ((message, "message"), (out.getvalue(), "stdout"), (err.getvalue(), "stderr")):
            self.no_leak(text, what)
        self.assertNotIn("protection verified", message)
        self.assertFalse(self.fired(marker), "filter marker present after protected run")
        names = spy.names()
        self.assertEqual(names, ["rev-parse-toplevel", "config-list"])  # no diff, no listing
        return exc

    def test_clean_filter_in_repository_config(self):
        repo = self.build()
        repo.git("config", "filter.x.clean", self.cmd("clean", with_value=True))
        self.assert_stopped(repo, "filter.x.clean", ".git/config")

    def test_smudge_filter(self):
        repo = self.build()
        repo.git("config", "filter.x.smudge", self.cmd("smudge", with_value=True))
        self.assert_stopped(repo, "filter.x.smudge", ".git/config", control="checkout-index", marker="smudge")

    def test_process_filter(self):
        repo = self.build()
        repo.git("config", "filter.x.process", self.cmd("proc", with_value=True))
        self.assert_stopped(repo, "filter.x.process", ".git/config", marker="proc")

    def test_filter_in_worktree_config(self):
        repo = self.build()
        repo.git("config", "extensions.worktreeConfig", "true")
        repo.git("config", "--worktree", "filter.x.clean", self.cmd("clean", with_value=True))
        self.assert_stopped(repo, "filter.x.clean", "config.worktree")

    def test_filter_in_an_included_file(self):
        repo = self.build()
        extra = repo.path / ".git" / "extra.cfg"
        repo.git("config", "-f", str(extra), "filter.x.clean", self.cmd("clean", with_value=True))
        repo.git("config", "include.path", "extra.cfg")
        self.assert_stopped(repo, "filter.x.clean", "extra.cfg")

    def test_filter_name_containing_dots(self):
        repo = self.build({"a.txt": "1\n", ".gitattributes": "*.txt filter=a.b.c\n"})
        repo.git("config", "filter.a.b.c.clean", self.cmd("clean", with_value=True))
        self.assert_stopped(repo, "filter.a.b.c.clean", ".git/config")

    def test_upper_case_section_and_variable(self):
        repo = self.build()
        with open(repo.path / ".git" / "config", "a", encoding="utf-8") as fh:
            fh.write('[FILTER "x"]\n\tCLEAN = %s\n' % cfg_quote(self.cmd("clean", with_value=True)))
        self.assert_stopped(repo, "filter.x.clean", ".git/config")

    def test_filter_name_containing_an_equals_sign_is_still_refused(self):
        repo = self.build({"a.txt": "1\n", ".gitattributes": "*.txt filter=p=q\n"})
        repo.git("config", "filter.p=q.clean", self.cmd("clean", with_value=True))
        exc = self.assert_stopped(repo, "unusual character", ".git/config")
        self.assertIsNone(exc.key)

    def test_origin_path_containing_a_tab_does_not_hide_a_filter(self):
        listing = ("file:.git/config\tcore.repositoryformatversion=0\n"
                   "file:.git/we\tird.cfg\tfilter.x.clean=%s\n" % VALUE_TOKEN).encode()
        verdict = check_config_listing(listing)
        self.assertEqual(verdict[0], "filter")


# ================================================================ preflight: ordering etc.
class PreflightFailClosedTests(unittest.TestCase):
    REPO = "file:.git/config\tcore.repositoryformatversion=0\n"

    def run_preflight(self, runner):
        return make_adapter(".", runner=runner).preflight()

    def assert_unverified(self, runner, check):
        with self.assertRaises(PreflightUnverifiedError) as ctx:
            self.run_preflight(runner)
        exc = ctx.exception
        self.assertEqual(exc.exit_code, ExitCode.INPUT_OR_GIT)
        message = str(exc)
        self.assertIn("content-filter protection could not be verified", message)
        self.assertIn(check, message)
        self.assertNotIn("protection verified", message.replace("could not be verified", ""))
        self.assertFalse(VALUE_TOKEN in message, "a value leaked into the message")
        self.assertEqual(exc.check, check)
        return exc

    def test_command_exits_non_zero(self):
        self.assert_unverified(StubRunner(stdout=(self.REPO).encode(), returncode=128), "command failed or timed out")

    def test_command_times_out(self):
        runner = StubRunner(raises=subprocess.TimeoutExpired(["git"], 1))
        self.assert_unverified(runner, "command failed or timed out")

    def test_empty_output(self):
        self.assert_unverified(StubRunner(stdout=b""), "repository configuration not found in output")

    def test_line_without_a_tab(self):
        out = (self.REPO + "file:.git/config core.x=1\n").encode()
        self.assert_unverified(StubRunner(stdout=out), "output not parseable")

    def test_truncated_line(self):
        out = (self.REPO + "file:.git/con").encode()
        self.assert_unverified(StubRunner(stdout=out), "output not parseable")

    def test_unknown_origin_type(self):
        out = (self.REPO + "network:somewhere\tcore.x=1\n").encode()
        self.assert_unverified(StubRunner(stdout=out), "unknown origin type")

    def test_origin_without_a_colon(self):
        out = (self.REPO + "file\tcore.x=1\n").encode()
        self.assert_unverified(StubRunner(stdout=out), "unknown origin type")

    def test_output_lacking_the_repository_record(self):
        out = b"command line:\tcore.fsmonitor=false\n"
        self.assert_unverified(StubRunner(stdout=out), "repository configuration not found in output")

    def test_repository_record_must_come_from_a_file_origin(self):
        out = b"command line:\tcore.repositoryformatversion=0\n"
        self.assert_unverified(StubRunner(stdout=out), "repository configuration not found in output")

    def test_multi_line_value_is_refused(self):
        out = (self.REPO + "file:.git/config\tcore.multi=first\nsecond line\n").encode()
        self.assert_unverified(StubRunner(stdout=out), "output not parseable")

    def test_nul_byte_is_not_parseable(self):
        self.assert_unverified(StubRunner(stdout=(self.REPO + "\0").encode()), "output not parseable")

    def test_git_missing_is_unverified(self):
        self.assert_unverified(StubRunner(raises=FileNotFoundError()), "command failed or timed out")

    def test_a_clean_listing_verifies_and_crlf_is_tolerated(self):
        for out in (self.REPO, self.REPO.replace("\n", "\r\n") + "\r\n"):
            self.assertIsNone(self.run_preflight(StubRunner(stdout=out.encode())))

    def test_all_four_origin_types_are_accepted(self):
        out = (self.REPO + "command line:\tcore.fsmonitor=false\nstandard input:\ta.b=c\nblob:abc\td.e=f\n").encode()
        self.assertIsNone(self.run_preflight(StubRunner(stdout=out)))

    def test_a_filter_is_named_even_when_the_listing_is_otherwise_incomplete(self):
        out = ("file:.git/config\tfilter.x.clean=%s\n" % VALUE_TOKEN).encode()
        with self.assertRaises(ContentFilterError) as ctx:
            self.run_preflight(StubRunner(stdout=out))
        self.assertFalse(VALUE_TOKEN in str(ctx.exception), "value leaked")

    def test_the_preflight_runs_only_the_config_template(self):
        runner = StubRunner(stdout=self.REPO.encode())
        self.run_preflight(runner)
        self.assertEqual([match_template(c[1:]) for c in runner.calls], ["config-list"])


@unittest.skipUnless(git_available(), "git executable not available in this environment")
class PreflightFailClosedRealGitTests(MarkerCase):
    def assert_stops_before_any_diff(self, repo, exc_type=PreflightUnverifiedError):
        spy = SpyRunner()
        with self.assertRaises(gitadapter.GitAdapterError) as ctx:
            make_adapter(repo.path, runner=spy).retrieve_diff()
        self.assertEqual(ctx.exception.exit_code, ExitCode.INPUT_OR_GIT)
        for name in spy.names():
            self.assertIn(name, ("rev-parse-toplevel", "config-list"))
        return ctx.exception

    def test_corrupted_repository_config_fails_the_command(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo:
            with open(repo.path / ".git" / "config", "a", encoding="utf-8") as fh:
                fh.write("[this is not valid\n")
            with self.assertRaises(PreflightUnverifiedError) as ctx:
                make_adapter(repo.path).preflight()
            self.assertIn("command failed or timed out", str(ctx.exception))
            self.assert_stops_before_any_diff(repo)

    def test_multi_line_value_in_a_real_repository_is_refused(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo:
            with open(repo.path / ".git" / "config", "a", encoding="utf-8") as fh:
                fh.write('[core]\n\tmulti = "first\\nsecond"\n')
            with self.assertRaises(PreflightUnverifiedError) as ctx:
                make_adapter(repo.path).preflight()
            self.assertEqual(ctx.exception.check, "output not parseable")
            exc = self.assert_stops_before_any_diff(repo)
            self.assertNotIn("first", str(exc))

    def test_timeout_in_a_full_run_makes_no_diff_call(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo:
            calls = []

            def runner(argv, **kwargs):
                calls.append(match_template(argv[1:]))
                if match_template(argv[1:]) == "config-list":
                    raise subprocess.TimeoutExpired(argv, 1)
                return subprocess.run(argv, **kwargs)

            with self.assertRaises(PreflightUnverifiedError):
                make_adapter(repo.path, runner=runner).retrieve_diff()
            self.assertEqual(calls, ["rev-parse-toplevel", "config-list"])


@unittest.skipUnless(git_available(), "git executable not available in this environment")
class PreflightNegativeTests(MarkerCase):
    def proceeds(self, repo):
        spy = SpyRunner()
        result = make_adapter(repo.path, runner=spy).retrieve_diff()
        self.assertEqual(spy.names()[-4:], ["diff-raw", "diff-numstat", "diff-text", "ls-files-others"])
        return result

    def test_attribute_bound_to_a_filter_with_no_defined_command(self):
        with TempGitRepo({"a.txt": "1\n", ".gitattributes": "*.txt filter=ghost\n"}) as repo:
            repo.write("a.txt", "2\n")
            self.assertEqual([f.path for f in self.proceeds(repo).files], ["a.txt"])

    def test_repository_with_no_filters(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo:
            repo.write("a.txt", "2\n")
            self.assertEqual([f.path for f in self.proceeds(repo).files], ["a.txt"])

    def test_lookalike_keys_proceed(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo:  # no attribute binding: a bound required filter with no command fails in Git
            repo.git("config", "filter.x.required", "true")
            repo.git("config", "filterx.y.clean", self.cmd("look1"))
            repo.git("config", "diff.x.clean", self.cmd("look2"))
            repo.git("config", "filter.x.cleaner", self.cmd("look3"))
            repo.write("a.txt", "2\n")
            self.assertEqual([f.path for f in self.proceeds(repo).files], ["a.txt"])
            for name in ("look1", "look2", "look3"):
                self.assertFalse(self.fired(name), "lookalike marker present")

    def test_linked_worktree(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo, tempfile.TemporaryDirectory(prefix="docsync_wt_") as tmp:
            wt = Path(tmp) / "wt"
            repo.git("worktree", "add", "-q", str(wt), "-b", "wtbranch")
            (wt / "a.txt").write_text("2\n", encoding="utf-8")
            result = make_adapter(wt).retrieve_diff()
            self.assertEqual([f.path for f in result.files], ["a.txt"])

    def test_value_text_that_looks_like_a_filter_key_is_accepted(self):
        # a value such as core.note=x.filter.y.clean=z is accepted: the key is core.note,
        # which is not a filter key, so the text inside the value does not matter
        out = b"file:.git/config\tcore.repositoryformatversion=0\nfile:.git/config\tcore.note=x.filter.y.clean=z\n"
        self.assertIsNone(check_config_listing(out))

    def test_known_over_refusal_required_key_whose_value_ends_with_run_clean(self):
        # KNOWN over-refusal, recorded and not changed: the key filter.x.required is not a
        # command key, but its value ends with "run.clean", and the conservative scan of the
        # whole line refuses it. This fails safe (a refusal, never a miss).
        out = b"file:.git/config\tfilter.x.required=run.clean\n"
        verdict = check_config_listing(out)
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict[0], "filter")


# ==================================================================== diff retrieval
@unittest.skipUnless(git_available(), "git executable not available in this environment")
class DiffRetrievalTests(unittest.TestCase):
    def collect(self, repo):
        return make_adapter(repo.path).retrieve_diff()

    def by_path(self, result):
        return {f.path: f for f in result.files}

    def test_staged_and_unstaged_changes_are_both_returned(self):
        with TempGitRepo({"staged.py": "a=1\n", "unstaged.py": "b=1\n", "both.py": "c=1\n"}) as repo:
            repo.write("staged.py", "a=2\n")
            repo.git("add", "staged.py")
            repo.write("unstaged.py", "b=2\nb2=3\n")
            repo.write("both.py", "c=2\n")
            repo.git("add", "both.py")
            repo.write("both.py", "c=3\n")
            result = self.collect(repo)
            files = self.by_path(result)
            self.assertEqual(sorted(files), ["both.py", "staged.py", "unstaged.py"])
            self.assertEqual((files["staged.py"].added, files["staged.py"].deleted), (1, 1))
            self.assertEqual((files["unstaged.py"].added, files["unstaged.py"].deleted), (2, 1))
            self.assertEqual(files["both.py"].status, "M")
            self.assertIn("+c=3", result.diff_text)
            self.assertNotIn("+c=2", result.diff_text)  # HEAD to working tree, one combined diff
            self.assertIsInstance(result, DiffResult)
            self.assertEqual(result.status, "changes")

    def test_a_rename_is_one_entry(self):
        with TempGitRepo({"old.txt": "line1\nline2\nline3\nline4\n"}) as repo:
            repo.git("mv", "old.txt", "new.txt")
            result = self.collect(repo)
            self.assertEqual(len(result.files), 1)
            f = result.files[0]
            self.assertEqual((f.path, f.old_path, f.status, f.added, f.deleted), ("new.txt", "old.txt", "R100", 0, 0))

    def test_a_rename_with_edits_is_one_entry_with_counts(self):
        with TempGitRepo({"old.txt": "l1\nl2\nl3\nl4\nl5\nl6\n"}) as repo:
            repo.git("mv", "old.txt", "new.txt")
            repo.write("new.txt", "l1\nl2\nl3\nl4\nl5\nCHANGED\n")
            f = self.collect(repo).files[0]
            self.assertEqual((f.path, f.old_path, f.status[0], f.added, f.deleted), ("new.txt", "old.txt", "R", 1, 1))

    def test_a_deleted_file(self):
        with TempGitRepo({"gone.txt": "1\n2\n", "keep.txt": "k\n"}) as repo:
            repo.delete("gone.txt")
            f = self.collect(repo).files[0]
            self.assertEqual((f.path, f.status, f.added, f.deleted, f.new_mode), ("gone.txt", "D", 0, 2, "000000"))

    def test_a_binary_change_has_unknown_counts_never_zero(self):
        with TempGitRepo({"b.bin": b"\x00\x01\x02"}) as repo:
            repo.write("b.bin", b"\x00\x09\x09\x09")
            f = self.collect(repo).files[0]
            self.assertTrue(f.binary)
            self.assertIsNone(f.added)
            self.assertIsNone(f.deleted)
            self.assertIsNone(f.changed_lines)

    def test_a_staged_mode_only_change(self):
        with TempGitRepo({"run.sh": "echo hi\n"}) as repo:
            repo.git("update-index", "--chmod=+x", "run.sh")
            # ``git diff HEAD`` compares HEAD with the working tree: where the file system tracks the
            # executable bit (Linux), the file on disk must also be executable or the change cancels out.
            os.chmod(repo.path / "run.sh", 0o755)
            f =self.collect(repo).files[0]
            self.assertEqual((f.path, f.status, f.old_mode, f.new_mode, f.added, f.deleted, f.binary),
                             ("run.sh", "M", "100644", "100755", 0, 0, False))

    def test_a_submodule_change_has_mode_160000(self):
        with TempGitRepo({"s.txt": "1\n"}) as src, TempGitRepo({"a.txt": "1\n"}) as sup:
            sup.git("-c", "protocol.file.allow=always", "submodule", "add", str(src.path), "sub")
            sup.commit("add sub")
            sup.write("sub/s.txt", "2\n")
            sup.git("-C", "sub", "add", "-A")
            sup.git("-C", "sub", "commit", "-q", "-m", "two")
            f = self.collect(sup).files[0]
            self.assertEqual((f.path, f.status, f.old_mode, f.new_mode), ("sub", "M", "160000", "160000"))

    def test_untracked_files_are_listed_by_name_and_ignored_files_are_not(self):
        with TempGitRepo({"a.txt": "1\n", ".gitignore": "ignored.log\n"}) as repo:
            repo.write("a.txt", "2\n")
            repo.write("fresh.txt", "UNTRACKED_CONTENT_TOKEN\n")
            repo.write("ignored.log", "IGNORED_CONTENT_TOKEN\n")
            repo.write("dir/other.txt", "x\n")
            spy = SpyRunner()
            result = make_adapter(repo.path, runner=spy).retrieve_diff()
            self.assertEqual(result.untracked, ("dir/other.txt", "fresh.txt"))
            self.assertEqual([f.path for f in result.files], ["a.txt"])
            blob = repr(result)
            self.assertNotIn("UNTRACKED_CONTENT_TOKEN", blob)
            self.assertNotIn("IGNORED_CONTENT_TOKEN", blob)
            self.assertNotIn("ignored.log", blob)
            self.assertEqual(spy.names().count("ls-files-others"), 1)  # names only; no other read path

    def test_repository_with_no_commits_is_a_git_error(self):
        with TempGitRepo({"a.txt": "1\n"}, commit=False) as repo:
            with self.assertRaises(NoHeadError) as ctx:
                self.collect(repo)
            self.assertEqual(ctx.exception.exit_code, ExitCode.INPUT_OR_GIT)

    def test_empty_change_set_is_reported_and_untracked_names_still_listed(self):
        with TempGitRepo({"a.txt": "1\n"}) as repo:
            repo.write("only-untracked.txt", "u\n")
            result = self.collect(repo)
            self.assertEqual(result.files, ())
            self.assertTrue(result.is_empty)
            self.assertEqual(result.status, EMPTY_CHANGE_SET)
            self.assertEqual(result.status, "empty change set")
            self.assertEqual(result.untracked, ("only-untracked.txt",))
            self.assertEqual(result.diff_text, "")

    def test_paths_with_spaces_and_non_ascii_names(self):
        with TempGitRepo({"my file.txt": "1\n", "café.txt": "1\n"}) as repo:
            repo.write("my file.txt", "2\n")
            repo.write("café.txt", "2\n")
            self.assertEqual(sorted(f.path for f in self.collect(repo).files), ["café.txt", "my file.txt"])

    def test_not_a_git_repository_is_exit_3_and_nothing_else_runs(self):
        with tempfile.TemporaryDirectory(prefix="docsync_plain_") as tmp:
            spy = SpyRunner()
            with self.assertRaises(NotARepositoryError):
                make_adapter(tmp, runner=spy).retrieve_diff()
            self.assertEqual(spy.names(), ["rev-parse-toplevel"])

    def test_subdirectory_of_a_repository_is_refused_before_the_preflight(self):
        with TempGitRepo({"sub/a.txt": "1\n"}) as repo:
            spy = SpyRunner()
            with self.assertRaises(gitadapter.NotRepositoryRootError):
                make_adapter(repo.path / "sub", runner=spy).retrieve_diff()
            self.assertEqual(spy.names(), ["rev-parse-toplevel"])


class DiffParsingTests(unittest.TestCase):
    """Record formats with in-memory bytes (plan T05, record formats)."""

    def test_raw_rename_and_copy_have_two_paths(self):
        raw = (b":100644 100644 aaa bbb R086\0old.txt\0new.txt\0"
               b":100644 100644 aaa ccc C075\0src.txt\0copy.txt\0"
               b":100644 000000 aaa 000 D\0gone.txt\0")
        entries = gitadapter._parse_raw(raw)
        self.assertEqual([(e[2], e[3], e[4]) for e in entries],
                         [("R086", "old.txt", "new.txt"), ("C075", "src.txt", "copy.txt"), ("D", None, "gone.txt")])

    def test_numstat_rename_leaves_the_path_empty_and_follows_with_two_paths(self):
        raw = b"1\t2\t\0old.txt\0new.txt\0-\t-\tb.bin\0"
        self.assertEqual(gitadapter._parse_numstat(raw), {"new.txt": (1, 2), "b.bin": (None, None)})

    def test_malformed_records_are_a_clear_git_error(self):
        runner = StubRunner(stdout=b"garbage")

        def run(argv, **kwargs):
            name = match_template(argv[1:])
            if name == "config-list":
                return subprocess.CompletedProcess(argv, 0, b"file:.git/config\tcore.repositoryformatversion=0\n", b"")
            if name == "rev-parse-toplevel":
                return subprocess.CompletedProcess(argv, 0, os.path.abspath(".").encode(), b"")
            return runner(argv, **kwargs)

        with self.assertRaises(GitCommandError) as ctx:
            make_adapter(".", runner=run).retrieve_diff()
        self.assertEqual(ctx.exception.exit_code, ExitCode.INPUT_OR_GIT)
        self.assertNotIn("garbage", str(ctx.exception))

    def test_raw_entry_without_line_counts_is_an_error(self):
        with self.assertRaises(ValueError):
            gitadapter._changed_files(b":100644 100644 a b M\0x.txt\0", b"")


if __name__ == "__main__":
    unittest.main()
