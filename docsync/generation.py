"""Doc Generator stage. Builds proposed edits from the diff, deterministically (D20).

Implemented in plan task T10. Pure and in memory: no file is read or written.

Rules (requirements 6b.7, architecture Doc Generator):

* One ``ProposedEdit`` per (source file, target doc) pair. It is a fixed-template reason
  line, the changed symbol names (sorted, distinct) and the supporting source file. There
  is no free-text generation and no time or random value, so the same input always gives
  the same output (D20, NFR-04).
* A source file with no symbol names (for example a non-``.py`` file, D17), or with no
  evidence record at all, has insufficient evidence: a ``NotFoundItem`` listing the file
  and the target, and no edit (AC-03, E9).
* Conflicting evidence (implementer rule): when two different source files that map to
  the same target both report the same changed symbol name, or one path has several
  evidence records with different symbol sets, the intended behavior cannot be
  determined. One ``NotFoundItem`` lists all the files involved and none of them gets an
  edit.
* Ambiguous, unmapped and skipped changes (``candidate`` is None) get neither an edit nor
  an item here; the mapping stage and target resolution already report them.
* The output never carries file contents, so an edit cannot touch unrelated lines (NFR-05).

Evidence records are duck-typed (``path`` and ``symbol_names`` attributes) because stages
may not import each other. Paths are unredacted structured fields; output stages redact.
"""

from dataclasses import dataclass

from docsync.contracts import MappingResult, NotFoundItem, ProposedEdit

__all__ = ["GenerationOutcome", "generate", "REASON_TEMPLATE"]

REASON_TEMPLATE = "Source change in %s: update %s for the changed symbols"


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    """Sorted generation output. ``edits`` by (target, source); ``not_found`` by subject."""

    edits: tuple = ()
    not_found: tuple = ()

    @property
    def has_edits(self):
        return bool(self.edits)


def _evidence_by_path(evidence):
    if isinstance(evidence, (str, bytes)):
        raise TypeError("evidence must be a sequence of evidence records")
    grouped = {}
    for record in tuple(evidence):
        path = getattr(record, "path", None)
        names = getattr(record, "symbol_names", None)
        if not isinstance(path, str) or names is None or isinstance(names, (str, bytes)):
            raise TypeError("evidence records need a path and a sequence of symbol_names")
        names = tuple(names)
        if not all(isinstance(n, str) for n in names):
            raise TypeError("symbol_names must contain only strings")
        grouped.setdefault(path, []).append(frozenset(n for n in names if n.strip()))
    return grouped


def generate(evidence, mapping_results, target=None):
    """Return a ``GenerationOutcome`` for the (source, target) pairs in ``mapping_results``.

    ``evidence`` are the Change Analyzer's per-file records; ``mapping_results`` are
    ``MappingResult`` values. If ``target`` is given only pairs mapped to it are in scope.
    """
    by_path = _evidence_by_path(evidence)
    if isinstance(mapping_results, (str, bytes)):
        raise TypeError("mapping_results must be a sequence of MappingResult")
    results = tuple(mapping_results)
    if not all(isinstance(r, MappingResult) for r in results):
        raise TypeError("mapping_results must contain only MappingResult")

    pairs = sorted({(r.candidate, r.source_path) for r in results
                    if r.candidate is not None and (target is None or r.candidate == target)})
    edits, items = [], []

    for doc in sorted({t for t, _ in pairs}):
        sources = [s for t, s in pairs if t == doc]
        handled = set()
        symbols = {}
        for source in sources:
            records = by_path.get(source, [])
            if len(set(records)) > 1:
                items.append(NotFoundItem(
                    "conflicting evidence for %s" % source,
                    "several evidence records disagree on the changed symbols; "
                    "target %s" % doc, (source,)))
                handled.add(source)
                continue
            symbols[source] = records[0] if records else frozenset()
        owners = {}
        for source in sorted(symbols):
            for name in symbols[source]:
                owners.setdefault(name, []).append(source)
        conflicted = sorted({s for group in owners.values() if len(group) > 1 for s in group})
        if conflicted:
            names = sorted(n for n, g in owners.items() if len(g) > 1)
            items.append(NotFoundItem(
                "conflicting evidence for %s" % doc,
                "source files report the same changed symbol name (%s); the intended "
                "behavior cannot be determined" % ", ".join(names), tuple(conflicted)))
            handled.update(conflicted)
        for source in sorted(symbols):
            if source in handled:
                continue
            if not symbols[source]:
                items.append(NotFoundItem(
                    "insufficient evidence for %s" % source,
                    "no changed symbol names could be extracted; target %s needs "
                    "clarification" % doc, (source,)))
                continue
            edits.append(ProposedEdit(
                target=doc, reason=REASON_TEMPLATE % (source, doc),
                supporting_sources=(source,), symbol_names=tuple(sorted(symbols[source]))))
    items.sort(key=lambda i: (i.subject, i.files))
    return GenerationOutcome(edits=tuple(edits), not_found=tuple(items))
