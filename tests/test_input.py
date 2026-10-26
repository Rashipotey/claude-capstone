"""T03 tests: Input Resolver (AC-05, NFR-02, E1, OQ-1)."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docsync import input as input_stage
from docsync import redact as redact_stage
from docsync.contracts import ChangeRequest, ExitCode, InputOrGitError
from docsync.input import resolve_input

# A fake, obviously non-real secret-like value.
FAKE_SECRET = "FAKEVALUE0123456789"


def resolve(path=None, target=None):
    return resolve_input(path, target, redactor=redact_stage.redact)


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def assert_input_error(self, path):
        with self.assertRaises(InputOrGitError) as ctx:
            resolve(path)
        self.assertEqual(ctx.exception.exit_code, ExitCode.INPUT_OR_GIT)
        self.assertEqual(ctx.exception.stage, "input")
        return str(ctx.exception)

    def test_valid_directory(self):
        request = resolve(str(self.root))
        self.assertIsInstance(request, ChangeRequest)
        self.assertEqual(os.path.normcase(request.repo_path), os.path.normcase(os.path.abspath(self.root)))
        self.assertIsNone(request.target)

    def test_target_is_carried_through(self):
        self.assertEqual(resolve(str(self.root), "README.md").target, "README.md")

    def test_pathlike_accepted(self):
        self.assertIsInstance(resolve(self.root), ChangeRequest)

    def test_default_is_current_directory(self):
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        for arg in (None, ""):
            request = resolve(arg)
            self.assertEqual(os.path.normcase(os.path.realpath(request.repo_path)),
                             os.path.normcase(os.path.realpath(self.root)))

    def test_nonexistent_path_names_the_path(self):
        missing = str(self.root / "no_such_dir")
        message = self.assert_input_error(missing)
        self.assertIn("no_such_dir", message)
        self.assertIn("does not exist", message)

    def test_regular_file_instead_of_directory(self):
        file_path = self.root / "afile.txt"
        file_path.write_text("x", encoding="utf-8")
        message = self.assert_input_error(str(file_path))
        self.assertIn("afile.txt", message)
        self.assertIn("not a directory", message)

    def test_unreadable_directory_simulated(self):
        # Portable: simulate the OS refusing to list the directory.
        with mock.patch("os.scandir", side_effect=PermissionError("denied")):
            message = self.assert_input_error(str(self.root))
        self.assertIn("not readable", message)

    def test_null_character_is_a_clear_error(self):
        message = self.assert_input_error("bad\x00path")
        self.assertIn("invalid", message)

    def test_error_message_passes_through_the_redactor(self):
        calls = []

        def spy(text):
            calls.append(text)
            return text.replace("no_such_dir", "<masked>")

        with self.assertRaises(InputOrGitError) as ctx:
            resolve_input(str(self.root / "no_such_dir"), redactor=spy)
        self.assertTrue(calls)
        self.assertNotIn("no_such_dir", str(ctx.exception))
        self.assertIn("<masked>", str(ctx.exception))

    def test_secret_like_path_is_masked_in_message(self):
        path = str(self.root / ("password=" + FAKE_SECRET))
        with self.assertRaises(InputOrGitError) as ctx:
            resolve(path)
        self.assertNotIn(FAKE_SECRET, str(ctx.exception))

    def test_redactor_is_required_and_must_be_callable(self):
        with self.assertRaises(TypeError):
            resolve_input(str(self.root))
        with self.assertRaises(TypeError):
            resolve_input(str(self.root), redactor=None)

    def test_no_git_or_subprocess_call_on_success_or_failure(self):
        missing = str(self.root / "missing")
        with mock.patch.object(subprocess, "run") as run, \
                mock.patch.object(subprocess, "Popen") as popen, \
                mock.patch.object(subprocess, "check_output") as check_output, \
                mock.patch("os.system") as system:
            resolve(str(self.root))
            with self.assertRaises(InputOrGitError):
                resolve(missing)
            with self.assertRaises(InputOrGitError):
                resolve(str(self.root / "missing2"))
        for spy in (run, popen, check_output, system):
            spy.assert_not_called()

    def test_module_does_not_import_subprocess(self):
        self.assertFalse(hasattr(input_stage, "subprocess"))
        source = Path(input_stage.__file__).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)

    def test_public_api(self):
        self.assertEqual(input_stage.__all__, ["resolve_input"])


if __name__ == "__main__":
    unittest.main()
