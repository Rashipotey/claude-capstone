"""T01 tests: the temporary Git repository helper builds repositories with known files."""

import os
import unittest
from pathlib import Path

from tests.helpers.gitrepo import GitUnavailable, TempGitRepo, git_available


@unittest.skipUnless(git_available(), "git executable not found")
class TempGitRepoTests(unittest.TestCase):
    def make(self, *args, **kwargs):
        repo = TempGitRepo(*args, **kwargs)
        self.addCleanup(repo.cleanup)
        return repo

    def test_creates_a_repo_with_known_files(self):
        files = {"README.md": "# Title\n", "docs/guide.md": "guide\n", "pkg/mod.py": "def f():\n    return 1\n"}
        repo = self.make(files)
        self.assertTrue((repo.path / ".git").is_dir())
        self.assertEqual(repo.tracked_files(), sorted(files))
        for rel, content in files.items():
            self.assertEqual(repo.read(rel), content.encode("utf-8"))
        self.assertTrue(repo.has_head())

    def test_binary_content_is_supported(self):
        blob = bytes(range(256))
        repo = self.make({"data.bin": blob})
        self.assertEqual(repo.read("data.bin"), blob)

    def test_can_build_a_repo_without_commits(self):
        repo = self.make({"a.py": "x = 1\n"}, commit=False)
        self.assertFalse(repo.has_head())
        self.assertEqual(repo.tracked_files(), [])
        self.assertTrue((repo.path / "a.py").is_file())

    def test_changes_after_the_initial_commit(self):
        repo = self.make({"a.py": "x = 1\n"})
        repo.write("a.py", "x = 2\n")
        repo.write("new.py", "y = 1\n")
        status = repo.git("status", "--porcelain")
        self.assertIn(" M a.py", status)
        self.assertIn("?? new.py", status)
        repo.commit("second")
        self.assertEqual(repo.tracked_files(), ["a.py", "new.py"])
        repo.delete("new.py")
        self.assertNotIn("new.py", [p for p in os.listdir(repo.path)])

    def test_is_hermetic_no_user_configuration_leaks_in(self):
        repo = self.make({"a.py": "x\n"})
        origins = repo.git("config", "--list", "--show-origin")
        # every record comes from the repository's own configuration or the command line
        for line in origins.splitlines():
            self.assertTrue(line.startswith(("file:.git/config", "command line:")), line)

    def test_cleanup_removes_the_directory_and_is_repeatable(self):
        repo = TempGitRepo({"a.py": "x\n"})
        root = repo.path.parent
        self.assertTrue(root.exists())
        repo.cleanup()
        self.assertFalse(root.exists())
        repo.cleanup()  # a second call is harmless

    def test_context_manager_cleans_up(self):
        with TempGitRepo({"a.py": "x\n"}) as repo:
            root = repo.path.parent
            self.assertTrue(root.exists())
        self.assertFalse(root.exists())

    def test_two_repos_are_independent(self):
        first = self.make({"a.py": "1\n"})
        second = self.make({"a.py": "2\n"})
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(first.read("a.py"), b"1\n")
        self.assertEqual(second.read("a.py"), b"2\n")

    def test_fixture_paths_cannot_escape_the_repository(self):
        repo = self.make()
        for bad in ("../outside.txt", "/abs.txt", "", "a/../../b.txt"):
            with self.assertRaises(ValueError, msg=bad):
                repo.write(bad, "x")
        self.assertFalse((repo.path.parent / "outside.txt").exists())

    def test_failed_setup_leaves_no_directory_behind(self):
        before = set(Path(os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp"))).glob("docsync_fixture_*"))
        with self.assertRaises(ValueError):
            TempGitRepo({"../escape.txt": "x"})
        after = set(Path(os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp"))).glob("docsync_fixture_*"))
        self.assertEqual(after - before, set())

    def test_git_failure_is_reported_with_a_clear_message(self):
        repo = self.make()
        with self.assertRaises(RuntimeError) as ctx:
            repo.git("no-such-subcommand")
        self.assertIn("no-such-subcommand", str(ctx.exception))


class GitUnavailableTests(unittest.TestCase):
    def test_missing_git_raises_a_clear_error(self):
        import shutil
        from unittest import mock

        with mock.patch.object(shutil, "which", return_value=None):
            with self.assertRaises(GitUnavailable):
                TempGitRepo()


if __name__ == "__main__":
    unittest.main()
