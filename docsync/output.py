"""Patch Writer stage. Rendering, destination guard, exclusive creation, and rollback.

Implemented in plan task T13 (Attempt 2 corrections included). Imports only the standard
library and ``docsync.contracts``; the redactor is injected (``redactor=`` / argument) so no
stage imports another.

Input contract (a choice the plan does not specify; flagged for the human). T10
``ProposedEdit`` carries no document text, so the writer cannot render from it. It takes
``DocumentChange(path, original, proposed)``: the original and the proposed full text of one
document (``README.md`` or ``docs/**/*.md``). NOTHING YET PRODUCES ``DocumentChange.proposed``
and how it will be produced is not invented here: this is an unresolved dependency that needs
a human decision before T15.

API decisions made in Attempt 1 (pending the human's decision, except where changed below):
  * Types: ``DocumentChange``, ``Hunk``, ``WithheldFinding``, ``RenderedPatch``,
    ``ApprovedPatch``, ``PatchToken``, ``WithheldHunksError``, ``RollbackError``.
  * Pipeline (D31): ``render_patch`` (diff + withhold) -> ``raise_if_withheld`` (exit 10) ->
    validation by the caller -> ``approve_patch`` (defense in depth, exit 12 on a broken
    sequence) -> ``publish_patch`` (exit 11 on destination, existing file or write error;
    exit 12 for an object that did not come from ``approve_patch``) -> ``rollback_patch``.
    ``check_no_existing_patch`` is the start-of-run pre-check (D29, exit 11).
  * Exit mapping: ``WithheldHunksError`` = 10; ``PatchWriteError`` = 11; precondition and
    seal failures (``UnexpectedStageError``) and ``RollbackError`` = 12. Other exceptions
    inside ``publish_patch`` propagate unchanged after the partial file is removed.
  * The repository path is carried inside ``ApprovedPatch`` because ``publish_patch(content)``
    takes no destination and has no other way to learn it (the destination is fixed:
    ``output/docsync.patch`` under the working directory).
  * ``PatchToken.path`` is the absolute path ``<realpath(cwd)>/output/docsync.patch`` (the
    ``output`` component is never resolved; since policy B it cannot be a link). It lets a later ``chdir`` not redirect the rollback, and ``rollback_patch`` refuses
    any token whose path is not exactly that shape (M3).

Rendering is deterministic (NFR-06): files sorted by path, three context lines, no
timestamps in headers, only LF is a line break (Git numbering, the same rule as the
validator), CR bytes are kept inside lines, a final line without LF gets Git's
"\\ No newline at end of file" marker.

Line numbers in findings (``Hunk.withheld_lines``, ``WithheldFinding.line``): removed lines
are reported by their ORIGINAL-file line number; added and context lines by their
PROPOSED-file line number; a PEM block is reported at its BEGIN line (in the document that
holds the block). ``Hunk.added_lines`` are 1-based LF (Git) numbers in the proposed document,
ready for ``validation.validate_content(..., added_lines=)``.

Secret handling. The injected redactor decides per hunk (context lines included, D8); the
writer adds one document-level rule that does not depend on the redactor: when the original
or the proposed document holds a PEM private-key BEGIN line, every hunk overlapping the lines
from BEGIN to END (or to the end of the document when END is missing) is withheld, so a block
split across hunks cannot slip through. ``approve_patch`` re-runs the injected redactor on the
rendered text and on every hunk's lines.

Redaction policy (current). A hunk is WITHHELD whenever ``contains_secret`` is True for its text
(context lines included). The writer never emits masked text: ``redact()`` is not called on document
text anywhere in this module, and a withheld hunk keeps only file and line numbers (never values) in
its findings and in the exit-10 error. The redactor finds KNOWN FORMS only and does NOT detect all
secrets; ``docsync.redact`` is the authority and its docstring lists the actual limits, each with an
example and a ``test_KNOWN_GAP_*`` test (bare high-entropy strings, unknown token formats, natural
language, command-line forms, some URL, table, Markdown and multi-line forms). File names in patch
headers are not scanned. False positives are possible (for example prose like ``credentials:
required``, camel-case words like ``primaryKey: id``, or a table row such as ``| Foreign key | users
|``); withholding on one is fail-closed. Attempt 8 closed: plain unclosed quote / comma / semicolon
values, camel-case names, HTML-tag and escaped-emphasis names, Unicode blanks and full-width
separators, and a single-token value on the line after a name and separator.

Redactor cost (Attempt 3, wording corrected in Attempts 4 and 8). ``render_patch`` calls
``contains_secret`` once per hunk, and ``secret_line_numbers`` only for a hunk that hits;
``approve_patch`` calls ``contains_secret`` on every hunk body and once on the whole text. So a patch
gets about three ``contains_secret`` passes over the same text. Each ``contains_secret`` runs about
fifteen pattern scans in the worst case (no hit): the two assignment patterns (``_ASSIGNMENT`` and the
passphrase / credential twin) once each, plus the Markdown, odd-value, next-line and table patterns.
Every pattern is linear (bounded repetitions, a one-character first test, one table-line lookup per
line); ``secret_line_numbers`` is linear since Attempt 4. A different injected redactor brings its own
cost; the writer does not bound it.

Seals (M2, M3). ``render_patch`` stamps ``RenderedPatch`` with a SHA-256 digest of its hunks,
findings and text, keyed with a random per-process value; ``approve_patch`` recomputes it,
re-derives the text from the hunks, and refuses (exit 12) a forged, altered or unsealed object
(``dataclasses.replace(text=...)`` keeps the old digest and is refused). ``ApprovedPatch``
carries a keyed digest of its text and repository, checked at construction and again by
``publish_patch``, so ``replace`` or direct attribute tampering is refused. ``copy.copy`` and
``copy.deepcopy`` of a valid object stay valid and unchanged (consistent, tested). This defends
against accidents and forged objects. It CANNOT prevent a deliberate in-process caller: code in
the same process can pass a no-op redactor (then the re-check finds nothing, and
``render_patch`` with the same no-op redactor withholds nothing), import the private key, or
call private functions. ``PatchToken`` is a plain checked record: ``rollback_patch`` deletes
only a regular file at a path shaped ``<absolute>/output/docsync.patch`` whose identity, size
and SHA-256 match; a caller who knows those values for another ``output/docsync.patch`` can
still aim the rollback at it.

Path and network risks. The destination guard resolves real paths (``os.path.realpath``) of
the working directory, the repository, ``<repo>/docs``, ``<repo>/README.md`` and the destination
file (architecture 2.6), but never of ``output`` (policy B below). UNC paths are refused BEFORE
resolving for the working directory and the repository. ``realpath(cwd)``,
``realpath(destination)``, ``realpath(<repo>/docs)`` and ``realpath(<repo>/README.md)`` can still
follow a link chain to a UNC location and touch the network; this is the same class as the T12
deferred Low, accepted there. A legitimate network-share working directory is deliberately
refused. Paths in error messages are structured data that the Reporter must redact.

Output junctions and symlinks (policy B, Attempt 5, human decision). An ``output`` path
component that is a symbolic link, a Windows junction or any other reparse point (dangling, or
pointing at a non-existent target, included) is REFUSED with ``PatchWriteError`` (exit 11) naming
the path, before ``output`` is resolved (``lstat``, the reparse-point attribute, ``islink`` and
``isjunction``; ``realpath`` is never called on ``output``, so a link to a UNC location is never
resolved). This applies in ``check_no_existing_patch``, in every ``_guard`` call of
``publish_patch`` and to the one-hop ``_link_target`` (which no longer resolves a target that is
itself a link). When ``output`` does not exist it is created, as before. STILL FOLLOWED: a link
as the working directory itself or as an ancestor of it is resolved by the real-path resolution
(``<realpath(cwd)>/output``), so the patch may land in the link's target tree; the UNC refusals
for the working directory and the repository remain; ``README.md`` and ``docs/`` stay protected
(a working directory inside them is refused). A link or reparse point AT the destination file
``output/docsync.patch`` is refused by the existing-file checks. Not closed: a link swapped in at
``output`` between the check and the open (TOCTOU, see below). DOWNSTREAM OBLIGATION FOR T14:
the destination is ``<realpath(cwd)>/output/docsync.patch``; when that differs from
``<cwd>/output/docsync.patch`` (a link in the working directory or an ancestor) T14 must report
the resolved destination to the user.

Residual limitations (not fixed):
  * The validation report has no content identity, so it is not bound to the patch content;
    only its verdict is checked.
  * TOCTOU windows remain. ``dest`` is ``<realpath(cwd)>/output/docsync.patch``; ``output`` is
    checked for being a link in the guard and again immediately before ``os.open``, but a swap
    of ``output`` (or of the working directory or an ancestor) for a link after that check can
    briefly create a file elsewhere (the post-write re-check refuses, and the file is removed
    by identity), and a link can appear at the final component. The final
    component is checked immediately before ``os.open`` (``lexists`` + ``lstat``) and
    ``O_EXCL`` is kept, but a link appearing between that check and the open is a race. After
    writing, the guard and the final component are re-checked; a file that landed somewhere
    other than the destination is removed by identity (at the link target, one hop) or is
    reported by path if it cannot be removed. ``dir_fd``-relative opening would close the gap
    on POSIX only.
  * File identity is ``(st_dev, st_ino)``. If ``st_ino`` is 0 the identity is treated as
    unusable: cleanup after a failed write leaves the file and reports it, and
    ``rollback_patch`` raises ``RollbackError`` instead of deleting.
  * ``rollback_patch`` has a check-to-delete race (documented, not detected). The
    held-open rollback behavior is tested only on Windows.
  * The patch file mode follows the umask (created with 0o666).
  * Only ``README.md`` and ``docs/**/*.md`` are accepted as document paths.
"""

import difflib
import hashlib
import os
import re
import stat
from dataclasses import dataclass, field

from docsync.contracts import (
    CheckStatus,
    PatchWriteError,
    UnexpectedStageError,
    ValidationReport,
    WithheldHunkError,
)

__all__ = [
    "OUTPUT_DIR",
    "PATCH_NAME",
    "DocumentChange",
    "Hunk",
    "WithheldFinding",
    "RenderedPatch",
    "ApprovedPatch",
    "PatchToken",
    "WithheldHunksError",
    "RollbackError",
    "render_patch",
    "raise_if_withheld",
    "approve_patch",
    "check_no_existing_patch",
    "publish_patch",
    "rollback_patch",
]

_STAGE = "output"
OUTPUT_DIR = "output"
PATCH_NAME = "docsync.patch"
_CONTEXT = 3
_KEY = os.urandom(32)  # per-process; binds seals to this process (not a secret from this process)
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_PEM_BEGIN = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _keyed_digest(*parts):
    return hashlib.sha256(_KEY + repr(parts).encode("utf-8", "backslashreplace")).hexdigest()


# ------------------------------------------------------------------------------ errors
class WithheldHunksError(WithheldHunkError):
    """Exit 10. ``findings`` is a tuple of WithheldFinding (file and line only)."""

    def __init__(self, findings):
        findings = tuple(findings)
        listing = ", ".join("%s line %d" % (f.file, f.line) for f in findings)
        super().__init__(_STAGE, "%d hunk(s) withheld (secret-like value): %s" % (len(findings), listing))
        self.findings = findings


class RollbackError(UnexpectedStageError):
    """The rollback could not delete the patch it created (exit 12 through the caller).
    ``path`` names the leftover file."""

    def __init__(self, path, reason):
        super().__init__(_STAGE, "could not remove the patch %s: %s" % (path, reason))
        self.path = path


class _Misplaced(Exception):
    """Internal: the file this call created is not at the destination (a link was followed)."""


def _fail(message):
    return PatchWriteError(_STAGE, message)


def _refuse(message):
    return UnexpectedStageError(_STAGE, "writer precondition: " + message)


# ------------------------------------------------------------------------------ inputs
def _check_doc_path(path):
    if not isinstance(path, str) or not path:
        raise ValueError("document path must be a non-empty string")
    if any(ord(c) < 32 or ord(c) == 127 for c in path) or "\\" in path:
        raise ValueError("document path must not contain control characters or backslashes")
    parts = path.split("/")
    if path.startswith("/") or ":" in parts[0] or any(p in ("", ".", "..") for p in parts):
        raise ValueError("document path must be relative, with no empty, '.' or '..' segment")
    if not (path == "README.md" or (parts[0] == "docs" and len(parts) > 1 and path.endswith(".md"))):
        raise ValueError("document path must be README.md or a Markdown file under docs/")


@dataclass(frozen=True, slots=True)
class DocumentChange:
    """One document: repository-relative POSIX path, original text, proposed text.
    The path is only ever written as text into the patch header; it never reaches the file
    system. Newlines must be preserved by the reader (no universal-newline translation)."""

    path: str
    original: str
    proposed: str

    def __post_init__(self):
        _check_doc_path(self.path)
        for name in ("original", "proposed"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError("%s must be a string" % name)
            if "\x00" in value:
                raise ValueError("%s must not contain NUL" % name)


@dataclass(frozen=True, slots=True)
class WithheldFinding:
    """File and line of a secret-like value. Never the value."""

    file: str
    line: int


@dataclass(frozen=True, slots=True)
class Hunk:
    """One hunk. A withheld hunk keeps its numbers but no text (``lines`` is empty), so the
    value cannot leak through the object. ``added_lines`` are 1-based LF line numbers in the
    proposed document. ``withheld_lines`` are the lines reported (proposed-file numbers for
    added and context lines, original-file numbers for removed lines, BEGIN line of a PEM
    block)."""

    file: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple = ()
    added_lines: tuple = ()
    withheld: bool = False
    withheld_lines: tuple = ()


def _hunk_key(h):
    return (h.file, h.old_start, h.old_count, h.new_start, h.new_count, h.lines, h.added_lines, h.withheld, h.withheld_lines)


def _rendered_digest(hunks, withheld, text):
    return _keyed_digest("rendered", tuple(_hunk_key(h) for h in hunks), tuple((f.file, f.line) for f in withheld), text)


@dataclass(frozen=True, slots=True)
class RenderedPatch:
    """Result of ``render_patch``. ``text`` is empty when any hunk is withheld. Only
    ``render_patch`` produces a valid one: ``_digest`` binds the hunks, findings and text, so
    an object built by hand or altered with ``dataclasses.replace`` is refused by
    ``approve_patch``."""

    hunks: tuple = ()
    withheld: tuple = ()
    text: str = ""
    _digest: str = field(default="", repr=False)

    @property
    def files(self):
        return tuple(sorted({h.file for h in self.hunks}))

    @property
    def has_withheld(self):
        return bool(self.withheld)

    @property
    def added_lines(self):
        """Mapping file -> sorted tuple of added line numbers, the ``added_lines`` argument of
        ``validation.validate_content`` (Git numbering)."""
        result = {}
        for hunk in self.hunks:
            result.setdefault(hunk.file, set()).update(hunk.added_lines)
        return {f: tuple(sorted(v)) for f, v in sorted(result.items())}


def _is_sealed(rendered):
    """True when ``rendered`` has the structure and the digest ``render_patch`` produced."""
    if type(rendered.hunks) is not tuple or type(rendered.withheld) is not tuple or type(rendered.text) is not str:
        return False
    if not all(type(h) is Hunk for h in rendered.hunks) or not all(type(f) is WithheldFinding for f in rendered.withheld):
        return False
    if not isinstance(rendered._digest, str) or not rendered._digest:
        return False
    return rendered._digest == _rendered_digest(rendered.hunks, rendered.withheld, rendered.text)


# --------------------------------------------------------------------------- rendering
def _split_lf(text):
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _body_text(entries):
    return "\n".join(c[:-1] if c.endswith("\n") else c for _t, c, _n in entries)


def _body_from_lines(lines):
    """The tag-free hunk body text re-derived from rendered hunk lines (header skipped)."""
    parts = []
    for line in lines[1:]:
        if line.startswith("\\"):
            continue
        parts.append(line[1:-1] if line.endswith("\n") else line[1:])
    return "\n".join(parts)


def _text_from_hunks(hunks):
    parts = []
    for file in sorted({h.file for h in hunks}):
        parts.append("--- a/%s\n+++ b/%s\n" % (file, file))
        parts.extend("".join(h.lines) for h in hunks if h.file == file)
    return "".join(parts)


def _pem_blocks(text):
    """1-based (begin, end) LF line ranges of PEM private-key blocks; END missing = last line."""
    lines = _split_lf(text)
    blocks, i = [], 0
    while i < len(lines):
        begin = _PEM_BEGIN.search(lines[i])
        if not begin:
            i += 1
            continue
        end = i
        if not _PEM_END.search(lines[i], begin.end()):
            end = i + 1
            while end < len(lines) and not _PEM_END.search(lines[end]):
                end += 1
            end = min(end, len(lines) - 1)
        blocks.append((i + 1, end + 1))
        i = end + 1
    return blocks


def _pem_overlap(blocks, start, count):
    """BEGIN lines of the blocks that overlap the hunk's line range in that document."""
    if not count:
        return set()
    last = start + count - 1
    return {b for b, e in blocks if b <= last and start <= e}


def _hunks_for(change, redactor):
    diff = list(
        difflib.unified_diff(
            _split_lf(change.original),
            _split_lf(change.proposed),
            fromfile="a/" + change.path,
            tofile="b/" + change.path,
            n=_CONTEXT,
        )
    )
    old_blocks = _pem_blocks(change.original)
    new_blocks = _pem_blocks(change.proposed)
    raw = []
    for line in diff[2:]:
        if line.startswith("@@"):
            raw.append([line, []])
        else:
            raw[-1][1].append(line)
    hunks = []
    for header, body in raw:
        match = _HUNK_HEADER.match(header)
        old_start, old_count, new_start, new_count = (
            int(match.group(1)),
            int(1 if match.group(2) is None else match.group(2)),
            int(match.group(3)),
            int(1 if match.group(4) is None else match.group(4)),
        )
        old_no = old_start if old_count else old_start + 1
        new_no = new_start if new_count else new_start + 1
        entries = []  # (tag, content, file line number)
        added = []
        for line in body:
            tag, content = line[0], line[1:]
            if tag == " ":
                entries.append((tag, content, new_no))
                old_no += 1
                new_no += 1
            elif tag == "-":
                entries.append((tag, content, old_no))
                old_no += 1
            else:
                entries.append((tag, content, new_no))
                added.append(new_no)
                new_no += 1
        text = _body_text(entries)
        found = set()
        withhold = False
        if redactor.contains_secret(text):
            withhold = True
            found = {entries[i - 1][2] for i in redactor.secret_line_numbers(text) if 1 <= i <= len(entries)}
            if not found:
                found = {entries[0][2]}
        pem = _pem_overlap(old_blocks, old_start, old_count) | _pem_overlap(new_blocks, new_start, new_count)
        if pem:
            withhold = True
            found |= pem
        if withhold:
            hunks.append(Hunk(change.path, old_start, old_count, new_start, new_count, (), tuple(added), True, tuple(sorted(found))))
            continue
        rendered = [header]
        for tag, content, _n in entries:
            rendered.append(tag + content if content.endswith("\n") else tag + content + "\n\\ No newline at end of file\n")
        hunks.append(Hunk(change.path, old_start, old_count, new_start, new_count, tuple(rendered), tuple(added)))
    return hunks


def _has_redactor_api(redactor):
    return callable(getattr(redactor, "contains_secret", None)) and callable(getattr(redactor, "secret_line_numbers", None))


def render_patch(changes, redactor):
    """Render documents as one unified diff and withhold hunks holding a secret-like value.

    ``redactor`` is injected and needs ``contains_secret(text)`` and
    ``secret_line_numbers(text)`` (the T02 API). A hunk is judged as a whole, context lines
    included (D8), and a hunk overlapping a PEM private-key block (also one that began in
    another hunk) is withheld regardless of the redactor. Pure: no file access. Files are
    sorted by path; identical documents produce no hunk. Duplicate paths are an error.
    """
    if not _has_redactor_api(redactor):
        raise TypeError("redactor must provide contains_secret and secret_line_numbers")
    changes = list(changes)
    if not all(isinstance(c, DocumentChange) for c in changes):
        raise TypeError("changes must contain only DocumentChange")
    paths = [c.path for c in changes]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate document path")
    hunks = []
    for change in sorted(changes, key=lambda c: c.path):
        hunks.extend(_hunks_for(change, redactor))
    findings = []
    for h in hunks:
        if h.withheld:
            findings.extend(WithheldFinding(h.file, n) for n in h.withheld_lines)
    withheld = tuple(dict.fromkeys(findings))  # one finding per file and line, in order
    hunks = tuple(hunks)
    text = "" if withheld else _text_from_hunks(hunks)
    return RenderedPatch(hunks, withheld, text, _rendered_digest(hunks, withheld, text))


def raise_if_withheld(rendered):
    """Raise WithheldHunksError (exit 10, P4) when any hunk is withheld."""
    if rendered.withheld:
        raise WithheldHunksError(rendered.withheld)


# ----------------------------------------------------------------------- preconditions
def _approval_seal(text, repository):
    return _keyed_digest("approved", text, repository)


@dataclass(frozen=True, slots=True)
class ApprovedPatch:
    """Content that passed render/withhold and validation. Build it only with
    ``approve_patch``; ``publish_patch`` refuses anything else. ``_seal`` is a keyed digest of
    ``text`` and ``repository``, so an instance with altered text (``dataclasses.replace``,
    direct attribute tampering) is refused."""

    text: str = ""
    repository: str = ""
    _seal: object = None

    def __post_init__(self):
        if not self._is_valid():
            raise UnexpectedStageError(_STAGE, "ApprovedPatch must be built by approve_patch")

    def _is_valid(self):
        return (
            isinstance(self.text, str)
            and isinstance(self.repository, str)
            and isinstance(self._seal, str)
            and self._seal == _approval_seal(self.text, self.repository)
        )

    def __repr__(self):
        return "ApprovedPatch(<%d characters>)" % len(self.text)


def approve_patch(rendered, validation, repository, unresolved, redactor):
    """Defense in depth (plan T13). Every failure here means the caller broke the sequence and
    is an unexpected internal failure (exit 12, UnexpectedStageError).

    ``unresolved`` (the in-scope changes with no proposed edit) and ``redactor`` are required;
    omitting either is a TypeError. ``unresolved`` must be EXACTLY a tuple, list, set or
    frozenset: ``type(unresolved) in (tuple, list, set, frozenset)``. A str, bytes, dict, None,
    generator, deque, namedtuple or any other subclass or object, even an empty or sized one, is
    refused with UnexpectedStageError like every other bad argument type (this function has
    always used that error, not TypeError, for wrong types); a non-empty exact collection is
    refused as an unresolved change. BEHAVIOR CHANGE (Attempt 4): earlier versions also accepted
    subclasses; those, and for example ``collections.deque``, are now refused, because a
    subclass can override ``__len__``, ``__bool__`` or ``__iter__`` and lie about being empty,
    while ``len`` of an exact built-in collection is trustworthy. This is still not proof: an
    in-process caller can pass an exact EMPTY collection while changes are in fact unresolved,
    and this function cannot verify that the caller is honest. Refuses: a ``RenderedPatch`` that ``render_patch`` did not
    produce unchanged (no seal, wrong digest, text not equal to what the hunks render to); a
    withheld hunk; a secret-like value found by ``redactor`` in the rendered text or in any hunk;
    a validation report that is not passed, a failed mandatory check, or a "not checked"
    mandatory check; empty output (D7); an unresolved in-scope change. The report cannot be
    bound to this content, so only its verdict is checked. A no-op ``redactor`` defeats the
    re-check (documented limitation). Messages carry counts, never content.
    """
    if not isinstance(rendered, RenderedPatch) or not isinstance(validation, ValidationReport):
        raise _refuse("rendered patch and validation report are required")
    if not _has_redactor_api(redactor):
        raise _refuse("a redactor with contains_secret and secret_line_numbers is required")
    if not isinstance(repository, (str, os.PathLike)) or not os.fspath(repository):
        raise _refuse("repository path is required")
    if not _is_sealed(rendered):
        raise _refuse("the rendered patch was not produced by render_patch or was altered")
    if rendered.withheld or any(h.withheld for h in rendered.hunks):
        raise _refuse("a hunk is withheld")
    mandatory = [r for r in validation.results if r.mandatory]
    if any(r.status is CheckStatus.FAILED for r in mandatory):
        raise _refuse("a mandatory check failed")
    if any(r.status is CheckStatus.NOT_CHECKED for r in mandatory):
        raise _refuse("a mandatory check is not checked")
    if not validation.passed:
        raise _refuse("validation did not pass")
    if not rendered.text or not rendered.hunks:
        raise _refuse("the output is empty")
    if type(unresolved) not in (tuple, list, set, frozenset):
        raise _refuse("unresolved must be exactly a tuple, list, set or frozenset")
    if len(unresolved):
        raise _refuse("an in-scope change is unresolved")
    if _text_from_hunks(rendered.hunks) != rendered.text:
        raise _refuse("the patch text does not match its hunks")
    suspicious = [h for h in rendered.hunks if redactor.contains_secret(_body_from_lines(h.lines))]
    if suspicious or redactor.contains_secret(rendered.text):
        raise _refuse("a secret-like value was found in the patch (%d hunk(s))" % len(suspicious))
    try:
        rendered.text.encode("utf-8")
    except UnicodeEncodeError:
        raise _refuse("the patch text is not encodable as UTF-8") from None
    repo = os.fspath(repository)
    return ApprovedPatch(rendered.text, repo, _approval_seal(rendered.text, repo))


# ----------------------------------------------------------------- destination handling
def _is_unc(path):
    path = os.fspath(path)
    if path.startswith("\\\\?\\") and len(path) > 5 and path[5] == ":":
        return False  # extended-length local drive path
    return path.startswith("\\\\") or path.startswith("//")


def _reparse(st):
    return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _inside(path, parent):
    path, parent = os.path.normcase(path), os.path.normcase(parent)
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:  # different drives
        return False


def _destination_text():
    return os.path.join(os.getcwd(), OUTPUT_DIR, PATCH_NAME)


def _is_link_like(path):
    """True when ``path`` ITSELF (its last component; nothing is resolved or followed) is a
    symbolic link, a Windows junction or any other reparse point, dangling or not. Uses
    ``lstat`` (symlink mode bit, ``FILE_ATTRIBUTE_REPARSE_POINT``) and then
    ``os.path.islink`` / ``os.path.isjunction``. A path that does not exist is not a link."""
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        st = None
    if st is not None and (stat.S_ISLNK(st.st_mode) or _reparse(st)):
        return True
    return bool(os.path.islink(path) or os.path.isjunction(path))


def _refuse_output_link(out):
    """Policy B: an ``output`` that is a link, junction or reparse point is refused (exit 11)
    BEFORE any real-path resolution of ``output``, so a link to a UNC location is never
    resolved and nothing is created through it."""
    if _is_link_like(out):
        raise _fail(
            "destination %s refused: %s is a symbolic link, junction or reparse point; "
            "output links are not followed; nothing was written" % (os.path.join(out, PATCH_NAME), out)
        )


def check_no_existing_patch():
    """Start-of-run pre-check (D29, exit 11). An ``output`` that is a link, junction or
    reparse point is refused first (policy B) without touching what it points at.
    ``os.path.lexists`` then makes a dangling symlink at the destination count as existing.
    The destination is fixed: ``output/docsync.patch`` under the working directory."""
    cwd = os.getcwd()
    if not _is_unc(cwd):
        _refuse_output_link(os.path.join(cwd, OUTPUT_DIR))
    dest = _destination_text()
    if os.path.lexists(dest):
        raise _fail("a patch already exists at %s; nothing was written (there is no --force)" % dest)


def _guard(repository):
    """Destination guard (architecture 2.6). Returns (real output dir, destination).

    Policy B: ``output`` itself must not be a link (refused before any resolution). Real paths
    (``os.path.realpath``; compared with ``normcase``, so case-insensitive on Windows) are
    resolved for the working directory, the repository, ``README.md``, ``docs`` and the
    destination file; ``realpath`` is never called on ``output``. UNC paths are refused first
    (see the module docstring for what that does not cover).
    """
    cwd = os.getcwd()
    repo = os.fspath(repository)
    out = os.path.join(cwd, OUTPUT_DIR)
    shown = os.path.join(out, PATCH_NAME)
    if _is_unc(cwd) or _is_unc(repo):
        raise _fail("destination %s refused: UNC paths are not supported" % shown)
    _refuse_output_link(out)
    if os.path.lexists(out) and not os.path.isdir(out):
        raise _fail("destination %s refused: output exists and is not a directory" % shown)
    real_out = os.path.join(os.path.realpath(cwd), OUTPUT_DIR)  # cwd and ancestors may be links
    dest = os.path.join(real_out, PATCH_NAME)
    real_dest = os.path.realpath(dest)  # a link at the destination file is still resolved
    real_repo = os.path.realpath(repo)
    readme = os.path.realpath(os.path.join(real_repo, "README.md"))
    docs = os.path.realpath(os.path.join(real_repo, "docs"))
    for candidate in (real_dest, real_out):
        if os.path.normcase(candidate) == os.path.normcase(readme) or _inside(candidate, docs):
            raise _fail("destination %s refused: it is README.md or inside docs/" % real_dest)
    return real_out, dest


def _refuse_if_present(dest):
    """Run immediately before ``os.open`` (M1): refuse if anything, including a symlink, a
    junction / reparse point or a dangling link, exists at the destination. ``O_EXCL`` stays on
    as the second line of defense; a link appearing after this check is the documented race."""
    exists = "a patch already exists at %s; nothing was written (there is no --force)" % dest
    if os.path.lexists(dest):
        raise _fail(exists)
    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _fail("could not inspect %s before creating it (errno %s); nothing was written" % (dest, exc.errno)) from None
    if stat.S_ISLNK(st.st_mode) or _reparse(st):
        raise _fail("a link or reparse point exists at %s; nothing was written" % dest)
    raise _fail(exists)


def _link_target(path):
    """One-hop target of a link at ``path`` resolved to a real path, or None (not a link,
    unreadable, or a UNC target that is not followed)."""
    try:
        target = os.readlink(path)
    except (OSError, ValueError):
        return None
    if not os.path.isabs(target):
        target = os.path.join(os.path.dirname(path), target)
    if _is_unc(target):
        return None
    if _is_link_like(target):
        return os.path.normpath(target)  # a chain is not followed (policy B): used by lstat only
    return os.path.realpath(target)


def _token_path():
    return os.path.join(os.path.realpath(os.getcwd()), OUTPUT_DIR, PATCH_NAME)


# ------------------------------------------------------------------------------ publish
def _check_token_fields(device, file_index, size, sha256, path):
    for name, value in (("device", device), ("file_index", file_index), ("size", size)):
        if type(value) is not int:
            raise TypeError("PatchToken.%s must be an int" % name)
    if size < 0:
        raise ValueError("PatchToken.size must not be negative")
    if not isinstance(sha256, str) or not _SHA256_HEX.match(sha256):
        raise ValueError("PatchToken.sha256 must be a 64-character lowercase hex string")
    if not isinstance(path, str) or not path or "\x00" in path:
        raise TypeError("PatchToken.path must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PatchToken:
    """Identity of the file ``publish_patch`` created: device, file index, size, SHA-256 of
    the content, and the absolute path ``<cwd>/output/docsync.patch`` (so a later change of
    working directory cannot redirect the rollback). Field types are checked at construction.
    On file systems without a stable file index ``file_index`` may be 0; the identity is then
    unusable and ``rollback_patch`` refuses to delete (documented limitation)."""

    device: int
    file_index: int
    size: int
    sha256: str
    path: str

    def __post_init__(self):
        _check_token_fields(self.device, self.file_index, self.size, self.sha256, self.path)


_OPEN_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL
    | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS = (
    os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_CLOEXEC", 0)
)


def _remove_if_ours(path, device, file_index):
    """Remove ``path`` only if it is a regular file with the given identity. Returns True if
    removed. An identity with ``st_ino`` 0 is unusable and never matches."""
    if file_index == 0:
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode) or _reparse(st) or (st.st_dev, st.st_ino) != (device, file_index):
        return False
    os.remove(path)
    return True


def _placed_at(dest, device, file_index):
    """True when ``dest`` is a regular, non-link file with the identity of the file created."""
    try:
        st = os.lstat(dest)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode) or _reparse(st):
        return False
    return file_index == 0 or (st.st_dev, st.st_ino) == (device, file_index)


def _cleanup(dest, device, file_index):
    """Remove the file this call created, by identity, at ``dest`` or at the one-hop target of a
    link at ``dest``. Returns (state, where): state is "removed", "foreign" (nothing with our
    identity was found; left untouched) or "leftover" (identity unusable or deletion failed)."""
    if device is None or file_index == 0:
        return "leftover", dest
    places = [dest]
    target = _link_target(dest)
    if target and os.path.normcase(target) != os.path.normcase(dest):
        places.append(target)
    for place in places:
        try:
            if _remove_if_ours(place, device, file_index):
                return "removed", place
        except OSError:
            return "leftover", place
    return "foreign", dest


def publish_patch(content):
    """Create ``output/docsync.patch`` (fixed, under the working directory) exclusively and
    return a PatchToken. Takes no destination argument.

    Refusals and write errors raise PatchWriteError (exit 11) and leave an existing path
    untouched; a partial file this call created is removed by identity. Any other exception
    also removes only that partial file and propagates (exit 12 through the caller). An
    ``ApprovedPatch`` whose seal does not match its text is refused (exit 12).
    """
    if not isinstance(content, ApprovedPatch) or not content._is_valid():
        raise _refuse("content has not passed approve_patch")
    data = content.text.encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    out_dir, dest = _guard(content.repository)
    token_path = _token_path()
    if not os.path.lexists(out_dir):
        try:
            os.mkdir(out_dir)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _fail("could not create the output directory for %s (errno %s)" % (dest, exc.errno)) from None
        out_dir, dest = _guard(content.repository)
    _refuse_output_link(out_dir)  # policy B, again immediately before os.open
    _refuse_if_present(dest)  # immediately before os.open (M1)
    try:
        fd = os.open(dest, _OPEN_FLAGS, 0o666)
    except OSError as exc:
        if os.path.lexists(dest):
            raise _fail("a patch already exists at %s; nothing was written (there is no --force)" % dest) from None
        raise _fail("could not create %s (errno %s)" % (dest, exc.errno)) from None
    device = file_index = None
    handle = None
    try:
        st = os.fstat(fd)
        device, file_index = st.st_dev, st.st_ino
        handle = os.fdopen(fd, "wb")
        fd = None
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        _guard(content.repository)  # the link may have been swapped after the first check
        if not _placed_at(dest, device, file_index):
            raise _Misplaced()  # a link was followed: the file is somewhere else
        return PatchToken(device, file_index, len(data), sha, token_path)
    except BaseException as exc:
        for opened in (handle, fd):
            try:
                if hasattr(opened, "close"):
                    opened.close()
                elif opened is not None:
                    os.close(opened)
            except OSError:
                pass
        state, where = _cleanup(dest, device, file_index)
        if isinstance(exc, _Misplaced):
            if state == "removed":
                raise _fail("%s was not the file this call created (a link was followed); the file written through it at %s was removed" % (dest, where)) from None
            raise _fail("%s was not the file this call created (a link was followed); a stray file may remain at the link target of %s and must be checked and removed by hand" % (dest, dest)) from None
        if state == "leftover" and isinstance(exc, (OSError, PatchWriteError)):
            raise _fail("write to %s failed and the partial file could not be removed" % dest) from None
        if isinstance(exc, PatchWriteError):
            raise
        if isinstance(exc, OSError):
            if state == "removed":
                note = "the partial file was removed" if where == dest else "the partial file was removed from the link target %s" % where
            else:
                note = "the path holds a different file, left untouched"
            raise _fail("could not write %s (errno %s); %s" % (dest, exc.errno, note)) from None
        raise


def _token_path_problem(path):
    """Why ``path`` is not exactly an absolute ``<dir>/output/docsync.patch``, or None."""
    if not os.path.isabs(path) or _is_unc(path) or os.path.normpath(path) != path:
        return "the token path is not a normalized absolute local path"
    parent, name = os.path.split(path)
    if name != PATCH_NAME or os.path.basename(parent) != OUTPUT_DIR:
        return "the token path is not an output/%s path" % PATCH_NAME
    return None


def rollback_patch(token):
    """Delete the patch only if the token's path is exactly an absolute ``<dir>/output/docsync.patch``
    AND it is a regular file (not a link) whose device, file index, size and SHA-256 equal
    ``token``. Returns True if deleted, False if the path is absent or holds anything else (left
    untouched). A token that is not a PatchToken, has wrongly typed fields, or has any other
    path raises UnexpectedStageError (exit 12) before any file is touched. Raises RollbackError,
    naming the path, if the file is ours but cannot be read or deleted (for example it is held
    open) or if its identity is unusable (``st_ino`` 0). A change between the check and the
    delete is not detected."""
    if not isinstance(token, PatchToken):
        raise _refuse("rollback requires the token returned by publish_patch")
    try:
        _check_token_fields(token.device, token.file_index, token.size, token.sha256, token.path)
    except (TypeError, ValueError):
        raise _refuse("the rollback token is malformed") from None
    path = token.path
    problem = _token_path_problem(path)
    if problem:
        raise _refuse("rollback refused: " + problem)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RollbackError(path, "cannot inspect it (errno %s)" % exc.errno) from None
    if not stat.S_ISREG(st.st_mode) or _reparse(st):
        return False
    if token.file_index == 0:
        raise RollbackError(path, "the file identity is unusable (file index 0); remove it by hand if it is yours")
    if (st.st_dev, st.st_ino, st.st_size) != (token.device, token.file_index, token.size):
        return False
    try:
        fd = os.open(path, _READ_FLAGS)
        with os.fdopen(fd, "rb") as handle:
            st2 = os.fstat(handle.fileno())
            if (st2.st_dev, st2.st_ino, st2.st_size) != (token.device, token.file_index, token.size):
                return False
            digest = hashlib.sha256(handle.read(token.size + 1)).hexdigest()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RollbackError(path, "cannot read it (errno %s)" % exc.errno) from None
    if digest != token.sha256:
        return False
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RollbackError(path, "cannot delete it (errno %s)" % exc.errno) from None
    return True
