"""Reporter stage. Pure report rendering and separate emission (plan task T14).

Public API:
    render_report(result, *, redactor) -> str   pure: no file, console, network, clock
    fallback_report(outcome_class) -> str       fixed "Run stopped: <outcome class>", no data
    emit_report(text) -> None                   write to standard output and flush; errors propagate

The report input type is defined here (``ReportInput`` and its parts), as plain frozen data. It is
not part of ``docsync.contracts``. This module imports only the standard library and
``docsync.contracts``; the Redactor is passed in as ``redactor=`` (an object with ``redact`` and
``contains_secret``).

Outcome class: the NAME of the ``ExitCode`` member (a string such as ``"OVER_CAP"``). The failure
report names it with its designated exit code (architecture Section 6a). ``fallback_report`` accepts an
``ExitCode`` member or its name, for a stop outcome only (not ``OK``); anything else gives the fixed
text "Run stopped: unknown outcome" and the argument is never echoed.

Redaction (impl-log T14). Every name, path and short message from the caller goes through
``_safe``: control characters become "?", then a text flagged by ``redactor.contains_secret`` is
replaced WHOLE by a fixed placeholder (``[REDACTED-NAME]`` or ``[REDACTED-MESSAGE]``); any other text
passes through ``redactor.redact``. The Reporter never receives or prints document text, hunk text,
diff text, evidence text or symbol bodies. A withheld hunk is shown as file and line only. This
depends on the injected Redactor: with a no-op Redactor nothing is masked. The Redactor has known
gaps (for example file names are not scanned for every format), so a secret that matches no pattern
is not detected.

Free-text cap and the contract for T15. Free-text fields (``message``, ``stage``,
``NotFoundItem.detail``, ``SkippedFile.reason``) are limited to 200 characters in total: longer text is
cut and ends with "...[truncated]". The cap is applied BEFORE the redaction check (so the Redactor
never scans more than the cap) and again to the final text. T15 may supply ONLY counts, file or symbol
names, and fixed short phrases in these fields; NEVER document text, hunk text, diff text, evidence
text or exception text. The Redactor is a best-effort safeguard only, not a guarantee, and a secret
cut by the cap may not match a pattern.

A success report (``ExitCode.OK``) is rejected (ValueError) unless ``validation`` is present and
``validation.passed`` is True.

Not Found rule: a Not Found item whose detail already starts with "Not Found:" is shown as it is;
"Not Found: " is added only to a detail that lacks it. Items with subject
``relative_links_limitation`` (T12) are shown under Limitations, never as passing.

Resolved destination. The caller supplies ``patch_path`` (the resolved destination) and
``default_patch_path`` (the default <cwd>/output/docsync.patch) as plain strings. The report states
the resolved destination whenever both are given and differ, and on the success path states the
planned patch path. This module does not compute or guess a destination. HOW T15 obtains the resolved
destination before publish is NOT solved by T14: the T13 public API has no accessor and a stage may
not import another stage. That must be settled for T15.
"""

import sys
from dataclasses import dataclass

from docsync.contracts import (
    CHECK_RELATIVE_LINKS,
    CheckStatus,
    ExitCode,
    NotFoundItem,
    ProposedEdit,
    ValidationReport,
)

__all__ = [
    "ReportInput",
    "WithheldFinding",
    "SkippedFile",
    "CandidateGroup",
    "NotAddressed",
    "LIMITATIONS",
    "NAME_PLACEHOLDER",
    "MESSAGE_PLACEHOLDER",
    "render_report",
    "fallback_report",
    "emit_report",
]

NAME_PLACEHOLDER = "[REDACTED-NAME]"
MESSAGE_PLACEHOLDER = "[REDACTED-MESSAGE]"
LIMITATION_SUBJECT = "relative_links_limitation"
RELATIVE_LINKS_PASS_RULE = "added-inline-relative-links"
NOT_FOUND_PREFIX = "Not Found:"
MAX_FREE_TEXT = 200
TRUNCATION_MARKER = "...[truncated]"

# Always shown, on every report (requirements 6b.13 and 6b.9, architecture 2.4 and 2.5).
LIMITATIONS = (
    "External URLs are not checked (D9).",
    "No dependency or security scanner is run (D9).",
    "Untracked files are not analyzed (D21).",
    "Reference-style links, autolinks, anchor targets, and links on lines the edit does not add"
    " are outside the check (D27).",
    "Consistency is not computed (D28).",
)

_OUTCOME_TEXT = {
    ExitCode.OK: "Patch written",
    ExitCode.USAGE: "Usage error or invalid --target",
    ExitCode.INPUT_OR_GIT: "Input or Git error",
    ExitCode.NO_CHANGES: "No changes",
    ExitCode.OVER_CAP: "Diff over the cap",
    ExitCode.UNSUPPORTED_ENTRY: "Unsupported entry",
    ExitCode.NO_SUITABLE_TARGET: "No suitable documentation target",
    ExitCode.UNRESOLVED_CANDIDATES: "Unresolved candidates",
    ExitCode.VALIDATION_FAILED: "Validation failed, a mandatory check not performed, or empty output",
    ExitCode.WITHHELD_HUNK: "Secret-like hunk withheld",
    ExitCode.PATCH_WRITE: "Existing patch or patch write failure",
    ExitCode.UNEXPECTED: "Other stage failure",
}
_STOP_CLASSES = {code.name: code for code in ExitCode if code is not ExitCode.OK}


# ------------------------------------------------------------------ validation helpers
def _text(name, value, *, optional=False):
    if value is None and optional:
        return value
    if not isinstance(value, str):
        raise TypeError("%s must be a string" % name)
    if not value.strip():
        raise ValueError("%s must not be empty" % name)
    return value


def _typed_tuple(name, value, kind):
    if isinstance(value, (str, bytes)):
        raise TypeError("%s must be a sequence, not a single string" % name)
    items = tuple(value)
    for item in items:
        if not isinstance(item, kind):
            raise TypeError("%s must contain only %s" % (name, kind.__name__))
    return items


def _str_items(name, value):
    items = _typed_tuple(name, value, str)
    for item in items:
        _text(name, item)
    return items


# ------------------------------------------------------------------------ input types
@dataclass(frozen=True, slots=True)
class WithheldFinding:
    """A withheld hunk: file and 1-based line only, never a value."""

    file: str
    line: int

    def __post_init__(self):
        _text("file", self.file)
        if isinstance(self.line, bool) or not isinstance(self.line, int) or self.line < 1:
            raise ValueError("line must be a positive integer")


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """A file not analyzed, with a short reason (generated, documentation, test, deleted, untracked)."""

    path: str
    reason: str

    def __post_init__(self):
        _text("path", self.path)
        _text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class CandidateGroup:
    """A candidate documentation file and the changed files mapped to it."""

    doc: str
    files: tuple = ()

    def __post_init__(self):
        _text("doc", self.doc)
        object.__setattr__(self, "files", _str_items("files", self.files))


@dataclass(frozen=True, slots=True)
class NotAddressed:
    """A change that maps to another document and was not addressed in this run."""

    path: str
    doc: str

    def __post_init__(self):
        _text("path", self.path)
        _text("doc", self.doc)


@dataclass(frozen=True, slots=True)
class ReportInput:
    """Everything the report may show. Plain data; no document, hunk or diff text.

    ``outcome`` is the ExitCode of the run (OK for the success report). ``message`` is a short stop
    message (counts and names only). ``patch_path`` and ``default_patch_path`` are caller-supplied
    strings; a success report requires ``patch_path``.
    """

    outcome: ExitCode
    patch_path: str | None = None
    default_patch_path: str | None = None
    message: str | None = None
    stage: str | None = None
    examined: tuple = ()
    edits: tuple = ()
    skipped: tuple = ()
    candidates: tuple = ()
    not_addressed: tuple = ()
    unresolved: tuple = ()
    withheld: tuple = ()
    validation: ValidationReport | None = None
    not_found: tuple = ()

    def __post_init__(self):
        if not isinstance(self.outcome, ExitCode):
            raise TypeError("outcome must be an ExitCode")
        _text("patch_path", self.patch_path, optional=True)
        _text("default_patch_path", self.default_patch_path, optional=True)
        _text("message", self.message, optional=True)
        _text("stage", self.stage, optional=True)
        s = object.__setattr__
        s(self, "examined", _str_items("examined", self.examined))
        s(self, "edits", _typed_tuple("edits", self.edits, ProposedEdit))
        s(self, "skipped", _typed_tuple("skipped", self.skipped, SkippedFile))
        s(self, "candidates", _typed_tuple("candidates", self.candidates, CandidateGroup))
        s(self, "not_addressed", _typed_tuple("not_addressed", self.not_addressed, NotAddressed))
        s(self, "unresolved", _str_items("unresolved", self.unresolved))
        s(self, "withheld", _typed_tuple("withheld", self.withheld, WithheldFinding))
        s(self, "not_found", _typed_tuple("not_found", self.not_found, NotFoundItem))
        if self.validation is not None and not isinstance(self.validation, ValidationReport):
            raise TypeError("validation must be a ValidationReport or None")
        if self.outcome is ExitCode.OK:
            if self.validation is None or self.validation.passed is not True:
                raise ValueError("a success report requires a passed validation")
            if self.patch_path is None:
                raise ValueError("a success report requires patch_path")
            if self.withheld:
                raise ValueError("a success report cannot carry withheld hunks")


# ------------------------------------------------------------------------- redaction
def _check_redactor(redactor):
    for method in ("redact", "contains_secret"):
        if not callable(getattr(redactor, method, None)):
            raise TypeError("redactor must provide redact() and contains_secret()")


def _safe(redactor, text, placeholder=NAME_PLACEHOLDER):
    """Make one name, path or short message safe: no control characters, whole-string placeholder."""
    clean = "".join(ch if ch.isprintable() else "?" for ch in text)
    if redactor.contains_secret(clean):
        return placeholder
    return redactor.redact(clean)


def _cap(text):
    """Limit free text to MAX_FREE_TEXT characters in total; longer text ends with TRUNCATION_MARKER."""
    if len(text) <= MAX_FREE_TEXT:
        return text
    return text[: MAX_FREE_TEXT - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def _free(redactor, text, placeholder=MESSAGE_PLACEHOLDER):
    """Caller free text: cap BEFORE the redaction check, and cap the final output again."""
    return _cap(_safe(redactor, _cap(text), placeholder))


def _prefixed(detail):
    return detail if detail.startswith(NOT_FOUND_PREFIX) else "%s %s" % (NOT_FOUND_PREFIX, detail)


def _files_suffix(r, files):
    if not files:
        return ""
    return " (files: %s)" % ", ".join(sorted(_safe(r, f) for f in files))


# --------------------------------------------------------------------------- sections
def _section(title, lines):
    if not lines:
        return []
    return ["%s (%d):" % (title, len(lines))] + ["  " + line for line in sorted(lines)]


def _validation_lines(r, validation):
    out = []
    for res in validation.results:
        where = ""
        if res.file is not None:
            where = " " + _safe(r, res.file)
            if res.status is CheckStatus.FAILED and res.line is not None:
                where += " line %d" % res.line  # NOT_CHECKED: file and rule only (OQ-3)
        rule = " rule %s" % _safe(r, res.rule) if res.rule is not None else ""
        check = _safe(r, res.check)
        if res.status is CheckStatus.PASSED and res.check == CHECK_RELATIVE_LINKS:
            # Scoped: only the added inline relative links; never a plain "links passed".
            scope = RELATIVE_LINKS_PASS_RULE if res.rule in (None, RELATIVE_LINKS_PASS_RULE) else _safe(r, res.rule)
            out.append(
                "PASSED %s%s: no broken inline relative link on the added lines"
                " (scope: rule %s; other link kinds are under Limitations)" % (check, where, scope)
            )
        elif res.status is CheckStatus.PASSED:
            out.append("PASSED %s%s%s" % (check, where, rule))
        elif res.status is CheckStatus.FAILED:
            out.append("FAILED %s%s%s" % (check, where, rule))
        else:
            out.append("NOT CHECKED %s%s%s" % (check, where, rule))
    return out


def render_report(result, *, redactor):
    """Render the success report or a failure report for a stopped run. Pure: no I/O."""
    if not isinstance(result, ReportInput):
        raise TypeError("result must be a ReportInput")
    _check_redactor(redactor)
    r = redactor
    ok = result.outcome is ExitCode.OK
    lines = ["DOCSYNC report"]
    lines.append("Outcome: %s (exit %d): %s" % (result.outcome.name, int(result.outcome), _OUTCOME_TEXT[result.outcome]))
    if not ok:
        lines.append("Run stopped: no patch was written.")
    if result.stage is not None:
        lines.append("Stage: %s" % _free(r, result.stage))
    if result.message is not None:
        lines.append("Detail: %s" % _free(r, result.message))

    if result.patch_path is not None:
        differs = result.default_patch_path is not None and result.patch_path != result.default_patch_path
        resolved = _safe(r, result.patch_path)
        if ok:
            lines.append("Planned patch: %s" % resolved)
        elif differs:
            lines.append("Resolved patch destination: %s" % resolved)
        if differs:
            lines.append("Resolved destination differs from the default: %s" % _safe(r, result.default_patch_path))
    elif ok:  # unreachable (validated), kept explicit
        lines.append("Planned patch: Not Found")

    lines += _section("Files examined", [_safe(r, p) for p in result.examined])

    proposed = []
    for edit in result.edits:
        entry = _safe(r, edit.target)
        if edit.supporting_sources:
            entry += "; sources: " + ", ".join(sorted(_safe(r, s) for s in edit.supporting_sources))
        if edit.symbol_names:
            entry += "; symbols: " + ", ".join(sorted(_safe(r, s) for s in edit.symbol_names))
        proposed.append(entry)
    lines += _section("Files proposed", proposed)
    lines += _section("Files skipped", ["%s: %s" % (_safe(r, s.path), _free(r, s.reason)) for s in result.skipped])
    lines += _section(
        "Candidates",
        ["%s <- %s" % (_safe(r, c.doc), ", ".join(sorted(_safe(r, f) for f in c.files)) or "Not Found") for c in result.candidates],
    )
    lines += _section("Not addressed in this run", ["%s -> %s" % (_safe(r, n.path), _safe(r, n.doc)) for n in result.not_addressed])
    lines += _section("Unresolved changes (no candidate)", [_safe(r, p) for p in result.unresolved])
    lines += _section("Withheld hunks (file and line only)", ["%s line %d" % (_safe(r, w.file), w.line) for w in result.withheld])

    items = list(result.not_found)
    if result.validation is not None:
        items += list(result.validation.not_found)
    if result.validation is None:
        lines.append("Validation: not run")
    else:
        lines.append("Validation: %s" % ("passed" if result.validation.passed else "not passed"))
        lines += ["  " + x for x in sorted(_validation_lines(r, result.validation))]

    def item_line(item):
        return _cap(_prefixed(_free(r, item.detail))) + _files_suffix(r, item.files)

    found = [item_line(i) for i in items if i.subject != LIMITATION_SUBJECT]
    limits = [item_line(i) for i in items if i.subject == LIMITATION_SUBJECT]
    lines += _section("Not Found", found)

    lines.append("Limitations (not checked, outside v1 scope):")
    lines += ["  - " + text for text in LIMITATIONS]
    lines += ["  - " + text for text in sorted(limits)]
    return "\n".join(lines) + "\n"


def fallback_report(outcome_class):
    """Fixed one-line message with the outcome class only; never echoes an unknown argument."""
    name = None
    if isinstance(outcome_class, ExitCode):
        name = outcome_class.name if outcome_class in _STOP_CLASSES.values() else None
    elif isinstance(outcome_class, str) and outcome_class in _STOP_CLASSES:
        name = outcome_class
    return "Run stopped: %s\n" % (name if name is not None else "unknown outcome")


def emit_report(text):
    """Write the text to standard output and flush. Any error propagates (not swallowed)."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    stream = sys.stdout
    stream.write(text)
    stream.flush()
