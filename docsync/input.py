"""Input Resolver stage. Validates the repository path and produces a ChangeRequest.

Implemented in plan task T03 (AC-05, NFR-02, E1, OQ-1).

The path is an optional positional argument that defaults to the current directory.
This stage only checks that the path exists, is a directory, and is readable. It makes
no Git call. Whether the directory is a repository root is checked by the Git Adapter
(T04), not here; that detail is "Not Found" for this stage.

Module boundary (architecture Section 1): a stage must not import another stage, so the
redaction function is passed in by the caller (the CLI passes ``docsync.redact.redact``).
There is deliberately no default: an error message is never built without redaction.
"""

import os

from docsync.contracts import ChangeRequest, InputOrGitError

__all__ = ["resolve_input"]

_STAGE = "input"


def _fail(redactor, reason, path_text):
    # The path is user-supplied text and may look like a secret; it is redacted
    # before it appears in a message.
    message = "%s: %s" % (reason, redactor(path_text))
    return InputOrGitError(_STAGE, redactor(message))


def resolve_input(repo_path=None, target=None, *, redactor):
    """Return a ChangeRequest for an existing, readable directory, or raise InputOrGitError.

    ``repo_path`` None or empty means the current directory (OQ-1). ``redactor`` is a
    callable that takes text and returns text with secret-like values masked.
    """
    if not callable(redactor):
        raise TypeError("redactor must be callable")
    if repo_path is None or repo_path == "":
        shown = "."
        path = os.getcwd()
    else:
        if not isinstance(repo_path, (str, os.PathLike)):
            raise TypeError("repo_path must be a string or path")
        shown = os.fspath(repo_path)
        if "\x00" in shown:
            raise _fail(redactor, "invalid repository path (contains a null character)", shown.replace("\x00", "?"))
        path = shown

    try:
        exists = os.path.exists(path)
        is_dir = os.path.isdir(path)
    except (OSError, ValueError):
        raise _fail(redactor, "repository path cannot be checked", shown) from None
    if not exists:
        raise _fail(redactor, "repository path does not exist", shown)
    if not is_dir:
        raise _fail(redactor, "repository path is not a directory", shown)
    try:
        with os.scandir(path):
            pass
    except OSError:
        raise _fail(redactor, "repository path is not readable", shown) from None

    return ChangeRequest(repo_path=os.path.abspath(path), target=target)
