"""Proposal Builder (plan task T10b): proposed document text from the proposed edits.

Turns T10's ``ProposedEdit`` objects into the proposed text of each target document plus
the 1-based LF line numbers the edit adds. Imports only ``docsync.contracts``; it returns its
own result types and never imports ``docsync.output`` (T15 builds ``DocumentChange``).

The only side effect is calling the injected, read-only ``read_text(path) -> str | None``.
No Not Found item, skipped record, rejection record, error text, ``repr`` or ``str`` carries
a reason, a symbol name or document text: they hold fixed phrases only. A target that passed
the path rule appears only in the structured ``path``/``target``/``files`` fields; a target
that failed the rule is never echoed. The ``repr`` of these types hides paths and texts.
"""

import re
from dataclasses import dataclass, field

from docsync.contracts import NotFoundItem, ProposedEdit

__all__ = [
    "MAX_ORIGINAL_CHARS",
    "MAX_REASON_CHARS",
    "MAX_SYMBOL_CHARS",
    "MAX_SYMBOLS",
    "HEADING",
    "ProposedDocument",
    "SkippedDocument",
    "RejectedEdit",
    "ProposalResult",
    "build_proposals",
]

MAX_ORIGINAL_CHARS = 1_000_000
MAX_REASON_CHARS = 200
MAX_SYMBOL_CHARS = 128
MAX_SYMBOLS = 50

HEADING = "## Proposed documentation update"

# Fixed phrases (never built from input).
SKIP_INVALID_PATH = "invalid target path"
SKIP_UNREADABLE = "document missing, unreadable or not valid UTF-8"
SKIP_NUL = "document contains a NUL character"
SKIP_TOO_LARGE = "document exceeds the size limit"
SKIP_ALL_REJECTED = "all edits rejected"
SKIP_REASONS = (SKIP_INVALID_PATH, SKIP_UNREADABLE, SKIP_NUL, SKIP_TOO_LARGE, SKIP_ALL_REJECTED)

RULE_REASON = "reason-not-allowed"
RULE_SYMBOL = "symbol-name-not-allowed"
RULE_TOO_MANY = "too-many-symbols"
REJECT_RULES = (RULE_REASON, RULE_SYMBOL, RULE_TOO_MANY)

_SUBJECT_TARGET = "Documentation target"
_SUBJECT_EDIT = "Proposed documentation edit"
_DETAIL = {
    SKIP_INVALID_PATH: "Not Found: invalid target path, no proposed text built",
    SKIP_UNREADABLE: "Not Found: the document is missing, unreadable or not valid UTF-8, no proposed text built",
    SKIP_NUL: "Not Found: the document contains a NUL character, no proposed text built",
    SKIP_TOO_LARGE: "Not Found: the document exceeds the size limit, no proposed text built",
    SKIP_ALL_REJECTED: "Not Found: every proposed edit for the document was rejected, no proposed text built",
}
_DETAIL_REJECTED = "Not Found: edit rejected because a value is not safe to insert"

_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
_REASON_FORBIDDEN = frozenset("`<>[]()|~\\&")
_REASON_BAD_START = frozenset(" #>-+*=")
_ORDERED_LIST = re.compile(r"[0-9]+[.)]")


# ------------------------------------------------------------------------ path rule
def _check_path(path):
    """Same rule as ``DocumentChange`` (re-implemented, not imported). Raises ValueError."""
    if not isinstance(path, str) or not path:
        raise ValueError("document path must be a non-empty string")
    if any(ord(c) < 32 or ord(c) == 127 for c in path) or "\\" in path:
        raise ValueError("document path must not contain control characters or backslashes")
    parts = path.split("/")
    if path.startswith("/") or ":" in parts[0] or any(p in ("", ".", "..") for p in parts):
        raise ValueError("document path must be relative, with no empty, '.' or '..' segment")
    if not (path == "README.md" or (parts[0] == "docs" and len(parts) > 1 and path.endswith(".md"))):
        raise ValueError("document path must be README.md or a Markdown file under docs/")


def _path_ok(path):
    try:
        _check_path(path)
    except ValueError:
        return False
    return True


# ------------------------------------------------------------------------ result types
@dataclass(frozen=True, slots=True)
class ProposedDocument:
    """One document with its proposed text. ``added_lines``: 1-based LF line numbers, in
    ``proposed``, of the generated lines only. ``repr`` hides the path and both texts."""

    path: str = field(repr=False)
    original: str = field(repr=False)
    proposed: str = field(repr=False)
    added_lines: tuple = ()

    def __post_init__(self):
        _check_path(self.path)
        for name in ("original", "proposed"):
            if not isinstance(getattr(self, name), str):
                raise TypeError("%s must be a string" % name)
        if self.proposed == self.original:
            raise ValueError("a proposed document must differ from its original")
        lines = tuple(self.added_lines)
        for n in lines:
            if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                raise ValueError("added_lines must be positive integers")
        object.__setattr__(self, "added_lines", lines)


@dataclass(frozen=True, slots=True)
class SkippedDocument:
    """A document for which no change was built. ``path`` is None for an invalid target."""

    path: str | None = field(repr=False)
    reason: str

    def __post_init__(self):
        if self.path is not None:
            _check_path(self.path)
        if self.reason not in SKIP_REASONS:
            raise ValueError("reason must be one of the fixed phrases")


@dataclass(frozen=True, slots=True)
class RejectedEdit:
    """A rejected edit: the path-valid target (or None) and a fixed rule name."""

    target: str | None = field(repr=False)
    rule: str

    def __post_init__(self):
        if self.target is not None:
            _check_path(self.target)
        if self.rule not in REJECT_RULES:
            raise ValueError("rule must be one of the fixed rule names")


@dataclass(frozen=True, slots=True, repr=False)
class ProposalResult:
    documents: tuple = ()
    skipped: tuple = ()
    rejected: tuple = ()
    not_found: tuple = ()

    def __post_init__(self):
        for name, kind in (
            ("documents", ProposedDocument),
            ("skipped", SkippedDocument),
            ("rejected", RejectedEdit),
            ("not_found", NotFoundItem),
        ):
            items = tuple(getattr(self, name))
            if not all(isinstance(i, kind) for i in items):
                raise TypeError("%s must contain only %s" % (name, kind.__name__))
            object.__setattr__(self, name, items)

    def __repr__(self):
        return "ProposalResult(documents=%d, skipped=%d, rejected=%d, not_found=%d)" % (
            len(self.documents), len(self.skipped), len(self.rejected), len(self.not_found))

    __str__ = __repr__


# ------------------------------------------------------------------------ value checks
def _reason_ok(reason):
    if not isinstance(reason, str) or not reason or len(reason) > MAX_REASON_CHARS:
        return False
    if not all(0x20 <= ord(c) <= 0x7E for c in reason):
        return False
    if any(c in _REASON_FORBIDDEN for c in reason):
        return False
    if reason[0] in _REASON_BAD_START or _ORDERED_LIST.match(reason):
        return False
    return True


def _symbol_ok(name):
    return (
        isinstance(name, str)
        and 0 < len(name) <= MAX_SYMBOL_CHARS
        and _SYMBOL.fullmatch(name) is not None
    )


def _edit_rule(edit):
    """The fixed rule name that rejects the edit, or None if all values may be inserted."""
    if not _reason_ok(edit.reason):
        return RULE_REASON
    if len(edit.symbol_names) > MAX_SYMBOLS:
        return RULE_TOO_MANY
    if not all(_symbol_ok(n) for n in edit.symbol_names):
        return RULE_SYMBOL
    return None


# ------------------------------------------------------------------------ text building
def _is_blank(segment):
    if segment.endswith("\r"):
        segment = segment[:-1]
    return segment.strip(" ") == ""


def _build(original, items):
    """Return (proposed, added_lines) for accepted ``items`` = [(reason, symbols), ...]."""
    base = original
    added = []
    if base:
        if not base.endswith("\n"):
            base += "\n"  # terminates the last line; not counted as an added line
        line_no = base.count("\n")
        last = base[:-1].rsplit("\n", 1)[-1]
        if not _is_blank(last):
            base += "\n"
            line_no += 1
            added.append(line_no)
    else:
        line_no = 0
    block = [HEADING, ""]
    for reason, symbols in items:
        block.append("- " + reason)
        if symbols:
            block.append("  Changed symbols: " + ", ".join(symbols))
    for line in block:
        line_no += 1
        added.append(line_no)
    return base + "\n".join(block) + "\n", tuple(added)


def _sorted_key_path(path, extra=""):
    return (path is None, path or "", extra)


# ------------------------------------------------------------------------ entry point
def build_proposals(edits, read_text):
    """Build the proposed documents for ``edits`` (iterable of ``ProposedEdit``).

    ``read_text(path) -> str | None`` is called only for a path-valid target that still has
    at least one acceptable edit, and only once per document. ``None`` (or a non-string)
    means missing, unreadable, outside the tree or not UTF-8. An exception raised by the
    reader is not caught. Returns a ``ProposalResult``; an empty ``edits`` gives an empty one.
    """
    if not callable(read_text):
        raise TypeError("read_text must be callable")
    if isinstance(edits, (str, bytes)):
        raise TypeError("edits must be an iterable of ProposedEdit")
    edits = tuple(edits)
    if not all(isinstance(e, ProposedEdit) for e in edits):
        raise TypeError("edits must contain only ProposedEdit")

    groups = {}  # target -> [edit], insertion ordered (T10 order kept)
    for edit in edits:
        groups.setdefault(edit.target, []).append(edit)

    documents, skipped, rejected, not_found = [], [], [], []

    def skip(path, why, files=()):
        skipped.append(SkippedDocument(path, why))
        subject = _SUBJECT_TARGET
        not_found.append(NotFoundItem(subject, _DETAIL[why], files))

    for target, group in groups.items():
        if not _path_ok(target):
            skip(None, SKIP_INVALID_PATH)
            continue
        accepted, seen = [], set()
        for edit in group:
            rule = _edit_rule(edit)
            if rule is not None:
                rejected.append(RejectedEdit(target, rule))
                not_found.append(NotFoundItem(_SUBJECT_EDIT, _DETAIL_REJECTED, (target,)))
                continue
            symbols = tuple(sorted(set(edit.symbol_names)))
            key = (edit.reason, symbols)
            if key in seen:
                continue
            seen.add(key)
            accepted.append(key)
        if not accepted:
            skip(target, SKIP_ALL_REJECTED, (target,))
            continue
        original = read_text(target)
        if not isinstance(original, str):
            skip(target, SKIP_UNREADABLE, (target,))
            continue
        if "\x00" in original:
            skip(target, SKIP_NUL, (target,))
            continue
        if len(original) > MAX_ORIGINAL_CHARS:
            skip(target, SKIP_TOO_LARGE, (target,))
            continue
        proposed, added_lines = _build(original, accepted)
        documents.append(ProposedDocument(target, original, proposed, added_lines))

    return ProposalResult(
        documents=sorted(documents, key=lambda d: d.path),
        skipped=sorted(skipped, key=lambda s: _sorted_key_path(s.path, s.reason)),
        rejected=sorted(rejected, key=lambda r: _sorted_key_path(r.target, r.rule)),
        not_found=sorted(not_found, key=lambda n: (n.subject, n.detail, n.files)),
    )
