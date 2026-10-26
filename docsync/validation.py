"""Validator stage. Mandatory checks plus the non-blocking consistency item.

Implemented in plan tasks T11, T11b and T12.

T11 scope (architecture Section 2.4, D2, D5, D7):

* Markdown syntax on the proposed content: unbalanced (unclosed) code fences and
  malformed inline link syntax. Standard library only, no Markdown parser.
* Non-empty output: the generated output as a whole (D7).
* Every result carries a check name, a file where one applies, a line where one is
  known, and a rule. A check that cannot be performed is NOT_CHECKED, never PASSED,
  and carries the file and rule only. How a line is reported for a not-checked
  result is Not Found (design review Gap 7, OQ-3 default), so ``line`` stays None.
* The consistency item (T11b, D28) is a non-blocking NotFoundItem in ``report.not_found``.

T12 scope (D2, D5, D9, D27, OQ-5), see ``check_relative_links``:

* Inline relative links and images on the ADDED lines of each document are resolved
  against the working tree, relative to the directory of the document. The caller
  states which lines are added: ``added_lines`` maps file -> 1-based line numbers of the
  proposed text. The plan does not define this input; nothing upstream produces it yet
  (T13/T15, or a later task, must supply it).
* Numbering rule for ``added_lines`` (LF-based, consistent with Git): lines are separated
  by LF (backslash-n) only. A lone CR, VT (0x0b), FF (0x0c), FS/GS/RS (0x1c-0x1e), NEL
  (0x85), U+2028 and U+2029 do NOT start a new line. A final line without a trailing LF
  counts as a line; a trailing LF does not create an extra empty line; empty text has 0
  lines. One trailing CR on a line (CRLF) is dropped for scanning only. A new file with
  n lines is ``range(1, n+1)``. This single LF rule is used by BOTH the T11 syntax checks
  and the T12 link check: they walk the same line sequence (``_walk``), report the same
  line numbers for the same text and share one fence state, so they cannot diverge. A lone
  CR is therefore never a line break (decided: Git does not treat it as one; CRLF works).
  ``added_lines`` is consumed lazily and bounded (see ``check_relative_links``).
* Ambiguous additions give NOT_CHECKED (rule ``links-added-lines-ambiguous``), never a
  pass: (a) an empty set for a document with any non-blank content; (b) any number
  beyond the document's line count (one out-of-range number marks the whole set
  invalid, because it shows producer and validator disagree on the numbering, so the
  other numbers cannot be trusted). An empty set for an empty or blank-only document
  is not ambiguous: there is nothing to add or check (PASSED; the non-empty-output
  check covers empty documents).
* ``#fragment`` and ``?query`` are stripped; anchors are not checked. The path is
  percent-decoded exactly once, then validated; encoded separators, ``..`` and NUL are
  therefore seen as what they decode to.
* Only existence is checked (``os.path.exists`` on a confined real path). Contents are
  never read. Nothing outside the working-tree root is touched: ``..`` escapes,
  absolute paths, drive letters, UNC paths and symlink/junction escapes (realpath
  confinement) are failures; NUL, control characters, backslashes, ``:``, Windows
  device names and components ending in a dot or space are invalid targets.
* External URLs (never fetched, D9), autolinks, reference-style links, anchor-only
  targets and broken links on lines the edit does not add are declared limitations,
  returned separately and never reported as passing.
* If the check cannot be performed (no root, no added lines for that file, non-text
  content) the result is NOT_CHECKED with file and rule only (D5).
* A PASSED relative_links result carries the scope label rule ``added-inline-relative-links``
  (``RULE_LINKS_SCOPE``). It means only "no broken inline relative link on the added lines".
  External, autolink, reference-style and anchor-only links, and links on lines the edit
  does not add, are outside the check: they are listed as limitations, never as passing.

Known limitations (documented, not fixed; Attempt 1 Lows):

* The root and the target are resolved with ``realpath`` before the confinement test.
* ``..`` is collapsed lexically before the filesystem is consulted, which can differ from
  OS resolution through symlinks.
* Existence is non-strict: on case-insensitive Windows a wrong-case target can pass, and
  device names outside the reserved list (for example COM1 superscript, LPT2 superscript,
  CONIN$, CONOUT$) are not recognised.
* There is no cap on the number of distinct link targets in a document.
* HTML links (``<a href>``, ``<img src>``) are not scanned and empty destinations are
  skipped.
* File names in results are reported as given (not redacted).

Input is a mapping, or a sequence of ``(file, content)`` pairs, of the proposed
document content. Content is data and is only scanned, never executed or followed.
Line numbers are 1-based within the proposed content of that file.
"""

import os
import re
from collections import namedtuple
from urllib.parse import unquote

from docsync.contracts import (
    CHECK_MARKDOWN_SYNTAX,
    CHECK_RELATIVE_LINKS,
    CHECK_NON_EMPTY_OUTPUT,
    CheckResult,
    CheckStatus,
    NotFoundItem,
    ValidationReport,
)

__all__ = [
    "RULE_UNCLOSED_FENCE",
    "RULE_UNCLOSED_LINK",
    "RULE_EMPTY_LINK",
    "RULE_EMPTY_OUTPUT",
    "RULE_NOT_TEXT",
    "RULE_NOT_CHECKED",
    "RULE_LINK_MISSING",
    "RULE_LINK_OUTSIDE_ROOT",
    "RULE_LINK_INVALID",
    "RULE_LINKS_ROOT",
    "RULE_NO_ADDED_LINES",
    "RULE_ADDED_LINES_AMBIGUOUS",
    "RULE_DOC_PATH",
    "RULE_LINKS_SCOPE",
    "LIMIT_EXTERNAL",
    "LIMIT_AUTOLINK",
    "LIMIT_REFERENCE",
    "LIMIT_ANCHOR",
    "LIMIT_NOT_ADDED",
    "LINKS_LIMITATION_SUBJECT",
    "LinkCheck",
    "check_relative_links",
    "limitation_items",
    "scan_markdown",
    "check_markdown_syntax",
    "check_non_empty_output",
    "not_checked",
    "CONSISTENCY_SUBJECT",
    "CONSISTENCY_DETAIL",
    "consistency_not_found",
    "with_consistency_item",
    "validate_content",
]

RULE_UNCLOSED_FENCE = "unclosed-code-fence"
RULE_UNCLOSED_LINK = "link-unclosed-destination"
RULE_EMPTY_LINK = "link-empty-destination"
RULE_EMPTY_OUTPUT = "empty-output"
RULE_NOT_TEXT = "content-not-text"
RULE_NOT_CHECKED = "check-not-performed"

RULE_LINK_MISSING = "link-target-missing"
RULE_LINK_OUTSIDE_ROOT = "link-target-outside-root"
RULE_LINK_INVALID = "link-target-invalid"
RULE_LINKS_ROOT = "links-root-invalid"
RULE_NO_ADDED_LINES = "links-added-lines-unknown"
RULE_ADDED_LINES_AMBIGUOUS = "links-added-lines-ambiguous"
RULE_DOC_PATH = "links-document-path-invalid"
# Scope label carried by every PASSED relative_links result (see check_relative_links).
RULE_LINKS_SCOPE = "added-inline-relative-links"

LIMIT_EXTERNAL = "external-url-not-checked"
LIMIT_AUTOLINK = "autolink-not-checked"
LIMIT_REFERENCE = "reference-link-not-checked"
LIMIT_ANCHOR = "anchor-only-not-checked"
LIMIT_NOT_ADDED = "link-on-line-not-added-by-edit"

LINKS_LIMITATION_SUBJECT = "relative_links_limitation"
_MAX_TARGET = 4096
_MAX_LISTED_LINES = 20
_RESERVED = frozenset(
    ["con", "prn", "aux", "nul"] + ["com%d" % n for n in range(1, 10)] + ["lpt%d" % n for n in range(1, 10)]
)

CONSISTENCY_SUBJECT = "consistency"
CONSISTENCY_DETAIL = "Not Found: consistency is not computed in v1"

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def not_checked(check, file=None, rule=RULE_NOT_CHECKED):
    """A NOT_CHECKED result: file and rule only, no line (Gap 7). Never counts as passed."""
    return CheckResult(check=check, status=CheckStatus.NOT_CHECKED, file=file, line=None, rule=rule)


def _blank_code_spans(line):
    """Blank inline code spans, in linear time and without regular expressions.

    A span opens with a run of N backticks and closes at the next run of exactly N
    backticks on the same line (CommonMark). An opener with no matching closer is
    literal text. Every backtick run is visited a constant number of times."""
    runs = []  # (start, end) of each maximal backtick run
    i, n = 0, len(line)
    while i < n:
        if line[i] == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    if len(runs) < 2:
        return line
    following = [None] * len(runs)  # index of the next run of the same length
    latest = {}
    for k in range(len(runs) - 1, -1, -1):
        size = runs[k][1] - runs[k][0]
        following[k] = latest.get(size)
        latest[size] = k
    chars = None
    k = 0
    while k < len(runs):
        close = following[k]
        if close is None:
            k += 1
            continue
        if chars is None:
            chars = list(line)
        start, end = runs[k][0], runs[close][1]
        chars[start:end] = " " * (end - start)
        k = close + 1
    return line if chars is None else "".join(chars)


def _link_findings(line):
    """Yield rule names for malformed inline links on one non-code line."""
    text = _blank_code_spans(line)
    pos = 0
    while True:
        at = text.find("](", pos)
        if at < 0:
            return
        i = at + 2
        depth = 1
        start = i
        while i < len(text):
            ch = text[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth > 0:
            yield RULE_UNCLOSED_LINK
            return  # the rest of the line is the unterminated destination
        if not text[start:i].strip():
            yield RULE_EMPTY_LINK
        pos = i + 1


def _lf_lines(text):
    r"""Lines of ``text`` separated by LF (backslash-n) only (Git numbering). A trailing LF adds no
    empty line; empty text has no lines. One trailing CR per line is dropped."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _walk(text):
    """The single line walk shared by the T11 and T12 checks. Returns ``(prose, unclosed)``:
    ``prose`` is the list of ``(number, line)`` outside fenced code blocks, numbered by the
    LF rule (``_lf_lines``), and ``unclosed`` is the number of the line that opened a fence
    never closed, or None. Linear time."""
    prose = []
    open_fence = None  # (char, length, line number)
    for number, line in enumerate(_lf_lines(text), start=1):
        match = _FENCE.match(line)
        if open_fence is not None:
            if match:
                marker, rest = match.group(1), match.group(2)
                if marker[0] == open_fence[0] and len(marker) >= open_fence[1] and not rest.strip():
                    open_fence = None
            continue
        if match:
            marker, rest = match.group(1), match.group(2)
            if not (marker[0] == "`" and "`" in rest):  # a backtick fence's info string may not hold a backtick
                open_fence = (marker[0], len(marker), number)
                continue
        prose.append((number, line))
    return prose, (open_fence[2] if open_fence is not None else None)


def scan_markdown(text):
    """Return a sorted list of (line_number, rule) syntax findings for one document.
    Line numbers follow the LF rule shared with the link check."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    findings = []
    prose, unclosed = _walk(text)
    for number, line in prose:
        for rule in _link_findings(line):
            findings.append((number, rule))
    if unclosed is not None:
        findings.append((unclosed, RULE_UNCLOSED_FENCE))
    return sorted(findings)


def _documents(content):
    """Normalize the input to a list of (file, content) pairs."""
    if isinstance(content, (str, bytes)):
        raise TypeError("content must be a mapping or a sequence of (file, content) pairs")
    pairs = list(content.items()) if hasattr(content, "items") else list(content)
    documents = []
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise TypeError("content must be a mapping or a sequence of (file, content) pairs")
        file, text = pair
        if not isinstance(file, str) or not file.strip():
            raise TypeError("each file name must be a non-empty string")
        documents.append((file, text))
    return documents


def check_markdown_syntax(content):
    """Markdown syntax results for every document: one PASSED per clean file, one FAILED
    per finding (file, line, rule), and NOT_CHECKED (file and rule only) for a document
    whose content is not text."""
    results = []
    for file, text in _documents(content):
        if not isinstance(text, str):
            results.append(not_checked(CHECK_MARKDOWN_SYNTAX, file, RULE_NOT_TEXT))
            continue
        findings = scan_markdown(text)
        if not findings:
            results.append(CheckResult(CHECK_MARKDOWN_SYNTAX, CheckStatus.PASSED, file=file))
        for line, rule in findings:
            results.append(
                CheckResult(CHECK_MARKDOWN_SYNTAX, CheckStatus.FAILED, file=file, line=line, rule=rule)
            )
    return results


def check_non_empty_output(content):
    """The whole generated output must hold some non-blank text (D7). No documents, or
    only blank documents, fails. If any content is not text the output cannot be judged
    and the result is NOT_CHECKED."""
    documents = _documents(content)
    if any(not isinstance(text, str) for _, text in documents):
        return not_checked(CHECK_NON_EMPTY_OUTPUT, None, RULE_NOT_TEXT)
    if any(text.strip() for _, text in documents):
        return CheckResult(CHECK_NON_EMPTY_OUTPUT, CheckStatus.PASSED)
    return CheckResult(CHECK_NON_EMPTY_OUTPUT, CheckStatus.FAILED, rule=RULE_EMPTY_OUTPUT)


# ---------------------------------------------------------------- T12: relative links

LinkCheck = namedtuple("LinkCheck", "results limitations")  # CheckResult list; sorted (file, line, rule)


def _inline_destinations(text):
    """Yield the raw destination text of each inline link or image on one line (code
    spans already blanked). An unterminated destination ends the scan. Linear time."""
    pos = 0
    while True:
        at = text.find("](", pos)
        if at < 0:
            return
        i = at + 2
        start = i
        depth = 1
        while i < len(text):
            ch = text[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth > 0:
            return
        inner = text[start:i].strip()
        if inner.startswith("<"):
            end = inner.find(">")
            dest = inner[1:end] if end > 0 else inner[1:]
        else:
            parts = inner.split(None, 1)
            dest = parts[0] if parts else ""
        yield dest
        pos = i + 1


def _has_autolink(text):
    """True if the line has ``<scheme:...>`` with no space inside. Single pass."""
    last = -1
    for i, ch in enumerate(text):
        if ch == "<":
            last = i
        elif ch == ">" and last >= 0:
            body = text[last + 1:i]
            colon = body.find(":")
            if 2 <= colon <= 32 and body[:1].isalpha() and not any(c.isspace() for c in body):
                return True
            last = -1
    return False


def _has_reference(text):
    stripped = text.lstrip(" ")
    if len(text) - len(stripped) <= 3 and stripped.startswith("[") and "]:" in stripped:
        return True  # reference definition
    return "][" in text  # reference-style use


def _scheme_length(dest):
    """Index of the ':' ending a leading URI scheme (letter, then letters, digits, + . -), else 0."""
    if not (dest[:1].isascii() and dest[:1].isalpha()):
        return 0
    i = 1
    while i < len(dest) and dest[i].isascii() and (dest[i].isalnum() or dest[i] in "+.-"):
        i += 1
    return i if i < len(dest) and dest[i] == ":" else 0


def _safe_components(parts):
    """True if every path component is acceptable (no reserved device names, no
    trailing dot or space, no ':')."""
    for comp in parts:
        if comp in ("", ".", ".."):
            continue
        if ":" in comp or comp[-1] in ". ":
            return False
        if comp.split(".", 1)[0].lower() in _RESERVED:
            return False
    return True


def _confined(root_real, real):
    try:
        a, b = os.path.normcase(root_real), os.path.normcase(real)
        return os.path.commonpath([a, b]) == a
    except ValueError:  # different drives, mixed absolute and relative
        return False


def _doc_parts(file):
    """Directory components of the document, or None if its path is not acceptable."""
    name = file.replace("\\", "/")
    if "\0" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None
    comps = [c for c in name.split("/") if c not in ("", ".")]
    if not comps or ".." in comps or not _safe_components(comps):
        return None
    return comps[:-1]


def _classify(dest, root_real, doc_dir, cache):
    """Classify one raw destination. Returns (kind, rule): kind is "ok", "broken" or
    "skip" (a declared limitation). Touches only a confined real path, existence only."""
    if not dest:
        return "skip", None
    if dest.startswith("#"):
        return "skip", LIMIT_ANCHOR
    if dest.startswith("//") or _scheme_length(dest) >= 2:
        return "skip", LIMIT_EXTERNAL  # never fetched (D9), never opened
    raw = dest.split("#", 1)[0].split("?", 1)[0]
    if not raw:
        return "skip", LIMIT_ANCHOR
    if len(raw) > _MAX_TARGET:
        return "broken", RULE_LINK_INVALID
    try:
        path = unquote(raw, errors="strict")  # decoded once; everything below sees the result
    except UnicodeDecodeError:
        return "broken", RULE_LINK_INVALID
    if any(ord(c) < 32 or ord(c) == 127 for c in path) or "\\" in path:
        return "broken", RULE_LINK_INVALID
    if path.startswith("/") or (len(path) > 1 and path[1] == ":" and path[0].isalpha()):
        return "broken", RULE_LINK_OUTSIDE_ROOT  # absolute, UNC or drive-letter path
    parts = path.split("/")
    if not _safe_components(parts):
        return "broken", RULE_LINK_INVALID
    stack = list(doc_dir)
    for comp in parts:
        if comp in ("", "."):
            continue
        if comp == "..":
            if not stack:
                return "broken", RULE_LINK_OUTSIDE_ROOT
            stack.pop()
        else:
            stack.append(comp)
    key = tuple(stack)
    if key not in cache:
        try:
            real = os.path.realpath(os.path.join(root_real, *stack))
            if not _confined(root_real, real):
                cache[key] = ("broken", RULE_LINK_OUTSIDE_ROOT)  # symlink or junction escape
            elif os.path.exists(real):
                cache[key] = ("ok", None)
            else:
                cache[key] = ("broken", RULE_LINK_MISSING)
        except (OSError, ValueError):
            cache[key] = ("broken", RULE_LINK_MISSING)
    return cache[key]


_AMBIGUOUS = object()  # sentinel: the added-line set cannot be trusted
_ITEM_SLACK = 1000


def _added_set(added_lines, file, line_count):
    """The set of added line numbers for ``file``, None if the caller gave none, or
    ``_AMBIGUOUS``. The iterable is consumed lazily and never fully materialized: it stops
    at the first number beyond ``line_count`` (that alone makes the set ambiguous) and after
    ``2 * line_count + 1000`` items consumed (duplicates included). Shape errors (non-int,
    bool, < 1, non-iterable) raise TypeError for every item consumed."""
    if added_lines is None:
        return None
    lines = added_lines.get(file)
    if lines is None:
        return None
    cap = 2 * line_count + _ITEM_SLACK
    result = set()
    consumed = 0
    for n in lines:
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise TypeError("added line numbers must be positive integers")
        if n > line_count:
            return _AMBIGUOUS
        consumed += 1
        if consumed > cap:
            return _AMBIGUOUS
        result.add(n)
    return result


def check_relative_links(content, root=None, added_lines=None):
    """Check inline relative links and images on the added lines (D2, D27).

    ``content``: as for the other checks. ``root``: the working-tree root directory.
    ``added_lines``: mapping file (same key as in ``content``) -> iterable of 1-based
    line numbers of the proposed text that the edit adds. Numbering is LF-based (Git):
    lines are separated by LF only; a lone CR or other Unicode separator is not a line
    break; a trailing LF adds no line; a new file is ``range(1, n+1)``. Bad shapes (not a
    mapping, non-int, bool, or < 1) raise TypeError. The set is ambiguous, and the result
    NOT_CHECKED with rule ``links-added-lines-ambiguous``, if it is empty for a document
    with non-blank content, or holds any number beyond the document's line count.
    The iterable is consumed lazily with a cap: it stops at the first number beyond the line
    count (ambiguous) and after ``2 * line_count + 1000`` items consumed, duplicates included
    (ambiguous), so ``range(1, 10**12)``, an infinite generator or a huge duplicate list
    cost bounded time and memory. A bad-shape item after the stopping point is not seen.
    T13/T15 must supply it; nothing upstream produces it yet.

    Returns a ``LinkCheck``: per-file PASSED (no broken
    link on an added line) or FAILED (file, line, rule) results, NOT_CHECKED (file and
    rule only) when the check cannot be performed, and the declared limitations.
    Every PASSED result carries ``rule=RULE_LINKS_SCOPE`` ("added-inline-relative-links"),
    a scope label: it means only "no broken inline relative link on the added lines".
    External, autolink, reference-style and anchor-only links and links on lines the edit
    does not add are outside the check and are listed as limitations, never as passing.
    """
    documents = _documents(content)
    if added_lines is not None and not hasattr(added_lines, "get"):
        raise TypeError("added_lines must be a mapping of file to line numbers")
    root_real = None
    if isinstance(root, (str, os.PathLike)):
        try:
            candidate = os.path.realpath(root)
            if os.path.isdir(candidate):
                root_real = candidate
        except (OSError, ValueError):
            root_real = None
    results, limitations, cache = [], set(), {}
    for file, text in documents:
        if not isinstance(text, str):
            results.append(not_checked(CHECK_RELATIVE_LINKS, file, RULE_NOT_TEXT))
            continue
        if root_real is None:
            results.append(not_checked(CHECK_RELATIVE_LINKS, file, RULE_LINKS_ROOT))
            continue
        doc_dir = _doc_parts(file)
        if doc_dir is None:
            results.append(not_checked(CHECK_RELATIVE_LINKS, file, RULE_DOC_PATH))
            continue
        line_count = len(_lf_lines(text))
        added = _added_set(added_lines, file, line_count)
        if added is None:
            results.append(not_checked(CHECK_RELATIVE_LINKS, file, RULE_NO_ADDED_LINES))
            continue
        if added is _AMBIGUOUS or (not added and text.strip()):
            results.append(not_checked(CHECK_RELATIVE_LINKS, file, RULE_ADDED_LINES_AMBIGUOUS))
            continue
        failures = set()
        for number, line in _walk(text)[0]:
            blanked = _blank_code_spans(line)
            is_added = number in added
            if is_added:
                if _has_autolink(blanked):
                    limitations.add((file, number, LIMIT_AUTOLINK))
                if _has_reference(blanked):
                    limitations.add((file, number, LIMIT_REFERENCE))
            for dest in _inline_destinations(blanked):
                kind, rule = _classify(dest, root_real, doc_dir, cache)
                if kind == "skip":
                    if is_added and rule:
                        limitations.add((file, number, rule))
                elif kind == "broken":
                    if is_added:
                        failures.add((number, rule))
                    else:
                        limitations.add((file, number, LIMIT_NOT_ADDED))
        if not failures:
            results.append(
                CheckResult(CHECK_RELATIVE_LINKS, CheckStatus.PASSED, file=file, rule=RULE_LINKS_SCOPE)
            )
        for number, rule in sorted(failures):
            results.append(
                CheckResult(CHECK_RELATIVE_LINKS, CheckStatus.FAILED, file=file, line=number, rule=rule)
            )
    return LinkCheck(results, sorted(limitations))


def limitation_items(limitations):
    """Non-blocking NotFoundItems, one per (file, rule), listing up to 20 line numbers."""
    grouped = {}
    for file, line, rule in limitations:
        grouped.setdefault((file, rule), []).append(line)
    items = []
    for (file, rule), lines in sorted(grouped.items()):
        lines = sorted(set(lines))
        shown = ", ".join(str(n) for n in lines[:_MAX_LISTED_LINES])
        more = len(lines) - _MAX_LISTED_LINES
        if more > 0:
            shown += " and %d more" % more
        items.append(NotFoundItem(
            subject=LINKS_LIMITATION_SUBJECT,
            detail="Not Found: link not checked (%s) at line(s) %s" % (rule, shown),
            files=(file,),
        ))
    return items


def consistency_not_found():
    """The single non-blocking source-to-doc consistency item (D28, IS-6). No consistency
    is computed in v1; the item only says so."""
    return NotFoundItem(subject=CONSISTENCY_SUBJECT, detail=CONSISTENCY_DETAIL)


def with_consistency_item(report):
    """Return a report with exactly one consistency Not Found item (D28). The results are
    untouched, so ``passed`` and every failure are unchanged (non-blocking). Idempotent."""
    if not isinstance(report, ValidationReport):
        raise TypeError("report must be a ValidationReport")
    others = tuple(n for n in report.not_found if n.subject != CONSISTENCY_SUBJECT)
    return ValidationReport(results=report.results, not_found=others + (consistency_not_found(),))


def validate_content(content, root=None, added_lines=None):
    """Run the mandatory checks (T11, T12) and return a ValidationReport carrying the
    T11b consistency Not Found item and the T12 link limitations (non-blocking).

    ``root`` and ``added_lines`` feed the relative-link check; without them that check is
    NOT_CHECKED for every document and ``report.passed`` is False (D5).

    Numbering note: T11 syntax findings, T12 link findings and ``added_lines`` all use the
    same LF-only numbering and the same fence state (one shared walk, ``_walk``). A lone CR,
    VT, FF, FS/GS/RS (0x1c-0x1e), NEL (0x85), U+2028 or U+2029 is not a line break."""
    results = check_markdown_syntax(content)
    results.append(check_non_empty_output(content))
    links = check_relative_links(content, root, added_lines)
    results.extend(links.results)
    report = ValidationReport(results=tuple(results), not_found=tuple(limitation_items(links.limitations)))
    return with_consistency_item(report)
