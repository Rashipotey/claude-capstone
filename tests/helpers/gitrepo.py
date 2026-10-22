"""Test helper (plan T01): build a temporary Git repository from a small fixture spec.

This is test code, not the tool's Git Adapter. It runs git only to set up fixtures,
in a hermetic environment: no user or system configuration, no prompts, a fixed
identity passed on the command line, and no network. Fixture content is plain text
or bytes written by the test; it never contains real secrets.
"""

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

_PASS_THROUGH = ("PATH", "SYSTEMROOT", "TEMP", "TMP")
_IDENTITY = (
    "-c", "user.name=DocSync Test",
    "-c", "user.email=docsync-test@example.invalid",
    "-c", "commit.gpgsign=false",
    "-c", "core.autocrlf=false",
    "-c", "init.defaultBranch=main",
)


class GitUnavailable(RuntimeError):
    """Raised when the git executable cannot be found."""


def git_available():
    return shutil.which("git") is not None


def _env():
    env = {key: os.environ[key] for key in _PASS_THROUGH if key in os.environ}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
    )
    return env


def _remove_readonly(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


class TempGitRepo:
    """A throwaway Git repository.

    ``files`` maps repository-relative paths (forward slashes) to str or bytes
    content. With ``commit=True`` (the default) the files are committed as the
    initial commit, so ``HEAD`` exists. With ``commit=False`` the repository is
    initialized and the files are written but nothing is committed (no ``HEAD``).
    """

    def __init__(self, files=None, *, commit=True, message="initial"):
        if not git_available():
            raise GitUnavailable("git executable not found")
        self._tmp = tempfile.mkdtemp(prefix="docsync_fixture_")
        self.path = Path(self._tmp) / "repo"
        self.path.mkdir()
        self._closed = False
        try:
            self.git("init", "-q")
            for rel, content in (files or {}).items():
                self.write(rel, content)
            if commit:
                self.commit(message)
        except BaseException:
            self.cleanup()
            raise

    # -- context manager / cleanup -------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.cleanup()
        return False

    def cleanup(self):
        if not self._closed:
            self._closed = True
            shutil.rmtree(self._tmp, onexc=_remove_readonly)  # onexc: Python 3.12+

    # -- file operations -------------------------------------------------------------
    def _resolve(self, rel):
        if not isinstance(rel, str) or not rel or os.path.isabs(rel) or ".." in Path(rel).parts:
            raise ValueError("fixture paths must be relative and stay inside the repository: %r" % (rel,))
        target = (self.path / rel).resolve()
        if self.path.resolve() not in target.parents:
            raise ValueError("fixture path escapes the repository: %r" % (rel,))
        return target

    def write(self, rel, content):
        target = self._resolve(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        target.write_bytes(data)
        return target

    def read(self, rel):
        return self._resolve(rel).read_bytes()

    def delete(self, rel):
        self._resolve(rel).unlink()

    # -- git ---------------------------------------------------------------------------
    def git(self, *args):
        """Run git in the repository and return stdout as text. Raises on failure."""
        proc = subprocess.run(
            ["git", *_IDENTITY, *args],
            cwd=self.path,
            env=_env(),
            capture_output=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "git %s failed (exit %d): %s"
                % (" ".join(args), proc.returncode, proc.stderr.decode("utf-8", "replace").strip())
            )
        return proc.stdout.decode("utf-8", "replace")

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, "--allow-empty")

    def has_head(self):
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", "HEAD"],
            cwd=self.path, env=_env(), capture_output=True, timeout=60,
        )
        return proc.returncode == 0

    def tracked_files(self):
        out = self.git("ls-files", "-z")
        return sorted(name for name in out.split("\0") if name)
