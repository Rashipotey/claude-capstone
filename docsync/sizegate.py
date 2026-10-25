"""Size Gate stage. Applies the single diff cap and the counting rules (D6, D12, D23).

Implemented in plan task T06. Input is the in-memory per-file records (``ChangedFile``) of
the diff; nothing is read from disk and no diff text is looked at.

Order of checks (architecture Section 2.1):

1. No records: ``NoChangesError`` ("no changes", exit 4).
2. Any binary, mode-only, or submodule entry, or an entry whose line counts are unknown:
   ``UnsupportedEntryError`` (exit 6) naming the path and kind. Never counted as zero. This
   runs before the cap check, so a diff that is over the cap and also holds such an entry
   reports the unsupported entry.
3. More than 50 files or more than 2,000 changed lines (added plus deleted), either limit:
   ``OverCapError`` (exit 5) reporting both counts and asking for a split. No warning tier,
   no partial processing. At or below both limits the diff passes.

Counting: every entry is one file. A text entry counts added plus deleted lines, so a rename
or copy without a content change is 1 file and 0 lines. A deleted file is 1 file plus its
deleted lines and is listed as not analyzed.

Module boundary: this module imports no other stage. The redaction function is injected
by the caller and every error message passes through it. Messages hold names and counts only.
"""

from dataclasses import dataclass

from docsync.contracts import (
    ChangedFile,
    NoChangesError,
    OverCapError,
    UnsupportedEntryError,
)

__all__ = [
    "MAX_FILES",
    "MAX_LINES",
    "KIND_BINARY",
    "KIND_MODE_ONLY",
    "KIND_SUBMODULE",
    "KIND_UNKNOWN_COUNTS",
    "SizeGateResult",
    "SizeGateNoChangesError",
    "SizeGateOverCapError",
    "SizeGateUnsupportedEntryError",
    "classify_unsupported",
    "check_size",
]

_STAGE = "sizegate"

MAX_FILES = 50
MAX_LINES = 2000

KIND_BINARY = "binary"
KIND_MODE_ONLY = "mode-only"
KIND_SUBMODULE = "submodule"
KIND_UNKNOWN_COUNTS = "unknown line counts"

_SUBMODULE_MODE = "160000"


# ------------------------------------------------------------------ typed errors
class SizeGateNoChangesError(NoChangesError):
    """The change set is empty ("no changes"). Exit code 4."""

    def __init__(self, message):
        super().__init__(_STAGE, message)


class SizeGateOverCapError(OverCapError):
    """The diff is over the cap. Carries both counts. Exit code 5."""

    def __init__(self, message, file_count=None, line_count=None):
        super().__init__(_STAGE, message)
        self.file_count = file_count
        self.line_count = line_count


class SizeGateUnsupportedEntryError(UnsupportedEntryError):
    """A binary, mode-only, or submodule entry (or unknown counts). Exit code 6.

    ``path`` and ``kind`` name the first such entry; ``entries`` lists all of them as
    ``(path, kind)`` pairs.
    """

    def __init__(self, message, path=None, kind=None, entries=()):
        super().__init__(_STAGE, message)
        self.path = path
        self.kind = kind
        self.entries = tuple(entries)


# ------------------------------------------------------------------------ result
@dataclass(frozen=True, slots=True)
class SizeGateResult:
    """A diff that passed the gate. ``not_analyzed`` lists deleted paths (D23)."""

    file_count: int
    line_count: int
    not_analyzed: tuple = ()


# ----------------------------------------------------------------------- helpers
def _printable(text):
    """Make text safe to show: control and non-ASCII characters become '?'."""
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)


def _is_deleted(entry):
    return entry.status.startswith("D")


def classify_unsupported(entry):
    """Return the unsupported kind of one record, or None when it is countable."""
    if entry.new_mode == _SUBMODULE_MODE or entry.old_mode == _SUBMODULE_MODE:
        return KIND_SUBMODULE
    if entry.binary:
        return KIND_BINARY
    if entry.added is None or entry.deleted is None:
        return KIND_UNKNOWN_COUNTS
    # A mode change with no line change. Added and deleted files have a zero mode on one
    # side by definition, so they are not mode-only changes.
    if (
        entry.old_mode is not None
        and entry.new_mode is not None
        and entry.old_mode != entry.new_mode
        and entry.added == 0
        and entry.deleted == 0
        and entry.status[:1] not in ("A", "D")
    ):
        return KIND_MODE_ONLY
    return None


def check_size(files, *, redactor):
    """Apply the Size Gate to ``files`` (an iterable of ``ChangedFile``).

    Returns a ``SizeGateResult`` when the diff is within the cap. Raises
    ``SizeGateNoChangesError``, ``SizeGateUnsupportedEntryError`` or ``SizeGateOverCapError``.
    """
    if not callable(redactor):
        raise TypeError("redactor must be callable")
    if isinstance(files, (str, bytes)):
        raise TypeError("files must be a sequence of ChangedFile")
    records = tuple(files)
    if not all(isinstance(f, ChangedFile) for f in records):
        raise TypeError("files must contain only ChangedFile")

    if not records:
        raise SizeGateNoChangesError(redactor("no changes: the change set is empty"))

    unsupported = []
    for entry in records:
        kind = classify_unsupported(entry)
        if kind is not None:
            unsupported.append((_printable(entry.path), kind))
    if unsupported:
        path, kind = unsupported[0]
        more = len(unsupported) - 1
        message = "unsupported entry: %s (%s)" % (path, kind)
        if more:
            message += "; %d more unsupported entr%s" % (more, "y" if more == 1 else "ies")
        raise SizeGateUnsupportedEntryError(
            redactor(message), path=path, kind=kind, entries=unsupported
        )

    file_count = len(records)
    line_count = sum(f.changed_lines for f in records)
    if file_count > MAX_FILES or line_count > MAX_LINES:
        raise SizeGateOverCapError(
            redactor(
                "diff is over the cap: %d files (limit %d) and %d changed lines (limit %d); "
                "split the change into smaller parts and run again"
                % (file_count, MAX_FILES, line_count, MAX_LINES)
            ),
            file_count=file_count,
            line_count=line_count,
        )
    not_analyzed = tuple(_printable(f.path) for f in records if _is_deleted(f))
    return SizeGateResult(file_count=file_count, line_count=line_count, not_analyzed=not_analyzed)
