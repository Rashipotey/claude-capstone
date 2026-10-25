"""Doc Mapper and Target Resolver stage. Maps source files to documentation targets (D19).

Implemented in plan task T08 (mapping). Target resolution (T09) consumes its output.

T08 rules (P5, D19 Option B, D17), path-based only:

* Candidates are ``README.md`` and Markdown files directly under ``docs/`` in the working
  tree. Markdown elsewhere, and ``docs/sub/a.md``, are not candidates.
* A SOURCE change maps to ``docs/<module>.md`` if it exists, otherwise ``README.md`` if it
  exists, otherwise to no candidate. At most one candidate per change; nothing is chosen
  among several.
* Ambiguity (E7): if several docs share the change's lowercased stem (``docs/P.md`` and
  ``docs/p.md``), none is chosen and README is not used as a fallback. The change's
  ``MappingResult`` has no candidate and no skip reason, and the change is listed in
  ``MappingOutcome.ambiguous`` as ``(source_path, sorted matching docs)``. T09 must treat
  a non-empty ``ambiguous`` as a "multiple matching docs" refusal (exit 8), not as exit 7.
* Module name: the file name with its last extension removed, lowercased; directories are
  ignored; ``__init__.py`` uses the parent directory's name; non-Python files use the same
  rule. The doc is matched by lowercased stem and its actual path is reported.
* Documentation, test, generated, deleted and unsupported files are not mapped; each gets
  a ``MappingResult`` with a skip reason. The category comes from the Change Analyzer
  (this module does not import it), so an unclassified file is refused.

The module reads the working tree only to list candidates, never writes, and never opens a
file. Repository text is data. Paths in results are unredacted structured fields; output
stages redact them.
"""

import os
from dataclasses import dataclass
from pathlib import PurePosixPath

from docsync.contracts import ChangedFile, FileCategory, InputOrGitError, MappingResult

__all__ = [
    "NO_SUITABLE_TARGET_MESSAGE",
    "MappingOutcome",
    "discover_candidates",
    "module_name",
    "map_changes",
]

README = "README.md"
DOCS_DIR = "docs"
NO_SUITABLE_TARGET_MESSAGE = "no suitable documentation target"

_SKIP_REASONS = {
    FileCategory.DOCUMENTATION: "documentation file, not mapped",
    FileCategory.TEST: "test file, not mapped",
    FileCategory.GENERATED: "generated file, not mapped",
    FileCategory.DELETED: "deleted file, not mapped",
    FileCategory.UNSUPPORTED: "unsupported file type, not mapped",
}


@dataclass(frozen=True, slots=True)
class MappingOutcome:
    """Run-level mapping output. All sequences are tuples sorted by code point."""

    results: tuple = ()      # MappingResult, one per change, sorted by source_path
    candidates: tuple = ()   # sorted distinct docs that at least one change maps to
    ambiguous: tuple = ()    # (source_path, sorted docs) per change with several matching docs

    @property
    def has_candidates(self):
        """False means "no suitable documentation target" (T09 maps this to exit 7)."""
        return bool(self.candidates)

    @property
    def has_ambiguity(self):
        """True means at least one change matches several docs; nothing was chosen (E7)."""
        return bool(self.ambiguous)

    @property
    def unmapped(self):
        """Sorted source paths that were analyzed but have no candidate (not skipped)."""
        ambiguous = {path for path, _ in self.ambiguous}
        return tuple(r.source_path for r in self.results
                     if r.candidate is None and r.skipped_reason is None
                     and r.source_path not in ambiguous)

    @property
    def skipped(self):
        return tuple(r for r in self.results if r.skipped_reason is not None)


# ------------------------------------------------------------------------ discovery
def _is_plain_file(entry):
    try:
        return entry.is_file(follow_symlinks=False)
    except OSError:
        return False


def discover_candidates(repo_root):
    """Return the sorted tuple of candidate docs under ``repo_root`` (read-only).

    ``README.md`` at the root and ``docs/*.md`` directly under ``docs/``. Symbolic links
    are not candidates. A missing ``docs`` directory or README simply gives fewer
    candidates; an unusable ``repo_root`` raises ``InputOrGitError``.
    """
    root = str(repo_root)
    if not root.strip() or not os.path.isdir(root):
        raise InputOrGitError("mapping", "repository path is not a directory")
    found = []
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.name == README and _is_plain_file(entry):
                    found.append(README)
        docs = os.path.join(root, DOCS_DIR)
        if os.path.isdir(docs) and not os.path.islink(docs):
            with os.scandir(docs) as it:
                for entry in it:
                    if entry.name.endswith(".md") and len(entry.name) > 3 and _is_plain_file(entry):
                        found.append("%s/%s" % (DOCS_DIR, entry.name))
    except OSError:
        raise InputOrGitError("mapping", "documentation files could not be listed") from None
    return tuple(sorted(found))


# ---------------------------------------------------------------------------- rules
def module_name(path):
    """Return the lowercased module name of a changed file path (D19, D17)."""
    pure = PurePosixPath(path.replace("\\", "/"))
    name = pure.name
    if name == "__init__.py" and pure.parent.name:
        return pure.parent.name.lower()
    return PurePosixPath(name).stem.lower()


def _check_candidates(candidates):
    if isinstance(candidates, (str, bytes)):
        raise TypeError("candidates must be a sequence of paths")
    items = tuple(candidates)
    for item in items:
        if not isinstance(item, str):
            raise TypeError("candidates must contain only strings")
        parts = item.split("/")
        direct_doc = len(parts) == 2 and parts[0] == DOCS_DIR and item.endswith(".md") and len(parts[1]) > 3
        if item != README and not direct_doc:
            raise ValueError("not a documentation candidate: %r" % item)
    return tuple(sorted(set(items)))


def map_changes(files, candidates):
    """Map each change to at most one candidate. Returns a ``MappingOutcome``.

    ``files`` are ``ChangedFile`` records whose category is set by the Change Analyzer;
    ``candidates`` are the docs that exist (see ``discover_candidates``). Pure and
    deterministic: the same input gives the same output in the same order.
    """
    if isinstance(files, (str, bytes)):
        raise TypeError("files must be a sequence of ChangedFile")
    records = tuple(files)
    if not all(isinstance(f, ChangedFile) for f in records):
        raise TypeError("files must contain only ChangedFile")
    docs = _check_candidates(candidates)

    by_stem = {}
    for doc in docs:  # sorted, so each list is sorted by code point
        if doc != README:
            by_stem.setdefault(doc[len(DOCS_DIR) + 1:-3].lower(), []).append(doc)
    has_readme = README in docs

    results = []
    ambiguous = []
    for entry in sorted(records, key=lambda f: f.path):
        category = entry.category
        if category is FileCategory.UNCLASSIFIED:
            raise ValueError("file has no category; run the Change Analyzer first")
        if category is not FileCategory.SOURCE:
            results.append(MappingResult(entry.path, skipped_reason=_SKIP_REASONS[category]))
            continue
        matches = by_stem.get(module_name(entry.path), [])
        if len(matches) > 1:
            ambiguous.append((entry.path, tuple(matches)))
            results.append(MappingResult(entry.path))
            continue
        doc = matches[0] if matches else (README if has_readme else None)
        results.append(MappingResult(entry.path, candidate=doc))

    distinct = tuple(sorted({r.candidate for r in results if r.candidate is not None}))
    return MappingOutcome(results=tuple(results), candidates=distinct,
                          ambiguous=tuple(ambiguous))
