"""Shared, immutable data contracts and typed stage errors (plan task T01).

This module is not a stage. Every stage module may import it, and it imports no
stage module. Contracts hold plain data only: no behavior beyond validation of
their own fields. All sequences are stored as tuples so a frozen instance is
immutable all the way down.

Exit codes follow architecture Section 6a (D24). Every expected outcome keeps its
designated code; ``ExitCode.UNEXPECTED`` (12) is reserved for unexpected failures.
"""

import enum
from dataclasses import dataclass

# The eleven stage modules of the package (plan T01, architecture Section 2).
STAGE_MODULES = (
    "cli",
    "input",
    "gitadapter",
    "sizegate",
    "analysis",
    "mapping",
    "generation",
    "validation",
    "output",
    "report",
    "redact",
)

# Mandatory validation checks (D2, D5, D7). A report passes only if every one of
# them is present and passed.
CHECK_MARKDOWN_SYNTAX = "markdown_syntax"
CHECK_RELATIVE_LINKS = "relative_links"
CHECK_NON_EMPTY_OUTPUT = "non_empty_output"
MANDATORY_CHECKS = (CHECK_MARKDOWN_SYNTAX, CHECK_RELATIVE_LINKS, CHECK_NON_EMPTY_OUTPUT)


class ExitCode(enum.IntEnum):
    """Process exit codes (architecture Section 6a)."""

    OK = 0
    USAGE = 2
    INPUT_OR_GIT = 3
    NO_CHANGES = 4
    OVER_CAP = 5
    UNSUPPORTED_ENTRY = 6
    NO_SUITABLE_TARGET = 7
    UNRESOLVED_CANDIDATES = 8
    VALIDATION_FAILED = 9
    WITHHELD_HUNK = 10
    PATCH_WRITE = 11
    UNEXPECTED = 12


class FileCategory(enum.Enum):
    """Classification of a changed file (architecture Section 2, Change Analyzer)."""

    UNCLASSIFIED = "unclassified"
    SOURCE = "source"
    GENERATED = "generated"
    DOCUMENTATION = "documentation"
    TEST = "test"
    DELETED = "deleted"
    UNSUPPORTED = "unsupported"


class CheckStatus(enum.Enum):
    """Result of one validation check. NOT_CHECKED never counts as passed (D5)."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_CHECKED = "not_checked"


# ---------------------------------------------------------------- field helpers
def _set(obj, name, value):
    object.__setattr__(obj, name, value)


def _require_text(name, value, *, allow_empty=False):
    if not isinstance(value, str):
        raise TypeError("%s must be a string" % name)
    if not allow_empty and not value.strip():
        raise ValueError("%s must not be empty" % name)


def _optional_text(name, value):
    if value is not None:
        _require_text(name, value)


def _str_tuple(name, value):
    if isinstance(value, (str, bytes)):
        raise TypeError("%s must be a sequence of strings, not a single string" % name)
    items = tuple(value)
    for item in items:
        if not isinstance(item, str):
            raise TypeError("%s must contain only strings" % name)
    return items


def _optional_count(name, value):
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("%s must be a non-negative integer or None" % name)


# ------------------------------------------------------------------- contracts
@dataclass(frozen=True, slots=True)
class ChangeRequest:
    """What the user asked for: a repository path and an optional ``--target``."""

    repo_path: str
    target: str | None = None

    def __post_init__(self):
        _require_text("repo_path", self.repo_path)
        _optional_text("target", self.target)


@dataclass(frozen=True, slots=True)
class ChangedFile:
    """One entry of the Git diff. ``added`` and ``deleted`` are None when unknown.

    Unknown line counts are never zero (D23); ``changed_lines`` is then None.
    """

    path: str
    status: str
    added: int | None = None
    deleted: int | None = None
    old_path: str | None = None
    old_mode: str | None = None
    new_mode: str | None = None
    binary: bool = False
    category: FileCategory = FileCategory.UNCLASSIFIED

    def __post_init__(self):
        _require_text("path", self.path)
        _require_text("status", self.status)
        _optional_text("old_path", self.old_path)
        _optional_text("old_mode", self.old_mode)
        _optional_text("new_mode", self.new_mode)
        _optional_count("added", self.added)
        _optional_count("deleted", self.deleted)
        if not isinstance(self.binary, bool):
            raise TypeError("binary must be a bool")
        if not isinstance(self.category, FileCategory):
            raise TypeError("category must be a FileCategory")

    @property
    def changed_lines(self):
        """Added plus deleted lines (D6), or None when either count is unknown."""
        if self.added is None or self.deleted is None:
            return None
        return self.added + self.deleted


@dataclass(frozen=True, slots=True)
class MappingResult:
    """Mapping outcome for one changed source file: at most one candidate (D19).

    ``candidate`` is None when no documentation target exists for the file.
    ``skipped_reason`` is set when the file was not mapped (documentation, test,
    generated). A result never has both a candidate and a skip reason.
    """

    source_path: str
    candidate: str | None = None
    skipped_reason: str | None = None

    def __post_init__(self):
        _require_text("source_path", self.source_path)
        _optional_text("candidate", self.candidate)
        _optional_text("skipped_reason", self.skipped_reason)
        if self.candidate is not None and self.skipped_reason is not None:
            raise ValueError("a mapping result has either a candidate or a skip reason, not both")


@dataclass(frozen=True, slots=True)
class ProposedEdit:
    """A proposed documentation edit: a reason line plus symbol names (D20, NFR-04)."""

    target: str
    reason: str
    supporting_sources: tuple = ()
    symbol_names: tuple = ()

    def __post_init__(self):
        _require_text("target", self.target)
        _require_text("reason", self.reason)
        _set(self, "supporting_sources", _str_tuple("supporting_sources", self.supporting_sources))
        _set(self, "symbol_names", _str_tuple("symbol_names", self.symbol_names))


@dataclass(frozen=True, slots=True)
class NotFoundItem:
    """Something that could not be determined from the evidence (AC-03)."""

    subject: str
    detail: str
    files: tuple = ()

    def __post_init__(self):
        _require_text("subject", self.subject)
        _require_text("detail", self.detail)
        _set(self, "files", _str_tuple("files", self.files))


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One validation result. A result that is not PASSED must name its rule (AC-06)."""

    check: str
    status: CheckStatus
    mandatory: bool = True
    file: str | None = None
    line: int | None = None
    rule: str | None = None

    def __post_init__(self):
        _require_text("check", self.check)
        if not isinstance(self.status, CheckStatus):
            raise TypeError("status must be a CheckStatus")
        if not isinstance(self.mandatory, bool):
            raise TypeError("mandatory must be a bool")
        _optional_text("file", self.file)
        _optional_text("rule", self.rule)
        if self.line is not None and (isinstance(self.line, bool) or not isinstance(self.line, int) or self.line < 1):
            raise ValueError("line must be a positive integer or None")
        if self.status is not CheckStatus.PASSED and self.rule is None:
            raise ValueError("a result that is not passed must name its rule")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """All validation results plus non-blocking Not Found items (for example D28)."""

    results: tuple = ()
    not_found: tuple = ()

    def __post_init__(self):
        results = tuple(self.results)
        if not all(isinstance(r, CheckResult) for r in results):
            raise TypeError("results must contain only CheckResult")
        not_found = tuple(self.not_found)
        if not all(isinstance(n, NotFoundItem) for n in not_found):
            raise TypeError("not_found must contain only NotFoundItem")
        _set(self, "results", results)
        _set(self, "not_found", not_found)

    @property
    def passed(self):
        """True only if each mandatory check is present and passed (D2, D5).

        A missing check, a failed check, and a "not checked" check all prevent a
        pass, so a check that was not performed can never be reported as passing.
        Non-mandatory results and Not Found items never affect the outcome.
        """
        for name in MANDATORY_CHECKS:
            if not any(r.check == name and r.mandatory for r in self.results):
                return False  # a check that is absent was not performed
        # Every mandatory result, of any check, must have passed.
        return all(r.status is CheckStatus.PASSED for r in self.results if r.mandatory)


# ----------------------------------------------------------------- typed errors
class StageError(Exception):
    """Base class of every expected, typed outcome that stops a run.

    Each subclass carries its designated exit code. Messages must not contain file
    contents or secret values; callers pass only names, counts, and paths.
    """

    exit_code = ExitCode.UNEXPECTED

    def __init__(self, stage, message):
        if stage not in STAGE_MODULES:
            raise ValueError("unknown stage: %r" % (stage,))
        _require_text("message", message)
        super().__init__(message)
        self.stage = stage
        self.message = message

    def __str__(self):
        return "%s: %s" % (self.stage, self.message)


class UsageError(StageError):
    exit_code = ExitCode.USAGE


class InputOrGitError(StageError):
    exit_code = ExitCode.INPUT_OR_GIT


class NoChangesError(StageError):
    exit_code = ExitCode.NO_CHANGES


class OverCapError(StageError):
    exit_code = ExitCode.OVER_CAP


class UnsupportedEntryError(StageError):
    exit_code = ExitCode.UNSUPPORTED_ENTRY


class NoSuitableTargetError(StageError):
    exit_code = ExitCode.NO_SUITABLE_TARGET


class UnresolvedCandidatesError(StageError):
    exit_code = ExitCode.UNRESOLVED_CANDIDATES


class ValidationFailedError(StageError):
    exit_code = ExitCode.VALIDATION_FAILED


class WithheldHunkError(StageError):
    exit_code = ExitCode.WITHHELD_HUNK


class PatchWriteError(StageError):
    exit_code = ExitCode.PATCH_WRITE


class UnexpectedStageError(StageError):
    """An unexpected failure (exit 12). Never used for an expected outcome."""

    exit_code = ExitCode.UNEXPECTED


# Every expected error type, in architecture Section 6a order (used by tests and T15).
EXPECTED_ERRORS = (
    UsageError,
    InputOrGitError,
    NoChangesError,
    OverCapError,
    UnsupportedEntryError,
    NoSuitableTargetError,
    UnresolvedCandidatesError,
    ValidationFailedError,
    WithheldHunkError,
    PatchWriteError,
)
