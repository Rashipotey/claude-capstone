"""T04 tests: Git Adapter core (templates, environment, runner, root check, typed errors)."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from docsync import gitadapter
from docsync.contracts import ExitCode, InputOrGitError
from docsync.gitadapter import (
    TEMPLATES, GitAdapter, GitCommandError, GitMissingError, GitRejectedError, GitTimeoutError,
    NoHeadError, NotARepositoryError, NotRepositoryRootError, build_environment, match_template,
)
from tests.helpers.gitrepo import TempGitRepo, git_available

G = ("--no-pager", "-c", "core.fsmonitor=false")
D = ("--no-ext-diff", "--no-textconv", "--no-color", "--submodule=short",
     "--ignore-submodules=dirty", "--find-renames", "--find-copies", "--")


def mask(text):
    return text.replace("SECRETVALUE", "[REDACTED]")


class FakeRunner:
    """Records calls; returns a canned result or raises."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0, raises=None):
        self.calls = []
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.raises = raises

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        return self.result


def adapter(path=".", **kw):
    kw.setdefault("redactor", mask)
    return GitAdapter(path, **kw)


class TemplateTests(unittest.TestCase):
    def test_there_are_exactly_six_templates_with_the_planned_forms(self):
        self.assertEqual(len(TEMPLATES), 6)
        self.assertEqual(set(TEMPLATES.values()), {
            G + ("rev-parse", "--show-toplevel"),
            G + ("config", "--list", "--show-origin"),
            G + ("diff", "HEAD", "--raw", "-z") + D,
            G + ("diff", "HEAD", "--numstat", "-z") + D,
            G + ("diff", "HEAD") + D,
            G + ("ls-files", "--others", "--exclude-standard", "-z"),
        })

    def test_every_template_has_no_pager_and_only_the_fsmonitor_override(self):
        for name, vector in TEMPLATES.items():
            self.assertEqual(vector[:3], G, name)
            self.assertEqual(vector.count("-c"), 1, name)

    def test_each_template_is_accepted_and_run_by_the_runner(self):
        for name, vector in TEMPLATES.items():
            runner = FakeRunner(stdout=b"x")
            out = adapter(runner=runner).run(vector)
            self.assertEqual(out, b"x", name)
            self.assertEqual(match_template(vector), name)
            argv, kwargs = runner.calls[0]
            self.assertEqual(argv, ["git", *vector], name)

    def assert_rejected(self, args):
        runner = FakeRunner()
        with self.assertRaises(GitRejectedError) as ctx:
            adapter(runner=runner).run(args)
        self.assertEqual(runner.calls, [], "a rejected vector must not run")
        self.assertEqual(ctx.exception.exit_code, ExitCode.INPUT_OR_GIT)

    def test_forbidden_subcommands_are_rejected(self):
        for sub in ("commit", "push", "merge", "apply", "checkout", "reset"):
            self.assert_rejected(G + (sub,))
            self.assert_rejected((sub,))
            self.assert_rejected(G + (sub, "-m", "x"))

    def test_diff_without_no_ext_diff_is_rejected(self):
        for name in ("diff-raw", "diff-numstat", "diff-text"):
            vector = tuple(a for a in TEMPLATES[name] if a != "--no-ext-diff")
            self.assert_rejected(vector)

    def test_diff_with_an_extra_option_or_path_is_rejected(self):
        self.assert_rejected(TEMPLATES["diff-text"] + ("--output=x",))
        self.assert_rejected(TEMPLATES["diff-text"] + ("README.md",))
        self.assert_rejected(TEMPLATES["diff-text"][:-1] + ("--ext-diff", "--"))
        self.assert_rejected(TEMPLATES["diff-text"][:-1] + ("--textconv", "--"))

    def test_config_forms_other_than_the_preflight_are_rejected(self):
        base = G + ("config",)
        self.assert_rejected(base + ("--global", "user.name", "x"))
        self.assert_rejected(base + ("--unset", "core.fsmonitor"))
        self.assert_rejected(base + ("--edit",))
        self.assert_rejected(base + ("--file", "other.cfg", "--list"))
        self.assert_rejected(base + ("--list",))
        self.assert_rejected(base + ("--list", "--show-origin", "--file", "x"))
        self.assert_rejected(base + ("user.name",))

    def test_other_c_options_are_rejected(self):
        for value in ("core.fsmonitor=true", "core.pager=cat", "alias.x=!sh", "core.sshCommand=x"):
            vector = ("--no-pager", "-c", value, "rev-parse", "--show-toplevel")
            self.assert_rejected(vector)
        self.assert_rejected(G + ("-c", "core.editor=x", "rev-parse", "--show-toplevel"))
        self.assert_rejected(("-c", "core.fsmonitor=false", "rev-parse", "--show-toplevel"))  # no --no-pager

    def test_non_sequence_and_empty_vectors_are_rejected(self):
        self.assert_rejected(())
        self.assert_rejected(None)
        self.assert_rejected(12)

    def test_diff_vectors_without_ignore_submodules_dirty_are_rejected(self):
        old_d = tuple(a for a in D if a != "--ignore-submodules=dirty")
        for tail in (("--raw", "-z"), ("--numstat", "-z"), ()):
            self.assert_rejected(G + ("diff", "HEAD") + tail + old_d)
        for wrong in ("--ignore-submodules=all", "--ignore-submodules=untracked"):
            mutated = tuple(wrong if a == "--ignore-submodules=dirty" else a for a in D)
            self.assert_rejected(G + ("diff", "HEAD") + mutated)

    def test_unknown_template_name_is_rejected(self):
        with self.assertRaises(GitRejectedError):
            gitadapter.build_vector("commit")


class RunnerTests(unittest.TestCase):
    def test_no_call_uses_a_shell_and_the_environment_is_controlled(self):
        runner = FakeRunner()
        adapter("somewhere", runner=runner).run(TEMPLATES["config-list"])
        argv, kwargs = runner.calls[0]
        self.assertIs(kwargs["shell"], False)
        self.assertIsInstance(argv, list)
        self.assertEqual(kwargs["timeout"], gitadapter.TIMEOUT_SECONDS)
        self.assertTrue(os.path.isabs(kwargs["cwd"]))
        self.assertEqual(kwargs["env"]["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertIn("--no-pager", argv)

    def test_timeout_value_is_fixed_and_positive(self):
        self.assertEqual(gitadapter.TIMEOUT_SECONDS, 30)

    def test_timeout_is_a_typed_error(self):
        runner = FakeRunner(raises=subprocess.TimeoutExpired(["git"], 30))
        with self.assertRaises(GitTimeoutError) as ctx:
            adapter(runner=runner).run(TEMPLATES["diff-text"])
        self.assertEqual(ctx.exception.exit_code, ExitCode.INPUT_OR_GIT)
        self.assertIn("timed out", ctx.exception.message)

    def test_git_executable_not_found_is_a_typed_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GitMissingError) as ctx:
                adapter(tmp, executable="docsync-no-such-git-executable").run(TEMPLATES["rev-parse-toplevel"])
        self.assertEqual(ctx.exception.exit_code, ExitCode.INPUT_OR_GIT)

    def test_oserror_starting_git_is_git_missing(self):
        runner = FakeRunner(raises=PermissionError("denied"))
        with self.assertRaises(GitMissingError):
            adapter(runner=runner).run(TEMPLATES["rev-parse-toplevel"])

    def test_non_zero_exit_reports_step_and_code_but_no_output(self):
        runner = FakeRunner(stdout=b"FILECONTENT", stderr=b"fatal: something FILECONTENT", returncode=129)
        with self.assertRaises(GitCommandError) as ctx:
            adapter(runner=runner).run(TEMPLATES["ls-files-others"])
        err = ctx.exception
        self.assertEqual((err.step, err.returncode), ("ls-files", 129))
        self.assertIn("ls-files", err.message)
        self.assertIn("129", err.message)
        self.assertNotIn("FILECONTENT", str(err))
        self.assertEqual(err.exit_code, ExitCode.INPUT_OR_GIT)

    def test_no_head_is_a_typed_error(self):
        runner = FakeRunner(stderr=b"fatal: ambiguous argument 'HEAD': unknown revision or path", returncode=128)
        with self.assertRaises(NoHeadError):
            adapter(runner=runner).run(TEMPLATES["diff-raw"])

    def test_messages_pass_through_the_redactor(self):
        with self.assertRaises(GitRejectedError):
            adapter(runner=FakeRunner()).run(G + ("SECRETVALUE",))
        runner = FakeRunner(stderr=b"fatal: not a git repository", returncode=128)
        a = adapter("/tmp/SECRETVALUE", runner=runner)
        with self.assertRaises(NotARepositoryError) as ctx:
            a.run(TEMPLATES["rev-parse-toplevel"])
        self.assertNotIn("SECRETVALUE", str(ctx.exception))

    def test_root_error_message_redacts_the_path(self):
        runner = FakeRunner(stdout=b"/elsewhere\n")
        with self.assertRaises(NotRepositoryRootError) as ctx:
            adapter("/x/SECRETVALUE", runner=runner).check_root()
        self.assertNotIn("SECRETVALUE", str(ctx.exception))
        self.assertIn("[REDACTED]", str(ctx.exception))

    def test_constructor_requires_a_redactor_and_a_path(self):
        with self.assertRaises(TypeError):
            GitAdapter(".", redactor=None)
        with self.assertRaises(TypeError):
            GitAdapter("", redactor=mask)
        with self.assertRaises(TypeError):
            GitAdapter(None, redactor=mask)


class EnvironmentTests(unittest.TestCase):
    HOSTILE = {
        "GIT_EXTERNAL_DIFF": "evil", "GIT_PAGER": "evil", "GIT_DIR": "x", "GIT_WORK_TREE": "x",
        "GIT_INDEX_FILE": "x", "GIT_CONFIG_PARAMETERS": "'core.pager=evil'", "GIT_CONFIG_COUNT": "1",
        "GIT_EXEC_PATH": "x", "PAGER": "evil", "HOME": "h", "USERPROFILE": "u", "EDITOR": "e",
        "GIT_SSH_COMMAND": "evil", "GIT_ASKPASS": "evil", "XDG_CONFIG_HOME": "x", "API_TOKEN": "t",
    }

    def parent(self):
        return {"PATH": "/bin", "SYSTEMROOT": "C:\\Windows", "TEMP": "t1", "TMP": "t2",
                "GIT_CONFIG_GLOBAL": "/home/me/.gitconfig", **self.HOSTILE}

    def test_only_the_allowed_set_on_windows(self):
        env = build_environment(self.parent(), windows=True, devnull="nul")
        self.assertEqual(env, {
            "PATH": "/bin", "SYSTEMROOT": "C:\\Windows", "TEMP": "t1", "TMP": "t2",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "nul", "GIT_CONFIG_SYSTEM": "nul",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
        })

    def test_only_path_is_passed_through_off_windows(self):
        env = build_environment(self.parent(), windows=False, devnull="/dev/null")
        self.assertEqual(set(env), {
            "PATH", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
            "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT", "LC_ALL",
        })
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")

    def test_hostile_variables_are_absent(self):
        for windows in (True, False):
            env = build_environment(self.parent(), windows=windows)
            for name in self.HOSTILE:
                self.assertNotIn(name, env)
            self.assertNotEqual(env["GIT_CONFIG_GLOBAL"], "/home/me/.gitconfig")

    def test_windows_names_match_case_insensitively(self):
        env = build_environment({"Path": "p", "SystemRoot": "r"}, windows=True)
        self.assertEqual(env["PATH"], "p")
        self.assertEqual(env["SYSTEMROOT"], "r")

    def test_missing_parent_values_are_simply_absent_and_parent_is_not_mutated(self):
        parent = {"GIT_PAGER": "evil"}
        env = build_environment(parent, windows=True)
        self.assertNotIn("PATH", env)
        self.assertEqual(parent, {"GIT_PAGER": "evil"})

    def test_default_adapter_environment_drops_hostile_parent_variables(self):
        saved = {k: os.environ.get(k) for k in ("GIT_EXTERNAL_DIFF", "GIT_PAGER")}
        os.environ["GIT_EXTERNAL_DIFF"] = "evil"
        os.environ["GIT_PAGER"] = "evil"
        try:
            runner = FakeRunner()
            adapter(runner=runner).run(TEMPLATES["config-list"])
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        env = runner.calls[0][1]["env"]
        self.assertNotIn("GIT_EXTERNAL_DIFF", env)
        self.assertNotIn("GIT_PAGER", env)


class RootCheckFakeTests(unittest.TestCase):
    def test_forward_slash_root_equals_resolved_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            printed = os.path.realpath(tmp).replace("\\", "/") + "\n"
            runner = FakeRunner(stdout=printed.encode())
            root = adapter(tmp, runner=runner).check_root()
            self.assertEqual(os.path.normcase(root), os.path.normcase(os.path.realpath(tmp)))

    def test_different_root_is_exit_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(stdout=b"/some/other/place\n")
            with self.assertRaises(NotRepositoryRootError) as ctx:
                adapter(tmp, runner=runner).check_root()
            self.assertEqual(ctx.exception.exit_code, 3)

    def test_empty_output_is_a_failed_step_not_a_root(self):
        with self.assertRaises(GitCommandError):
            adapter(runner=FakeRunner(stdout=b"\n")).check_root()


@unittest.skipUnless(git_available(), "git executable not available in this environment")
class RealGitTests(unittest.TestCase):
    def test_repository_root_is_accepted(self):
        with TempGitRepo({"a.txt": "a\n"}) as repo:
            root = adapter(repo.path, redactor=mask).check_root()
            self.assertEqual(os.path.normcase(root), os.path.normcase(os.path.realpath(repo.path)))

    def test_root_given_with_a_trailing_separator_or_dot_segments(self):
        with TempGitRepo({"a.txt": "a\n"}) as repo:
            (repo.path / "sub").mkdir()
            odd = str(repo.path / "sub" / "..") + os.sep
            adapter(odd).check_root()

    def test_not_a_git_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            # guard: skip if the temp area sits inside some repository
            probe = subprocess.run(["git", "-C", tmp, "rev-parse", "--git-dir"], capture_output=True)
            if probe.returncode == 0:
                self.skipTest("temporary directory is inside a Git repository")
            with self.assertRaises(NotARepositoryError) as ctx:
                adapter(tmp).check_root()
            self.assertEqual(ctx.exception.exit_code, ExitCode.INPUT_OR_GIT)

    def test_subdirectory_of_a_repository_is_exit_3(self):
        with TempGitRepo({"sub/a.txt": "a\n"}) as repo:
            with self.assertRaises(NotRepositoryRootError) as ctx:
                adapter(repo.path / "sub").check_root()
            self.assertEqual(ctx.exception.exit_code, 3)
            self.assertIsInstance(ctx.exception, InputOrGitError)

    def test_linked_worktree_root_is_accepted(self):
        with TempGitRepo({"a.txt": "a\n"}) as repo:
            wt = Path(repo.path).parent / "linked"
            repo.git("worktree", "add", "-q", "--detach", str(wt))
            root = adapter(wt).check_root()
            self.assertEqual(os.path.normcase(root), os.path.normcase(os.path.realpath(wt)))

    def test_path_starting_with_dash_is_data(self):
        with TempGitRepo({"a.txt": "a\n"}) as repo:
            dashed = Path(repo.path).parent / "-opt"
            repo.path.rename(dashed)
            previous = os.getcwd()
            os.chdir(dashed.parent)
            try:
                root = adapter("-opt").check_root()  # relative, starts with "-"
            finally:
                os.chdir(previous)
            self.assertEqual(os.path.normcase(root), os.path.normcase(os.path.realpath(dashed)))
            repo.path = dashed  # let cleanup find it (cleanup removes the parent anyway)

    def test_nonexistent_path_is_a_clear_typed_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(InputOrGitError):
                adapter(os.path.join(tmp, "missing")).check_root()

    def test_no_head_with_real_repository(self):
        with TempGitRepo({"a.txt": "a\n"}, commit=False) as repo:
            a = adapter(repo.path)
            a.check_root()
            with self.assertRaises(NoHeadError) as ctx:
                a.run(TEMPLATES["diff-text"])
            self.assertEqual(ctx.exception.exit_code, 3)

    def test_each_template_runs_against_a_real_repository(self):
        with TempGitRepo({"a.txt": "a\n"}) as repo:
            repo.write("a.txt", "b\n")
            repo.write("new.txt", "n\n")
            a = adapter(repo.path)
            self.assertTrue(a.run(TEMPLATES["rev-parse-toplevel"]).strip())
            self.assertIn(b"core.repositoryformatversion", a.run(TEMPLATES["config-list"]))
            self.assertIn(b"a.txt", a.run(TEMPLATES["diff-raw"]))
            self.assertIn(b"a.txt", a.run(TEMPLATES["diff-numstat"]))
            self.assertIn(b"+b", a.run(TEMPLATES["diff-text"]))
            self.assertIn(b"new.txt", a.run(TEMPLATES["ls-files-others"]))


if __name__ == "__main__":
    unittest.main()
