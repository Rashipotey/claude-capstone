"""Git Adapter stage. The only module that runs git, through fixed argument templates.

Implemented in plan task T04 (core: runner, allow-list, environment, root check, typed
errors) and T05 (content-filter preflight, ``git diff HEAD`` retrieval, untracked names).

Controls held here as data (plan T05, "Hardening controls"):

* Exactly six argument templates. An argument vector that does not equal one of them is
  rejected before anything runs, so no other subcommand or option is reachable. The
  templates contain no path: the repository is the working directory of the call, and
  the path is never placed in an argument vector (paths are data, E11).
* An environment built from scratch (never copied): pass-through of ``PATH`` and, on
  Windows, ``SYSTEMROOT``, ``TEMP``, ``TMP``; a fixed set of ``GIT_*`` values; all else dropped.
* A bounded ``subprocess.Popen([...], shell=False)`` runner with a fixed timeout and capped
  capture of stdout and stderr. A timeout is a failed command.

Module boundary (architecture Section 1): this module imports no other stage. The
redaction function is injected by the caller (the CLI passes ``docsync.redact.redact``)
and every error message passes through it. Messages never contain file contents,
configuration values, or raw git output.

Stated limits (not claimed away): behavior was only exercised against Git for Windows;
"no HEAD" and "not a repository" are recognized from git's English messages (``LC_ALL=C``
is set), and any unrecognized failure is reported as a generic failed step.
"""

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass

from docsync.contracts import ChangedFile, InputOrGitError, OverCapError

__all__ = [
    "TIMEOUT_SECONDS",
    "TEMPLATES",
    "GitAdapterError",
    "GitMissingError",
    "NotARepositoryError",
    "NotRepositoryRootError",
    "NoHeadError",
    "GitTimeoutError",
    "GitCommandError",
    "GitRejectedError",
    "ContentFilterError",
    "PreflightUnverifiedError",
    "EMPTY_CHANGE_SET",
    "DiffResult",
    "check_config_listing",
    "GitAdapter",
    "build_environment",
    "build_vector",
    "match_template",
]

_STAGE = "gitadapter"

# Fixed timeout per git call, in seconds. A call that exceeds it is a failed command.
TIMEOUT_SECONDS = 30

# Memory bounds for one git call (code review M-1). Stdout: 64 MiB, far above the diff size
# cap that can ever pass the size gate (50 files, 2000 changed lines); reaching it ends the
# call with an over-cap outcome (exit 5). The peak is not 64 MiB: the chunk list, the joined
# bytes and the later decoded text can coexist, so expect roughly several times the bound
# (about 3x or more). Stderr is only read to classify a failure, so 64 KiB are kept and the
# rest is read and discarded.
MAX_STDOUT_BYTES = 64 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
_CHUNK = 64 * 1024
_GRACE_SECONDS = 5

# G = git --no-pager -c core.fsmonitor=false (the executable name is added by the runner).
_G = ("--no-pager", "-c", "core.fsmonitor=false")
# D = diff options; the trailing "--" ends options, so a path could only follow it as data.
# --ignore-submodules=dirty: Git does not inspect a submodule's worktree or index, so a
# clean filter defined in a submodule's own configuration was not seen to run in the
# fixture used. Evidence is limited to Git 2.56.0 for Windows with that fixture; no
# universal protection is claimed. Stated limitation: a submodule that is dirty or has
# untracked content but whose HEAD commit is unchanged is NOT reported (invisible); a moved
# submodule pointer (mode 160000) is still reported.
_D = (
    "--no-ext-diff", "--no-textconv", "--no-color", "--submodule=short",
    "--ignore-submodules=dirty", "--find-renames", "--find-copies", "--",
)

# The complete allow-list, name -> full argument vector (without the executable).
TEMPLATES = {
    "rev-parse-toplevel": _G + ("rev-parse", "--show-toplevel"),
    "config-list": _G + ("config", "--list", "--show-origin"),
    "diff-raw": _G + ("diff", "HEAD", "--raw", "-z") + _D,
    "diff-numstat": _G + ("diff", "HEAD", "--numstat", "-z") + _D,
    "diff-text": _G + ("diff", "HEAD") + _D,
    "ls-files-others": _G + ("ls-files", "--others", "--exclude-standard", "-z"),
}

_PASS_THROUGH = ("PATH",)
_PASS_THROUGH_WINDOWS = ("SYSTEMROOT", "TEMP", "TMP")


# ------------------------------------------------------------------ typed errors
class GitAdapterError(InputOrGitError):
    """Base of Git Adapter errors. Exit code 3 (input or Git error)."""

    def __init__(self, message):
        super().__init__(_STAGE, message)


class GitMissingError(GitAdapterError):
    """The git executable could not be started."""


class NotARepositoryError(GitAdapterError):
    """The path is not inside a Git repository."""


class NotRepositoryRootError(GitAdapterError):
    """The path is inside a repository but is not its root (OQ-1)."""


class NoHeadError(GitAdapterError):
    """The repository has no HEAD commit."""


class GitTimeoutError(GitAdapterError):
    """A git call exceeded the timeout."""


class GitCommandError(GitAdapterError):
    """A git call exited non-zero. Carries the failing step and exit code only."""

    def __init__(self, message, step=None, returncode=None):
        super().__init__(message)
        self.step = step
        self.returncode = returncode


class GitRejectedError(GitAdapterError):
    """An argument vector did not match an allowed template; nothing was run."""


class GitOutputOverCapError(OverCapError):
    """Git output reached the memory bound (M-1). Exit code 5. The message is fixed text."""

    def __init__(self):
        super().__init__(_STAGE, "git output is over the size limit; the diff is over the cap, split the change")


class ContentFilterError(GitAdapterError):
    """The repository configuration defines a content filter (preflight condition 4).

    Carries the key and the origin only; the value is never kept. Exit code 3.
    """

    def __init__(self, message, key=None, origin=None):
        super().__init__(message)
        self.key = key
        self.origin = origin


class PreflightUnverifiedError(GitAdapterError):
    """Content-filter protection could not be verified (preflight conditions 1 to 3).

    ``check`` names the failed check. Exit code 3. Carries no configuration values and
    no raw command output.
    """

    def __init__(self, message, check=None):
        super().__init__(message)
        self.check = check


# --------------------------------------------------------------------- templates
def match_template(args):
    """Return the template name whose vector equals ``args`` exactly, else None."""
    try:
        vector = tuple(args)
    except TypeError:
        return None
    for name, template in TEMPLATES.items():
        if vector == template:
            return name
    return None


def build_vector(name):
    """Return the argument vector (without the executable) of a named template."""
    try:
        return list(TEMPLATES[name])
    except KeyError:
        raise GitRejectedError("unknown git template") from None


# ------------------------------------------------------------------- environment
def build_environment(parent_env=None, *, windows=None, devnull=None):
    """Build the child environment from scratch. Nothing is copied except the allowed names."""
    if parent_env is None:
        parent_env = os.environ
    if windows is None:
        windows = os.name == "nt"
    if devnull is None:
        devnull = os.devnull
    allowed = _PASS_THROUGH + (_PASS_THROUGH_WINDOWS if windows else ())
    env = {}
    for wanted in allowed:
        for key, value in parent_env.items():
            # Environment names are case-insensitive on Windows only.
            same = key.upper() == wanted if windows else key == wanted
            if same and isinstance(value, str):
                env[wanted] = value
                break
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=devnull,
        GIT_CONFIG_SYSTEM=devnull,
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
    )
    return env


# ------------------------------------------------------------ preflight (plan T05)
EMPTY_CHANGE_SET = "empty change set"

_ORIGIN_TYPES = frozenset({"file", "command line", "standard input", "blob"})
_REPO_RECORD_KEY = "core.repositoryformatversion"
# Section and variable names are case-insensitive; the subsection (filter name) may
# contain dots. Matched on the key (the record text before its first "=").
_FILTER_KEY = re.compile(r"filter\..+\.(?:clean|smudge|process)\Z", re.IGNORECASE | re.DOTALL)
# Conservative fallback over a whole line: a subsection name may itself contain "=", or an
# origin path may contain a tab. It can only add refusals (safe), never remove one.
_FILTER_ANYWHERE = re.compile(r"(?:\A|\t)filter\..+?\.(?:clean|smudge|process)(?:=|\Z)",
                              re.IGNORECASE | re.DOTALL)

_CHECK_COMMAND = "command failed or timed out"
_CHECK_PARSE = "output not parseable"
_CHECK_REPO = "repository configuration not found in output"
_CHECK_ORIGIN = "unknown origin type"


def _printable(text):
    """Make text safe to show: control and non-ASCII characters become '?'."""
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)


def check_config_listing(output):
    """Evaluate preflight conditions 2 to 4 on the output of ``config --list --show-origin``.

    Returns None when verified. Otherwise returns ``("filter", key, origin)`` for a
    defined content filter (``key`` is None when the key name cannot be shown safely) or
    ``("unverified", check_name)``. Values are never kept or returned.
    """
    text = output.decode("utf-8", "replace") if isinstance(output, (bytes, bytearray)) else str(output)
    if "\0" in text:
        return ("unverified", _CHECK_PARSE)
    records = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if not line:
            continue
        if "\t" not in line:
            return ("unverified", _CHECK_PARSE)
        origin, record = line.split("\t", 1)
        if ":" not in origin or origin.split(":", 1)[0] not in _ORIGIN_TYPES:
            return ("unverified", _CHECK_ORIGIN)
        records.append((line, origin, record))
    # Condition 4 is evaluated before condition 3 so a defined filter is named.
    for line, origin, record in records:
        key = record.split("=", 1)[0]
        if _FILTER_KEY.match(key):
            return ("filter", key, origin)
        if _FILTER_ANYWHERE.search(line):
            return ("filter", None, origin)
    # Condition 3: the repository's own configuration was inspected.
    for _line, origin, record in records:
        if origin.startswith("file:") and record.split("=", 1)[0].lower() == _REPO_RECORD_KEY:
            return None
    return ("unverified", _CHECK_REPO)


# ----------------------------------------------------------------- diff retrieval
@dataclass(frozen=True, slots=True)
class DiffResult:
    """What ``git diff HEAD`` found (D21).

    ``files`` are ``ChangedFile`` records in Git's order. ``status`` is the raw Git status
    token (for example ``M``, ``A``, ``D``, ``T``, ``R100``, ``C75``); ``old_path`` is set
    for a rename or copy. For a binary entry ``binary`` is True and the counts are None
    (never zero, D23). A mode-only change has differing ``old_mode`` and ``new_mode`` and
    0 added and 0 deleted lines; a submodule change has mode ``160000``. Classification
    is left to T06 and T07. ``untracked`` holds names only; those files are never read
    (E12). ``diff_text`` is the unified diff text.
    """

    files: tuple = ()
    diff_text: str = ""
    untracked: tuple = ()

    @property
    def is_empty(self):
        return not self.files

    @property
    def status(self):
        """``EMPTY_CHANGE_SET`` when there are no tracked changes, else ``"changes"``."""
        return EMPTY_CHANGE_SET if self.is_empty else "changes"


def _fields(raw):
    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    parts = text.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _parse_raw(raw):
    """Parse ``diff --raw -z``: ``:<modes> <shas> <status>`` NUL path (two paths for R/C)."""
    parts = _fields(raw)
    entries = []
    i = 0
    while i < len(parts):
        head = parts[i]
        meta = head.split(" ")
        if not head.startswith(":") or len(meta) < 5 or not meta[4]:
            raise ValueError("raw record")
        status = meta[4]
        count = 2 if status[0] in ("R", "C") else 1
        names = parts[i + 1:i + 1 + count]
        if len(names) != count or not all(names):
            raise ValueError("raw path")
        old_path, new_path = (names[0], names[1]) if count == 2 else (None, names[0])
        entries.append((meta[0][1:], meta[1], status, old_path, new_path))
        i += 1 + count
    return entries


def _parse_numstat(raw):
    """Parse ``diff --numstat -z`` into ``{new_path: (added, deleted)}``; (None, None) is binary."""
    parts = _fields(raw)
    counts = {}
    i = 0
    while i < len(parts):
        pieces = parts[i].split("\t", 2)
        if len(pieces) != 3:
            raise ValueError("numstat record")
        added, deleted, path = pieces
        if path == "":  # rename or copy: the old and new paths follow as separate fields
            if i + 2 >= len(parts):
                raise ValueError("numstat path")
            path = parts[i + 2]
            i += 3
        else:
            i += 1
        if not path:
            raise ValueError("numstat path")
        counts[path] = (None, None) if (added == "-" and deleted == "-") else (int(added), int(deleted))
    return counts


def _changed_files(raw, numstat):
    counts = _parse_numstat(numstat)
    files = []
    for old_mode, new_mode, status, old_path, new_path in _parse_raw(raw):
        if new_path not in counts:
            raise ValueError("no line counts")
        added, deleted = counts[new_path]
        files.append(ChangedFile(
            path=new_path, status=status, added=added, deleted=deleted, old_path=old_path,
            old_mode=old_mode, new_mode=new_mode, binary=added is None,
        ))
    return tuple(files)


# ------------------------------------------------------------------------ adapter
def _same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _drain(pipe, limit, sink, exceeded):
    """Read ``pipe`` to EOF in chunks into ``sink``. Keeps at most ``limit`` bytes.

    If ``exceeded`` is given, reading stops at the first byte over ``limit`` and the event is
    set (stdout). Otherwise the rest is read and discarded so the child never blocks (stderr).
    """
    kept = 0
    try:
        while True:
            chunk = pipe.read(_CHUNK)
            if not chunk:
                return
            room = limit - kept
            if len(chunk) > room:
                if exceeded is not None:
                    exceeded.set()
                    return
                chunk = chunk[:room]
            if chunk:
                sink.append(chunk)
                kept += len(chunk)
    except (OSError, ValueError):
        return


def _bounded_run(argv, *, shell=False, cwd=None, env=None, capture_output=True, stdin=None,
                 timeout=None):
    """``subprocess.run`` look-alike with bounded capture (default runner).

    Stdout over ``MAX_STDOUT_BYTES`` ends the call: only this child is killed by its own
    handle and ``GitOutputOverCapError`` is raised. Stderr keeps ``MAX_STDERR_BYTES``.
    """
    # bufsize=0: raw pipes, so a drain thread blocked in read() shares no buffer lock with a
    # close() call. A pipe is closed only after its drain thread has exited.
    proc = subprocess.Popen(argv, shell=shell, cwd=cwd, env=env, stdin=stdin,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    out, err = [], []
    exceeded = threading.Event()
    pairs = [
        (proc.stdout, threading.Thread(target=_drain, args=(proc.stdout, MAX_STDOUT_BYTES, out, exceeded),
                                       daemon=True)),
        (proc.stderr, threading.Thread(target=_drain, args=(proc.stderr, MAX_STDERR_BYTES, err, None),
                                       daemon=True)),
    ]
    threads = [t for _pipe, t in pairs]
    for t in threads:
        t.start()

    def close_finished():
        # A pipe whose drain thread is still alive (a descendant may hold the write end) is
        # left to that daemon thread; closing it could block.
        for pipe, t in pairs:
            if not t.is_alive():
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass

    def stop():
        # Kills only this child, by its handle. Descendants it spawned are NOT killed.
        end = time.monotonic() + _GRACE_SECONDS  # one shared grace period for all waits
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        for t in threads:
            t.join(timeout=max(end - time.monotonic(), 0))
        close_finished()

    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while proc.poll() is None and not exceeded.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                stop()
                raise subprocess.TimeoutExpired(argv, timeout)
            exceeded.wait(0.02)
        if exceeded.is_set():
            stop()
            raise GitOutputOverCapError()
        for t in threads:  # the child has exited: its pipes reach EOF
            left = _GRACE_SECONDS if deadline is None else max(deadline - time.monotonic(), 0.1)
            t.join(timeout=left)
        if exceeded.is_set():
            stop()
            raise GitOutputOverCapError()
        if any(t.is_alive() for t in threads):
            # Output may be incomplete (a descendant holds a pipe): fail closed.
            stop()
            raise subprocess.TimeoutExpired(argv, timeout)
    except BaseException:
        if proc.poll() is None:
            stop()
        raise
    close_finished()
    return subprocess.CompletedProcess(argv, proc.returncode, b"".join(out), b"".join(err))


class GitAdapter:
    """Runs allow-listed git commands in one directory.

    ``redactor`` is required (no default, so no message is built without redaction).
    ``executable`` and ``runner`` are injectable for tests; the runner has the signature
    of ``subprocess.run``.
    """

    def __init__(self, repo_path, *, redactor, executable="git", runner=_bounded_run,
                 timeout=TIMEOUT_SECONDS, environment=None):
        if not callable(redactor):
            raise TypeError("redactor must be callable")
        if not callable(runner):
            raise TypeError("runner must be callable")
        if not isinstance(repo_path, (str, os.PathLike)) or not os.fspath(repo_path):
            raise TypeError("repo_path must be a non-empty string or path")
        self._redact = redactor
        self._executable = executable
        self._runner = runner
        self._timeout = timeout
        self._environment = environment
        # Absolute, so a path that starts with "-" can never be read as an option; it is
        # only ever the working directory of the call, not an argument.
        self._cwd = os.path.abspath(os.fspath(repo_path))

    def _error(self, cls, message, **extra):
        return cls(self._redact(message), **extra)

    def run(self, args):
        """Run one allow-listed argument vector (without the executable); return stdout bytes."""
        name = match_template(args)
        if name is None:
            raise self._error(GitRejectedError, "git command rejected: not an allowed argument form")
        step = args[len(_G)]  # subcommand name, for messages
        env = self._environment if self._environment is not None else build_environment()
        try:
            proc = self._runner(
                [self._executable, *args],
                shell=False,
                cwd=self._cwd,
                env=env,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            raise self._error(
                GitTimeoutError,
                "git %s timed out after %s seconds" % (step, self._timeout),
            ) from None
        except FileNotFoundError:
            raise self._error(GitMissingError, "git executable not found") from None
        except OSError:
            raise self._error(GitMissingError, "git executable could not be started") from None

        if isinstance(proc.stdout, (bytes, bytearray)) and len(proc.stdout) > MAX_STDOUT_BYTES:
            raise GitOutputOverCapError()  # backstop for an injected runner
        if proc.returncode != 0:
            raise self._failure(step, name, proc)
        return proc.stdout

    def _failure(self, step, name, proc):
        # stderr is read only to classify the failure; it is never put in a message.
        stderr = proc.stderr
        text = stderr.decode("utf-8", "replace").lower() if isinstance(stderr, bytes) else str(stderr or "").lower()
        if "not a git repository" in text:
            return self._error(NotARepositoryError, "path is not a Git repository")
        if name == "rev-parse-toplevel" and "work tree" in text:
            return self._error(NotRepositoryRootError, "path is not the root of a Git working tree")
        if name.startswith("diff") and "head" in text and (
            "unknown revision" in text or "bad revision" in text or "ambiguous argument" in text
        ):
            return self._error(NoHeadError, "repository has no HEAD commit")
        return self._error(
            GitCommandError,
            "git %s failed with exit code %s" % (step, proc.returncode),
            step=step,
            returncode=proc.returncode,
        )

    def check_root(self):
        """Confirm the path is the repository root (OQ-1) and return the resolved root path.

        Uses the ``rev-parse --show-toplevel`` template and compares resolved paths
        (Git prints forward slashes on Windows). Any other path is an input error, exit 3.
        """
        out = self.run(TEMPLATES["rev-parse-toplevel"])
        top = out.decode("utf-8", "replace").rstrip("\r\n")
        if not top.strip():
            raise self._error(GitCommandError, "git rev-parse failed: no root path reported",
                              step="rev-parse", returncode=0)
        if not _same_path(top, self._cwd):
            raise self._error(
                NotRepositoryRootError,
                "path is inside a repository but is not its root: %s" % self._cwd,
            )
        return os.path.realpath(self._cwd)

    def preflight(self):
        """Content-filter preflight, fail closed (architecture 7.3, plan T05).

        Runs the ``config --list --show-origin`` template and returns None only when all
        four conditions hold. Otherwise raises ``ContentFilterError`` (a filter is defined)
        or ``PreflightUnverifiedError`` (protection could not be verified); both are exit 3.
        Messages name the key and origin or the failed check, never a value or raw output.
        """
        try:
            out = self.run(TEMPLATES["config-list"])
        except GitAdapterError:
            raise self._error(PreflightUnverifiedError, _unverified_message(_CHECK_COMMAND),
                              check=_CHECK_COMMAND) from None
        verdict = check_config_listing(out)
        if verdict is None:
            return None
        if verdict[0] == "filter":
            _kind, key, origin = verdict
            if key is None:
                what = "a filter key whose name contains an unusual character"
            else:
                what = "key %s" % _printable(key)
            raise self._error(
                ContentFilterError,
                "repository defines a content filter (%s, origin %s); stopping before any diff"
                % (what, _printable(origin)),
                key=None if key is None else _printable(key),
                origin=_printable(origin),
            )
        raise self._error(PreflightUnverifiedError, _unverified_message(verdict[1]), check=verdict[1])

    def retrieve_diff(self):
        """Return a ``DiffResult`` for ``git diff HEAD`` (D21).

        Order: root check, content-filter preflight, then the diff and listing calls. If
        the root check or the preflight fails, no diff or listing call is made.
        """
        self.check_root()
        self.preflight()
        raw = self.run(TEMPLATES["diff-raw"])
        numstat = self.run(TEMPLATES["diff-numstat"])
        text = self.run(TEMPLATES["diff-text"])
        others = self.run(TEMPLATES["ls-files-others"])
        try:
            files = _changed_files(raw, numstat)
        except (ValueError, TypeError):
            raise self._error(GitCommandError, "git diff output could not be parsed",
                              step="diff", returncode=0) from None
        untracked = tuple(sorted(_fields(others)))
        return DiffResult(
            files=files,
            diff_text=text.decode("utf-8", "replace") if isinstance(text, (bytes, bytearray)) else str(text),
            untracked=untracked,
        )


def _unverified_message(check):
    return "content-filter protection could not be verified: %s" % check
