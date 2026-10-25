"""Change Analyzer stage. Parses the diff, classifies files, extracts symbol names.

Implemented in plan tasks T07 and T07b (generated-file rule, D13; very large files are
not analyzed separately and have no per-file threshold, D14: they count toward the Size
Gate cap only).

Input: the ``ChangedFile`` records of the diff (already passed by the Size Gate, so binary,
mode-only and submodule entries are gone) and the raw unified diff text. Repository and
diff text is data: it is split, matched and parsed, never executed or obeyed (AC-08).

Classification, first match wins:

* status ``D``                                     -> DELETED (listed as not analyzed)
* status ``T`` (type change), or a diff section
  holding a binary marker or a NUL byte            -> UNSUPPORTED
* a generated path (D13, see below)                -> GENERATED (skipped, reported)
* ``README.md`` or a path under ``docs/``          -> DOCUMENTATION (skipped, reported)
* a ``test`` or ``tests`` directory, ``test_*.py``
  or ``*_test.py``                                 -> TEST (skipped, reported)
* anything else                                    -> SOURCE

Generated paths (D13): ``*.lock`` and ``*.min.*`` match the file name at any depth;
``dist/**`` and ``build/**`` match from the repository root. Matching is case-sensitive and
on the path only. Only SOURCE files go on to mapping.

Symbols (D17, D20): for a ``.py`` SOURCE file the changed symbol names come from ``ast``.
The new file text is obtained through an injected ``read_text(path)`` callable (the Analyzer
never runs Git and opens no file itself unless the caller passes ``working_tree_reader``).
A function or class counts as changed when an added line falls on its own lines (its span
minus nested definitions), or a deleted line was inside it. Names are qualified
(``Class.method``). Every other source file gets a generic text diff only and no symbol
names, and that is reported as a limitation.

Module boundary: no other stage is imported. The redaction function is injected.
"""

import ast
import re
from fnmatch import fnmatchcase
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from docsync.contracts import ChangedFile, FileCategory

__all__ = [
    "FileEvidence",
    "SkippedFile",
    "AnalysisResult",
    "classify",
    "parse_diff_sections",
    "extract_python_symbols",
    "working_tree_reader",
    "analyze",
]

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

LANG_PYTHON = "python"
LANG_GENERIC = "generic"


# ------------------------------------------------------------------------ results
@dataclass(frozen=True, slots=True)
class FileEvidence:
    """Evidence for one SOURCE file. ``note`` says why symbol names are absent, else None."""

    path: str
    language: str
    symbol_names: tuple = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """A file excluded from generation, with its category and the reason."""

    path: str
    category: FileCategory
    reason: str


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Sorted analysis output. All sequences are tuples sorted by path (code points)."""

    files: tuple = ()      # every ChangedFile, with category set
    evidence: tuple = ()   # FileEvidence, SOURCE files only
    skipped: tuple = ()    # SkippedFile, every non-SOURCE file
    limitations: tuple = ()  # human-readable lines for the report

    @property
    def source_files(self):
        return tuple(f for f in self.files if f.category is FileCategory.SOURCE)

    @property
    def has_source_files(self):
        """False means nothing is left to map (the orchestrator maps this to exit 4)."""
        return bool(self.source_files)


# --------------------------------------------------------------------- diff parsing
def _unquote(text):
    """Undo Git's C-style quoting of a path. Unquoted text is returned unchanged."""
    if len(text) < 2 or not (text.startswith('"') and text.endswith('"')):
        return text
    body = text[1:-1]
    out = bytearray()
    i = 0
    simple = {"n": 10, "t": 9, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11, '"': 34, "\\": 92}
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567":
                digits = body[i + 1:i + 4]
                m = re.match(r"[0-7]{1,3}", digits)
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
        out.extend(ch.encode("utf-8"))
        i += 1
    return out.decode("utf-8", "replace")


def _resolve_path(raw, known):
    """Match a header path (with or without a one-segment prefix) to a known path."""
    path = _unquote(raw.rstrip("\t"))
    if len(path) > 2 and path[1] == "/" and path[2:] in known:
        return path[2:]
    if path in known:
        return path
    return None


def parse_diff_sections(diff_text, known_paths):
    """Split ``diff_text`` into per-file sections.

    Returns ``{path: lines}`` where ``lines`` is the list of the section's lines. A path is
    taken from the ``+++``, ``---``, ``rename to`` or ``copy to`` header and must be one of
    ``known_paths``; a section that matches none is ignored. Never raises on odd text.
    """
    known = set(known_paths)
    sections = []
    current = None
    for line in str(diff_text).split("\n"):
        if line.startswith("diff --git "):
            current = [line]
            sections.append(current)
        elif current is not None:
            current.append(line)
    result = {}
    for lines in sections:
        path = None
        candidates = []
        for line in lines[1:]:
            if line.startswith("@@ "):
                break
            if line.startswith("+++ ") and line[4:] != "/dev/null":
                candidates.insert(0, line[4:])
            elif line.startswith("--- ") and line[4:] != "/dev/null":
                candidates.append(line[4:])
            elif line.startswith("rename to ") or line.startswith("copy to "):
                candidates.insert(0, line.split(" to ", 1)[1])
        for cand in candidates:
            path = _resolve_path(cand, known)
            if path:
                break
        if path and path not in result:
            result[path] = lines
    return result


def _changed_lines(section):
    """Return (added_new_line_numbers, deletion_positions) from a section's hunks.

    A deletion position p means lines were removed between new lines p-1 and p.
    """
    added = set()
    deletions = set()
    new_no = None
    for line in section:
        m = _HUNK.match(line)
        if m:
            new_no = int(m.group(3))
            continue
        if new_no is None:
            continue
        if line.startswith("+"):
            added.add(new_no)
            new_no += 1
        elif line.startswith("-"):
            deletions.add(new_no)
        elif line.startswith("\\"):
            continue
        elif line.startswith(" "):
            new_no += 1
        # an empty line or the next section header ends nothing here; ignored
    return added, deletions


# ------------------------------------------------------------------ classification
def _is_test_path(path):
    parts = PurePosixPath(path).parts
    if any(p in ("test", "tests") for p in parts[:-1]):
        return True
    name = parts[-1] if parts else path
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py")


def _is_documentation(path):
    return path == "README.md" or path.startswith("docs/")


def _section_is_unsupported(section):
    if section is None:
        return False
    for line in section:
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            return True
        if "\0" in line:
            return True
    return False


def _generated_pattern(path):
    """Return the D13 pattern the path matches, or None."""
    parts = PurePosixPath(path).parts
    if not parts:
        return None
    name = parts[-1]
    if fnmatchcase(name, "*.lock"):
        return "*.lock"
    if fnmatchcase(name, "*.min.*"):
        return "*.min.*"
    if len(parts) > 1 and parts[0] == "dist":
        return "dist/**"
    if len(parts) > 1 and parts[0] == "build":
        return "build/**"
    return None


def classify(entry, section=None):
    """Return the ``FileCategory`` of one ``ChangedFile``."""
    if entry.status.startswith("D"):
        return FileCategory.DELETED
    if entry.status.startswith("T") or _section_is_unsupported(section):
        return FileCategory.UNSUPPORTED
    if _generated_pattern(entry.path):
        return FileCategory.GENERATED
    if _is_documentation(entry.path):
        return FileCategory.DOCUMENTATION
    if _is_test_path(entry.path):
        return FileCategory.TEST
    return FileCategory.SOURCE


_SKIP_REASONS = {
    FileCategory.DELETED: "deleted file, not analyzed",
    FileCategory.UNSUPPORTED: "unsupported file type",
    FileCategory.DOCUMENTATION: "documentation file, not a source change",
    FileCategory.TEST: "test file, not a source change",
}


# ---------------------------------------------------------------- Python symbols
def _definitions(tree):
    """Yield (qualified_name, start, end, child_spans) for every def and class."""
    found = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                end = child.end_lineno or child.lineno
                found.append([name, start, end, []])
                index = len(found) - 1
                before = len(found)
                visit(child, name + ".")
                # direct children are the entries added after ``before`` that sit one level down
                for entry in found[before:]:
                    if entry[0].count(".") == name.count(".") + 1:
                        found[index][3].append((entry[1], entry[2]))
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def extract_python_symbols(source, added, deletions):
    """Return the sorted tuple of changed symbol names, or None if ``source`` does not parse.

    ``added`` is the set of added new-side line numbers; ``deletions`` the set of positions
    where lines were removed (between line p-1 and p).
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    names = set()
    for name, start, end, children in _definitions(tree):
        def own(n):
            return start <= n <= end and not any(a <= n <= b for a, b in children)

        if any(own(n) for n in added):
            names.add(name)
            continue
        for p in deletions:
            if start <= p - 1 and p <= end and own(p - 1) and own(p):
                names.add(name)
                break
    return tuple(sorted(names))


def working_tree_reader(repo_root):
    """Return a read-only ``read_text(path)`` for files under ``repo_root``.

    It returns the UTF-8 text of a regular file inside the root, or None when the path
    escapes the root, is missing or unreadable, or is not valid UTF-8. It never writes.
    """
    from pathlib import Path

    root = Path(repo_root).resolve()

    def read_text(path):
        try:
            target = (root / path).resolve()
            target.relative_to(root)
            if not target.is_file():
                return None
            return target.read_bytes().decode("utf-8")
        except (OSError, ValueError, UnicodeDecodeError):
            return None

    return read_text


# ------------------------------------------------------------------------ analyze
def _printable(text):
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)


def analyze(files, diff_text, *, redactor, read_text=None):
    """Classify ``files`` and gather symbol evidence. Returns an ``AnalysisResult``."""
    if not callable(redactor):
        raise TypeError("redactor must be callable")
    if read_text is not None and not callable(read_text):
        raise TypeError("read_text must be callable or None")
    if isinstance(files, (str, bytes)):
        raise TypeError("files must be a sequence of ChangedFile")
    records = tuple(files)
    if not all(isinstance(f, ChangedFile) for f in records):
        raise TypeError("files must contain only ChangedFile")
    if not isinstance(diff_text, str):
        raise TypeError("diff_text must be a string")

    sections = parse_diff_sections(diff_text, [f.path for f in records])
    classified = []
    for entry in sorted(records, key=lambda f: f.path):
        classified.append(replace(entry, category=classify(entry, sections.get(entry.path))))

    evidence = []
    skipped = []
    limitations = []
    for entry in classified:
        shown = _printable(entry.path)
        if entry.category is not FileCategory.SOURCE:
            reason = _SKIP_REASONS.get(entry.category)
            if entry.category is FileCategory.GENERATED:
                reason = "generated file (matches %s), skipped" % _generated_pattern(entry.path)
            skipped.append(SkippedFile(entry.path, entry.category, reason))
            limitations.append("%s: skipped, %s" % (shown, reason))
            continue
        if not entry.path.endswith(".py"):
            note = "generic text diff only, no symbol names for this file type"
            evidence.append(FileEvidence(entry.path, LANG_GENERIC, (), note))
            limitations.append("%s: %s" % (shown, note))
            continue
        section = sections.get(entry.path)
        note = None
        symbols = ()
        if section is None:
            note = "no diff text found for this file, no symbol names"
        elif read_text is None:
            note = "file text unavailable, no symbol names"
        else:
            text = read_text(entry.path)
            added, deletions = _changed_lines(section)
            if text is None:
                note = "file text unavailable, no symbol names"
            else:
                found = extract_python_symbols(text, added, deletions)
                if found is None:
                    note = "file could not be parsed as Python, no symbol names"
                elif not found:
                    note = "no function or class changed, no symbol names"
                else:
                    symbols = found
        evidence.append(FileEvidence(entry.path, LANG_PYTHON, symbols, note))
        if note:
            limitations.append("%s: %s" % (shown, note))

    return AnalysisResult(
        files=tuple(classified),
        evidence=tuple(evidence),
        skipped=tuple(skipped),
        limitations=tuple(redactor(line) for line in limitations),
    )
