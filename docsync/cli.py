"""CLI / Orchestrator stage. Parses arguments, resolves the run's scope, maps outcomes to exit codes.

Implemented in plan tasks T09 (argument handling and ``--target``) and T15 (``main()``:
sequencing, all-or-nothing, exit codes; see the "T15" section at the end of this module).
This module holds no analysis, mapping, generation, or validation logic. The T09 functions
take the mapping outcome from the caller (duck-typed: ``results``, ``candidates``,
``ambiguous``, ``unmapped``). It is the orchestrating module, so it is the only module that
imports the other stages (public names only); ``main()`` wires them together.

T09 rules (architecture Sections 2.3 and 6a, D4, D11, D24, D25, D30):

* Arguments: an optional repository path and ``--target <path>`` (or ``--target=<path>``).
  Any other option (``--force`` included) is a usage error, exit 2. Nothing reads stdin and
  nothing prompts.
* Resolution order in ``resolve_scope``:
  1. Any ambiguous change (several docs share its stem): exit 8, with or without ``--target``.
     This is checked before "no candidates", so an all-ambiguous run is exit 8, never 7.
  2. No change has a candidate: exit 7, with or without ``--target``.
  3. A given ``--target`` is validated (relative, no ``..``, Markdown, one of the run's
     candidates, resolves inside the repository with no link redirection): invalid is exit 2.
  4. Without ``--target``: proceed only if every analyzed change maps to one single doc,
     otherwise list the candidates and exit 8.
  5. With ``--target``: changes mapped to it are in scope, changes mapped to another doc are
     "not addressed in this run", a change with no candidate is unresolved (exit 8).
* The tool never selects a target.
* User-derived text (the target string, option text, paths) passes through the injected
  redactor and is escaped to ASCII before it enters a message.
"""

import os
import sys
from dataclasses import dataclass

from docsync import (
    analysis,
    generation,
    gitadapter,
    mapping,
    output,
    proposal,
    redact,
    report,
    sizegate,
    validation,
)
from docsync import input as input_stage
from docsync.contracts import (
    ExitCode,
    NoChangesError,
    NoSuitableTargetError,
    StageError,
    UnresolvedCandidatesError,
    UsageError,
    ValidationFailedError,
)

__all__ = [
    "ParsedArgs",
    "Scope",
    "parse_args",
    "parse_or_code",
    "validate_target",
    "resolve_scope",
    "exit_code_for",
    "NO_SUITABLE_TARGET_MESSAGE",
    "main",
]

_STAGE = "cli"
NO_SUITABLE_TARGET_MESSAGE = "no suitable documentation target"
README = "README.md"
DOCS_PREFIX = "docs/"
_SHOW_LIMIT = 120


@dataclass(frozen=True, slots=True)
class ParsedArgs:
    repo_path: str | None = None  # None means the current directory (OQ-1)
    target: str | None = None


@dataclass(frozen=True, slots=True)
class Scope:
    """The run's scope. Every analyzed source change is in exactly one of three groups."""

    target: str | None
    in_scope: tuple = ()        # source paths processed in this run
    not_addressed: tuple = ()   # (source path, doc it maps to), only with --target
    skipped: tuple = ()         # MappingResult entries skipped by the mapper (docs, tests, ...)


# ---------------------------------------------------------------------------- helpers
def _check_redactor(redactor):
    if not callable(redactor):
        raise TypeError("redactor must be callable")


def _show(redactor, text):
    """Redact, then escape to ASCII and bound the length, for use inside a message."""
    shown = ascii(redactor(str(text)))
    if len(shown) > _SHOW_LIMIT:
        shown = shown[:_SHOW_LIMIT] + "...'"
    return shown


def _usage(redactor, message):
    # Callers pass user-derived parts through _show() already; the fixed text is not redacted
    # as a whole, because a masking pattern could swallow the explanation next to a value.
    return UsageError(_STAGE, message)


# ------------------------------------------------------------------------- arguments
def parse_args(argv, *, redactor):
    """Parse ``argv`` (without the program name). Raises ``UsageError`` (exit 2).

    Accepts at most one positional repository path and one ``--target``. An argument that
    starts with ``-`` and is not ``--target`` is an unknown option. ``--`` ends options.
    Never reads stdin, never prompts.
    """
    _check_redactor(redactor)
    if isinstance(argv, (str, bytes)):
        raise TypeError("argv must be a sequence of strings")
    items = list(argv)
    repo_path = None
    target = None
    have_target = False
    options_done = False
    i = 0
    while i < len(items):
        arg = items[i]
        if not isinstance(arg, str):
            raise TypeError("argv must contain only strings")
        i += 1
        if not options_done and arg == "--":
            options_done = True
            continue
        if not options_done and arg.startswith("-") and arg != "-":
            if arg == "--target" or arg.startswith("--target="):
                if have_target:
                    raise _usage(redactor, "--target given more than once")
                if arg == "--target":
                    if i >= len(items) or not isinstance(items[i], str):
                        raise _usage(redactor, "--target needs a path")
                    value = items[i]
                    i += 1
                else:
                    value = arg[len("--target="):]
                if not value.strip():
                    raise _usage(redactor, "--target needs a non-empty path")
                have_target = True
                target = value
                continue
            raise _usage(redactor, "unknown option: %s (only a repository path and --target are accepted)"
                         % _show(redactor, arg))
        if repo_path is not None:
            raise _usage(redactor, "more than one repository path given")
        if not arg.strip():
            raise _usage(redactor, "the repository path is empty")
        repo_path = arg
    return ParsedArgs(repo_path=repo_path, target=target)


def parse_or_code(argv, *, redactor):
    """Return ``(args, 0, "")`` or ``(None, exit_code, message)`` for a usage error."""
    try:
        return parse_args(argv, redactor=redactor), 0, ""
    except UsageError as exc:
        return None, int(exc.exit_code), str(exc)


# ---------------------------------------------------------------------------- target
def _valid_list(candidates):
    return ", ".join(candidates) if candidates else "none"  # callers pass shown text


def _invalid_target(redactor, target, reason, candidates):
    return _usage(
        redactor,
        "invalid --target %s: %s. Valid candidates: %s"
        % (_show(redactor, target), reason,
           _valid_list([_show(redactor, c) for c in candidates])),
    )


def _is_absolute_like(text):
    if text.startswith(("/", "\\")):
        return True
    return len(text) >= 2 and text[1] == ":" and text[0].isalpha()


def validate_target(target, repo_root, candidates, *, redactor):
    """Validate ``--target`` and return the candidate string it names, or raise ``UsageError``.

    Rejects (exit 2): empty or NUL text, absolute paths (POSIX, drive, UNC), any ``..``
    segment, a path that is not ``README.md`` or Markdown directly under ``docs/``, a path
    that is not one of the run's candidates, and a path whose real location (symlinks and
    Windows junctions resolved) is not exactly ``<repository real path>/<target>``, which
    also covers every escape from the repository. Nothing is opened.
    """
    _check_redactor(redactor)
    candidates = tuple(sorted(set(candidates)))
    if not isinstance(target, str) or not target.strip():
        raise _invalid_target(redactor, "", "the target is empty", candidates)
    if "\x00" in target:
        raise _invalid_target(redactor, target.replace("\x00", "?"), "the target contains a null character", candidates)
    if _is_absolute_like(target):
        raise _invalid_target(redactor, target, "absolute paths are not allowed", candidates)
    normalized = target.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise _invalid_target(redactor, target, "'..' segments are not allowed", candidates)
    if not (normalized == README or (normalized.startswith(DOCS_PREFIX) and normalized.endswith(".md"))):
        raise _invalid_target(redactor, target, "not README.md or a Markdown file under docs/", candidates)
    if normalized not in candidates:
        raise _invalid_target(redactor, target, "not a documentation candidate of this run", candidates)

    try:
        real_root = os.path.realpath(str(repo_root))
        real_target = os.path.realpath(os.path.join(real_root, *normalized.split("/")))
        expected = os.path.join(real_root, *normalized.split("/"))
        same_place = os.path.normcase(real_target) == os.path.normcase(expected)
        inside = os.path.commonpath([os.path.normcase(real_root), os.path.normcase(real_target)]) \
            == os.path.normcase(real_root)
        is_file = os.path.isfile(real_target)
    except (OSError, ValueError):
        raise _invalid_target(redactor, target, "the target could not be resolved", candidates) from None
    if not inside:
        raise _invalid_target(redactor, target, "resolves outside the repository", candidates)
    if not same_place:
        raise _invalid_target(redactor, target, "resolves through a link", candidates)
    if not is_file:
        raise _invalid_target(redactor, target, "is not an existing file", candidates)
    return normalized


# ----------------------------------------------------------------------------- scope
def _mapped_groups(outcome):
    """Return {doc: [source paths]} for analyzed changes that have a candidate."""
    groups = {}
    for result in outcome.results:
        if result.candidate is not None:
            groups.setdefault(result.candidate, []).append(result.source_path)
    return groups


def _ambiguity_error(outcome, redactor):
    lines = ["multiple matching documentation files; nothing was chosen and no patch is written:"]
    for path, docs in outcome.ambiguous:
        lines.append("  %s matches: %s" % (_show(redactor, path), ", ".join(_show(redactor, d) for d in docs)))
    return UnresolvedCandidatesError(_STAGE, "\n".join(lines))


def _unresolved_error(outcome, redactor, headline, extra=()):
    lines = [headline]
    groups = _mapped_groups(outcome)
    for doc in sorted(groups):
        lines.append("  candidate %s: %s" % (_show(redactor, doc), ", ".join(_show(redactor, p) for p in groups[doc])))
    for path in outcome.unmapped:
        lines.append("  no candidate: %s" % _show(redactor, path))
    lines.extend(extra)
    return UnresolvedCandidatesError(_STAGE, "\n".join(lines))


def resolve_scope(outcome, repo_root, target=None, *, redactor):
    """Decide the run's scope from a mapping outcome. Returns a ``Scope`` or raises.

    Raises ``UnresolvedCandidatesError`` (exit 8), ``NoSuitableTargetError`` (exit 7) or
    ``UsageError`` (exit 2, invalid target). Never selects a target; ``target`` is only
    validated and applied.
    """
    _check_redactor(redactor)
    # 1. Ambiguity first: an all-ambiguous run is exit 8, not 7 (E7), with or without --target.
    if outcome.has_ambiguity:
        raise _ambiguity_error(outcome, redactor)
    # 2. No candidate at all: exit 7, with or without --target.
    if not outcome.has_candidates:
        raise NoSuitableTargetError(_STAGE, NO_SUITABLE_TARGET_MESSAGE)

    skipped = tuple(r for r in outcome.results if r.skipped_reason is not None)
    groups = _mapped_groups(outcome)

    if target is None:
        if outcome.unmapped or len(groups) != 1:
            raise _unresolved_error(
                outcome, redactor,
                "several documentation candidates or unmapped changes; no patch is written. "
                "Re-run with --target <path> to choose one:")
        (doc, paths), = groups.items()
        return Scope(target=None, in_scope=tuple(sorted(paths)), skipped=skipped)

    chosen = validate_target(target, repo_root, outcome.candidates, redactor=redactor)
    if outcome.unmapped:
        raise _unresolved_error(
            outcome, redactor,
            "changes with no documentation candidate are unresolved; no patch is written:")
    in_scope = tuple(sorted(groups.get(chosen, ())))
    not_addressed = tuple(sorted((p, doc) for doc, paths in groups.items() if doc != chosen for p in paths))
    return Scope(target=chosen, in_scope=in_scope, not_addressed=not_addressed, skipped=skipped)


# ------------------------------------------------------------------------- exit code
def exit_code_for(error):
    """Map a stage error (or any exception) to its designated exit code (architecture 6a).

    A typed ``StageError`` keeps its own code; anything else is an unexpected failure (12).
    """
    if isinstance(error, StageError):
        return int(error.exit_code)
    return int(ExitCode.UNEXPECTED)


# ======================================================================================
# T15 Orchestrator: main(). Sequencing, all-or-nothing, exit codes (architecture 6a, D1, D24).
#
# Order: arguments; existing-patch pre-check (before any Git call, D29); input; Git
# (root check, preflight, diff); size gate; analysis; mapping; scope and target; generate;
# T10b proposals (working_tree_reader injected); DocumentChange; render_patch (redact and
# withhold); validate the COMPLETE proposed text with added_lines (D31); approve_patch;
# render the success report; publish_patch; re-render only if token.path differs; emit.
#
# Every expected outcome is a typed error and keeps its designated code. Exit 12 is only for
# unexpected failures and, on the success path only, a report failure (the patch is then
# rolled back). Exception text is never put in a report: the capped free-text fields get
# fixed phrases, stage names and counts only. The CLI exposes no ``environment=`` and no
# ``executable=`` of the Git Adapter.
# ======================================================================================
_PHRASES = {
    ExitCode.USAGE: "usage error or invalid --target",
    ExitCode.INPUT_OR_GIT: "input or Git step failed",
    ExitCode.NO_CHANGES: "no changes to document",
    ExitCode.OVER_CAP: "diff over the cap",
    ExitCode.UNSUPPORTED_ENTRY: "unsupported entry in the diff",
    ExitCode.NO_SUITABLE_TARGET: "no suitable documentation target",
    ExitCode.UNRESOLVED_CANDIDATES: "unresolved candidates or changes",
    ExitCode.VALIDATION_FAILED: "validation failed or output empty",
    ExitCode.WITHHELD_HUNK: "secret-like hunk withheld",
    ExitCode.PATCH_WRITE: "patch not written",
    ExitCode.UNEXPECTED: "unexpected failure",
}
# Fixed phrases for the typed Git Adapter errors (checked in this order).
_GIT_PHRASES = (
    (gitadapter.ContentFilterError, "a content filter is defined"),
    (gitadapter.PreflightUnverifiedError, "content-filter protection could not be verified"),
    (gitadapter.NoHeadError, "repository has no HEAD commit"),
    (gitadapter.NotRepositoryRootError, "path is not the repository root"),
    (gitadapter.NotARepositoryError, "path is not a Git repository"),
    (gitadapter.GitMissingError, "git executable not available"),
    (gitadapter.GitTimeoutError, "git timed out"),
)
_UNTRACKED_LIMIT = 20
_DESTINATION = "%s/%s" % (output.OUTPUT_DIR, output.PATCH_NAME)


class _Unexpected(Exception):
    """Internal marker: stop with exit 12 (no exception text is ever shown)."""


class _Run:
    """What the run has learned so far. Names, counts and structured data only."""

    def __init__(self):
        self.stage = None
        self.completed = []
        self.examined = ()
        self.untracked = ()
        self.analysis_skipped = ()
        self.proposal_skipped = ()
        self.unsupported = ()
        self.candidates = ()
        self.not_addressed = ()
        self.unresolved = ()
        self.withheld = ()
        self.validation = None
        self.not_found = ()
        self.edits = ()

    def enter(self, name):
        if self.stage is not None:
            self.completed.append(self.stage)
        self.stage = name


def _note(text):
    """Best-effort note on standard error; a closed stream hides it."""
    try:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _code_of(exc):
    if isinstance(exc, StageError):
        try:
            code = ExitCode(int(exc.exit_code))
        except (TypeError, ValueError):
            return ExitCode.UNEXPECTED
        return ExitCode.UNEXPECTED if code is ExitCode.OK else code
    return ExitCode.UNEXPECTED


def _detail(run, exc, code):
    """A fixed phrase or counts for the error, never its message."""
    if code is ExitCode.PATCH_WRITE:
        if run.stage == "precheck":
            return "destination %s exists or is refused" % _DESTINATION
        return "destination %s refused or write failed" % _DESTINATION
    if isinstance(exc, sizegate.SizeGateOverCapError):
        if isinstance(exc.file_count, int) and isinstance(exc.line_count, int):
            return "%d files, %d changed lines" % (exc.file_count, exc.line_count)
        return None
    if isinstance(exc, sizegate.SizeGateUnsupportedEntryError):
        return "%d unsupported entries" % len(exc.entries)
    if isinstance(exc, output.WithheldHunksError):
        return "%d finding(s), file and line only" % len(exc.findings)
    if isinstance(exc, gitadapter.GitAdapterError):
        for kind, phrase in _GIT_PHRASES:
            if isinstance(exc, kind):
                return phrase
        return "a git step failed"
    if code is ExitCode.UNEXPECTED:
        return "no details shown"
    return None


def _report_input(run, outcome, **extra):
    skipped = [report.SkippedFile(p, "untracked file, not analyzed") for p in run.untracked[:_UNTRACKED_LIMIT]]
    if len(run.untracked) > _UNTRACKED_LIMIT:
        skipped.append(report.SkippedFile(
            "(untracked files)", "%d more not listed" % (len(run.untracked) - _UNTRACKED_LIMIT)))
    skipped += list(run.analysis_skipped) + list(run.unsupported) + list(run.proposal_skipped)
    return report.ReportInput(
        outcome=outcome, examined=run.examined, edits=run.edits, skipped=tuple(skipped),
        candidates=run.candidates, not_addressed=run.not_addressed, unresolved=run.unresolved,
        withheld=run.withheld, validation=run.validation, not_found=run.not_found, **extra)


def _failure_input(run, exc, code):
    if isinstance(exc, sizegate.SizeGateUnsupportedEntryError):
        run.unsupported = tuple(report.SkippedFile(p, "unsupported entry: %s" % k) for p, k in exc.entries)
    if isinstance(exc, output.WithheldHunksError):
        run.withheld = tuple(report.WithheldFinding(f.file, f.line) for f in exc.findings)
    parts = [_PHRASES[code]]
    detail = _detail(run, exc, code)
    if detail:
        parts.append(detail)
    parts.append("completed: %s" % (", ".join(run.completed) or "none"))
    return _report_input(run, code, stage=run.stage or "cli", message="; ".join(parts))


def _emit(text, fallback_code):
    """Emit ``text``. True if written. A UnicodeEncodeError prints the fixed fallback line
    instead (best effort); any other error leaves a note on standard error."""
    try:
        report.emit_report(text)
        return True
    except UnicodeEncodeError:
        try:
            # Nothing was written (the stream encodes the whole text first). Retry once
            # with the already rendered and redacted text, its characters the stream cannot
            # encode escaped (\uXXXX); this can only hide characters, never reveal more.
            encoding = getattr(sys.stdout, "encoding", None)
            if encoding:
                report.emit_report(text.encode(encoding, "backslashreplace").decode(encoding))
                return True
        except Exception:
            pass
        try:
            report.emit_report(report.fallback_report(fallback_code))
        except Exception:
            _note("the report could not be written to standard output")
        return False
    except Exception:
        _note("the report could not be written to standard output")
        return False


def _stop(run, exc):
    """Stop path: the designated code stands whatever happens to the report."""
    code = _code_of(exc)
    try:
        text = report.render_report(_failure_input(run, exc, code), redactor=redact)
    except Exception:
        text = report.fallback_report(code)
    _emit(text, code)
    return int(code)


def _rollback(token):
    """Delete the patch this run created. True if the all-or-nothing outcome holds."""
    try:
        output.rollback_patch(token)
        return True
    except Exception:
        try:
            shown = ascii(redact.redact(str(getattr(token, "path", "Not Found"))))
        except Exception:
            shown = "'Not Found'"
        _note("all-or-nothing outcome NOT achieved: the patch may remain at %s" % shown)
        return False


_NOT_ACHIEVED_LINE = (
    "Run stopped: UNEXPECTED. All-or-nothing outcome NOT achieved: a patch may remain at %s/%s."
    % (output.OUTPUT_DIR, output.PATCH_NAME))  # constant text, no data from the run


def _groups(outcome):
    groups = {}
    for result in outcome.results:
        if result.candidate is not None:
            groups.setdefault(result.candidate, []).append(result.source_path)
    for path, docs in outcome.ambiguous:
        for doc in docs:
            groups.setdefault(doc, []).append(path)
    return tuple(report.CandidateGroup(doc, tuple(sorted(paths))) for doc, paths in sorted(groups.items()))


class _Ready:
    """Steps 1 to 3 passed: the approved patch and a pure renderer for the success report."""

    def __init__(self, approved, default_path, render):
        self.approved = approved
        self.default_path = default_path
        self.render = render


def _prepare(argv, run):
    """Steps 1 to 3. Raises a typed error (stop path) or anything else (unexpected)."""
    run.enter("cli")
    args = parse_args(sys.argv[1:] if argv is None else argv, redactor=redact.redact)

    run.enter("precheck")
    output.check_no_existing_patch()  # before any Git call (D29)

    run.enter("input")
    request = input_stage.resolve_input(args.repo_path, args.target, redactor=redact.redact)
    root = os.path.realpath(request.repo_path)

    run.enter("gitadapter")
    adapter = gitadapter.GitAdapter(request.repo_path, redactor=redact.redact)
    def gate(files):
        # Pre-fetch gate (C-4, D12): an over-cap diff stops before its text is fetched.
        run.examined = tuple(f.path for f in files)
        try:
            sizegate.check_size(files, redactor=redact.redact)
        except Exception:
            run.enter("sizegate")  # name the stage in the stop report
            raise

    diff = adapter.retrieve_diff(gate=gate)  # root check, content-filter preflight, diff
    run.examined = tuple(f.path for f in diff.files)
    run.untracked = tuple(diff.untracked)

    run.enter("sizegate")  # the check itself ran inside retrieve_diff (gate), before the diff text

    run.enter("analysis")
    analyzed = analysis.analyze(diff.files, diff.diff_text, redactor=redact.redact,
                                read_text=analysis.working_tree_reader(root))
    run.analysis_skipped = tuple(report.SkippedFile(s.path, s.reason) for s in analyzed.skipped)
    if not analyzed.has_source_files:
        raise NoChangesError("analysis", "every changed file was skipped")

    run.enter("mapping")
    candidates = mapping.discover_candidates(root)
    outcome = mapping.map_changes(analyzed.files, candidates)
    run.candidates = _groups(outcome)
    run.unresolved = tuple(outcome.unmapped)

    run.enter("scope")
    scope = resolve_scope(outcome, root, request.target, redactor=redact.redact)
    run.not_addressed = tuple(report.NotAddressed(p, d) for p, d in scope.not_addressed)
    run.unresolved = ()

    run.enter("generation")
    generated = generation.generate(analyzed.evidence, outcome.results, scope.target)
    run.not_found = tuple(generated.not_found)

    run.enter("proposal")
    if scope.target is not None:  # T09 TOCTOU: re-check the target just before it is read
        validate_target(scope.target, root, outcome.candidates, redactor=redact.redact)
    proposals = proposal.build_proposals(generated.edits, analysis.working_tree_reader(root))
    run.not_found = run.not_found + tuple(proposals.not_found)
    run.proposal_skipped = tuple(
        report.SkippedFile(s.path if s.path is not None else "(invalid target)", s.reason)
        for s in proposals.skipped)
    produced = {d.path for d in proposals.documents}
    run.edits = tuple(e for e in generated.edits if e.target in produced)

    run.enter("redact")
    changes = [output.DocumentChange(d.path, d.original, d.proposed) for d in proposals.documents]
    rendered = output.render_patch(changes, redact)
    output.raise_if_withheld(rendered)  # exit 10; lists file and line only

    run.enter("validation")
    content = {d.path: d.proposed for d in proposals.documents}
    added = {d.path: d.added_lines for d in proposals.documents}
    run.validation = validation.validate_content(content, root, added)
    if not proposals.documents or not run.validation.passed:
        raise ValidationFailedError("validation", "validation did not pass")

    run.enter("approve")
    approved = output.approve_patch(rendered, run.validation, root, (), redact)
    default_path = os.path.join(os.getcwd(), output.OUTPUT_DIR, output.PATCH_NAME)

    def render(patch_path):
        return report.render_report(
            _report_input(run, ExitCode.OK, patch_path=patch_path, default_patch_path=default_path),
            redactor=redact)

    return _Ready(approved, default_path, render)


def _finish(run, ready):
    """Steps 4 to 6 (success path): render, publish, re-render if needed, emit."""
    try:
        run.enter("render")
        text = ready.render(ready.default_path)  # no patch exists yet
    except Exception:
        return _stop(run, _Unexpected())

    run.enter("publish")
    try:
        token = output.publish_patch(ready.approved)
    except Exception as exc:  # publish removed its own partial file
        return _stop(run, exc)

    try:
        if token.path != ready.default_path:
            run.enter("render")
            text = ready.render(token.path)
    except BaseException as exc:
        rolled_back = _rollback(token)
        if not isinstance(exc, Exception):
            raise
        if not rolled_back:  # the ordinary stop report would claim that no patch was written
            _emit(_NOT_ACHIEVED_LINE, ExitCode.UNEXPECTED)
            return int(ExitCode.UNEXPECTED)
        return _stop(run, _Unexpected())

    run.enter("emit")
    try:
        emitted = _emit(text, ExitCode.UNEXPECTED)
    except BaseException:
        _rollback(token)
        raise
    if not emitted:
        _rollback(token)
        return int(ExitCode.UNEXPECTED)
    return int(ExitCode.OK)


def main(argv=None):
    """Run the whole pipeline and return the process exit code (the caller exits with it).

    ``argv`` excludes the program name; None means ``sys.argv[1:]``. Never raises for a
    stage failure: expected outcomes keep their designated code, anything else is 12.
    """
    run = _Run()
    try:
        ready = _prepare(argv, run)
    except Exception as exc:
        return _stop(run, exc)
    return _finish(run, ready)


if __name__ == "__main__":
    sys.exit(main())
