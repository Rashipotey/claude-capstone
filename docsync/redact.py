"""Redactor stage. Masks secret-like text and flags hunks to withhold (D8, D15).

Implemented in plan task T02, extended in T13 (Attempts 2 to 8, each a human-authorized change to
approved T02; the public API never changed). Detection is by pattern only (architecture 7.2). THIS
MODULE DOES NOT DETECT ALL SECRETS; the limits are listed at the end and each is pinned by a
``test_KNOWN_GAP_*`` test. A secret that matches no pattern is not detected.

WARNING FOR CALLERS (T14 and later): ``redact()`` ALONE MUST NEVER BE RELIED ON TO SANITIZE
DOCUMENT TEXT. It masks what the patterns find and misses the cases below (masked text can still hold
a secret). A caller that handles document text must WITHHOLD any text for which ``contains_secret``
is True (as the T13 writer does, D8: it never writes masked text) and use ``redact()`` only for
paths, file names and short messages.

Public API:
    redact(text) -> str                 mask every match; names and structure stay
    contains_secret(text) -> bool       True when any pattern matches
    secret_line_numbers(text) -> list   1-based line numbers with a match (never values)
The three functions share ONE detection path (the same patterns and the same filters:
``_assignment_hits``, ``_extra_assignment_hits``, ``_LINE_PATTERNS``, ``_next_line_hits``,
``_table_hits``), so they agree on what is a hit; ``redact`` is idempotent. A masked text may still be
flagged (fail-closed): ``password: "abc" tail`` becomes ``password: "[REDACTED]" tail`` which is still
flagged because ``[REDACTED]`` is itself a non-empty quoted value. Masked unclosed forms
(``password: "[REDACTED]``) and table cells are not flagged again.

CATEGORIES (all fake examples). (1) key / token / password / passwd / pwd / secret assignments with
``=``, ``:``, ``:=`` (also the full-width ``U+FF1A`` / ``U+FF1D``); (2) PEM private-key blocks;
(3) AWS access key IDs; (4) known token prefixes (ghp_ and friends, github_pat_, xox?-, sk-);
(5) Authorization Bearer / Basic headers; (6) JWTs (``eyJ`` + 5 characters, any payload, signature may
be empty, ``=`` padding); (7) credentials in URLs (``scheme://user:password@host``, the user may be
empty); (8) passphrase / credential(s) assignments; (9) Markdown forms; (10) table rows.

HISTORY, in short (details are in impl-log/T13-patch-writer.md). Attempt 3 bounded the name suffix to
64 word characters and removed the quadratic prefix of ``_ASSIGNMENT``. Attempt 4 made
``secret_line_numbers`` linear and let a URL user be empty (``scheme://:8080@host`` is a fail-closed
false positive). Attempt 5 added Markdown names, backtick values, table rows and short JWT segments.
Attempt 6 restored plain star runs (``password: ***``, ``key: **``, ``token: *``), added unclosed
backtick values and the one-token table value. Attempt 7 added the emphasised-name patterns for an
unclosed quote, a comma, a semicolon and star-only values (``**Password:** "abc``).

ATTEMPT 8 (this text is current; where an older paragraph of the log differs, this one wins).
  A1 PLAIN unclosed quote, comma, semicolon (``_ODD_VALUE``). ``password: "abc``, ``password: 'abc``,
  ``password: ,abc``, ``password: ;abc`` are flagged and the REST OF THE LINE after the opener is
  masked (``password: "[REDACTED]``), the same decision as for emphasised names (after an unclosed
  quote the end of the value is unknown and a secret may hold spaces). A quote that closes on a LATER
  line (``password: "abc`` newline ``def"``) flags and masks the first line only; the continuation is
  never masked by ``redact()`` (a pinned LEAK in redact() output; the hunk is withheld because it is
  flagged). A quote closed on the same line is ``_ASSIGNMENT``'s. Not flagged (no value): the opener
  alone (``password: "``, ``password: ,``), an empty pair, ``"[REDACTED]`` or ``,[REDACTED]`` ending
  the line. Prose such as ``**Password:** , then log in`` and ``the password: "foo bar`` is flagged
  (fail-closed).
  A2 CAMEL-CASE names (``_NAME_START``). A name may start after letters at a camel-case boundary: a
  lower-case letter or digit followed by a capital (``dbPassword``, ``accessToken``, ``clientSecret``,
  ``apiToken``, ``userPassword``, ``myApiKey``, ``v2Token``) or a capital followed by a capitalised
  word (``DBPassword``, ``JWTSecret``). Still NOT names, one by one: ``monkey``, ``donkey``, ``turkey``,
  ``hockey`` (no capital), ``TURKEY`` (no capitalised word), ``passwordless`` / ``tokenizer`` /
  ``keyboard`` / ``secretary`` / ``Keynote`` / ``apikeys`` (letters follow the name; a name needs a
  separator, or one of ``_ . -`` plus a suffix, before ``=`` or ``:``). Fail-closed false positives:
  ``MonKey: x``, ``partitionKey: id``, ``primaryKey: id``, ``password-less: true``. All patterns that
  read a name use it (assignment, passphrase / credential, Markdown, backtick, odd value, next line).
  A3 (a) HTML tags around the name (``<b>Password</b>: abc``, ``<strong>Password:</strong> abc``) and
  (b) backslash-escaped emphasis (``\\*\\*Password\\*\\*: abc``) count as emphasis; a bare label of
  either kind (``<strong>Password:</strong>``) is not flagged. (c) Any Unicode white space except
  CR and LF counts as a blank around the separator (``password:\\u00a0abc``), and the full-width colon
  and equals sign are separators. (d) VALUE ON THE NEXT LINE (``_NEXT_LINE_VALUE``): a name and
  separator (emphasis allowed) that END a line, and on the IMMEDIATELY next line a single token of 1
  to 256 characters (indent allowed) is flagged and masked, reported at the NAME's line. Not a value:
  a start of ``# > | < [ { $ %``, a code fence, filler only (``--- === *** xxx``), ``REDACTED`` / ``n/a``,
  a label ending in a colon (``secretKeyRef:``, ``**Other:**``); a list item, a blank line in between,
  or two tokens are not bridged (pinned misses). False positives: ``**Key:**`` newline ``value``,
  ``Primary key:`` newline ``id``. Emphasis after the separator counts only when the word has
  emphasis before it, so ``key = ***`` newline ``b`` is not read as a label. (e) Text after a placeholder
  (``**Password:** [REDACTED] FakeBoldSecret1``, ``token**:**[REDACTED] hunter2``) is NOT flagged:
  it is exactly what ``redact()`` produces for ``value tail``, so flagging it would make ``redact()``
  non-idempotent. (f) A star-only value not longer than its opener (``*password: *``,
  ``**password: **``, ``***key: ***``) is indistinguishable from a bold marker and is not flagged.
  A4 No new skip rule: the Attempt 4 text is still matched by ``_ASSIGNMENT`` plus extras (new flags
  are a superset of Attempt 4's, proven by a seeded one-way test). Intentional losses (Markdown
  labels with no value) are listed in ``Attempt4SupersetTests.LOST_BY_DESIGN``.
  B TABLE POLICY. A table row is a HEADER ROW when the NEXT line is a separator row (``| --- | --- |``,
  ``|:---:|---:|``); it is exempt only when EVERY cell is 1 to 3 words from a closed list of column-header
  words (``_TABLE_HEADER_WORDS``: name, key, value, type, description, details, default, required,
  optional, example, notes, status, usage, purpose, token, password, secret, field, parameter, option,
  setting, variable, explanation, meaning, ...). A data row is never exempt: ``| password | hunter2 |``
  stays detected even directly under a header, and so do ``| password | admin |``, ``12345``,
  ``default`` and ``none``. The VALUE deny-list gained the data-type vocabulary only (text, int, bool,
  float, double, uuid, varchar, char, json, date, datetime, timestamp, bytes, binary, list, map, enum,
  any). Everything else stays detected, fail-closed: ``| Foreign key | users |``, ``| token | Bearer |``,
  ``| secret | releases |``, a header cell that is not on the list. Measured on this repository's own
  Markdown (README.md and docs/**): the flagged lines before and after the Attempt 8 changes are the
  same one documentation line (docs/pipeline-state.md, a log line that quotes secret syntax).
  Speed: every name pattern starts with a one-character test (a, c, k, p, s, t) and the table filter
  looks up each line once, so scanning is linear; hostile 200,000 and 1,000,000 character lines are
  covered by the timing tests (5 second bound).

REMAINING false negatives and limits (stated plainly; NOT desirable; each is pinned by a
``test_KNOWN_GAP_*`` test; the list is not claimed to be complete):
  * Unknown: bare high-entropy strings, unknown token formats (``glpat-...``, ``AIza...``), natural
    language ("the password is hunter2"), command-line and space-separated forms (``--password
    hunter2``, ``mysql -pSECRET``, ``curl -u user:pass``, ``Authorization: Token abc``), XML elements
    (``<password>hunter2</password>``), ``=>`` (``password => "abc"`` is flagged but ``"abc"`` stays in
    redact() output), names written with look-alike letters (Cyrillic, full-width) or zero-width
    characters, all-capital names without a separator (``DBPASSWORD=x``), file names (not scanned).
  * Names: a secret word, one separator, then MORE than 64 word characters before ``=`` or ``:``.
  * Values cut at ``,`` ``;`` (``password=ab,cd`` leaks ``cd``); a quoted passphrase / credential
    value over 512 characters; star-only values not longer than their opener; text after a placeholder;
    a trailing-underscore bold name is handled only through the plain patterns.
  * URLs: a password with an unencoded ``@`` (``https://u:pa@ss@host`` leaks ``ss``) or with a quote,
    ``<``, ``>`` or ``/``; an empty password or user without password (``https://user:@host``,
    ``https://user@host``); a user or password over 256 characters; a user with a quote, ``<`` or ``>``;
    a scheme over 32 characters; scheme-less ``user:pw@host`` and ``//user:pw@host``.
  * Bearer: standalone ``Bearer x`` outside an Authorization header; tokens under 8 characters.
  * JWT: header under ``eyJ`` + 5 characters, empty payload, fewer than three segments.
  * Backticks: a lone opener (``password: ` ``), the closed triple form (``password: ```abc``` ``) and
    a triple-backtick opener, a blank code span before the value (``password: ` `abc``).
  * Next-line values: a blank line between, a list item, two tokens, over 256 characters, a start
    of ``$`` or ``<`` etc.; a name that is on the line AFTER its separator.
  * HTML: an opening tag with attributes after the separator (``Password: <span class="x">abc``).
  * Multi-line quoted values: the continuation lines are not masked by redact().
  * Tables: a value that is a deny-listed word (type, boolean, header or data-type word) is read as a
    non-value; a value starting with ``<``, ``[``, ``{`` or ``%``; ``$`` followed by letters only or
    by capitals / digits only (read as a variable); a value with spaces or over 256 characters; a value
    of only ``x . - # _ *`` characters (``xxxx``) and a value beginning with four or more marker characters
    (``****real``); two or more extra words in the name cell, a word after the name; the name in another
    column; HTML tables.
  * False positives are possible and fail-closed (a hunk is withheld): ``credentials: required``,
    ``scheme://:8080@host``, ``eyJabcde.tar.gz``, ``- `token`: the token to send``, ``| Key | Explanation |``
    without a separator row, ``**Password:** , then log in``, the camel-case words above.
"""

import bisect
import re

__all__ = ["MASK", "redact", "contains_secret", "secret_line_numbers"]

MASK = "[REDACTED]"

# --- Shared building blocks (Attempt 8) -----------------------------------------------------
# Horizontal white space: ANY Unicode white space except CR and LF (a no-break space, an em space,
# U+3000 ...). It was [ \t]; widening it is a pure superset of the old behavior.
_HS = r"[^\S\r\n]"
# Separators: ":=", "=", ":" and the full-width colon / equals sign (U+FF1A, U+FF1D).
_SEP = r"(?::=|=|:|[\uff1a\uff1d])"
# Where a secret-like name may START: after a non-alphanumeric character (as before), or at a
# camel-case boundary: a lower-case letter or digit followed by a capital (dbPassword,
# accessToken, clientSecret, myApiKey, v2Token), or an upper-case letter followed by a capitalised
# word (DBPassword, JWTSecret). All three are zero-width and constant cost. "monkey", "turkey"
# and "hockey" (no capital) and "TURKEY" (no capitalised word) do NOT qualify. The leading
# lookahead is a speed-up only: every secret-like name starts with one of a, c, k, p, s, t
# (api, access, auth, app, client, credential, key, pass..., private, secret, token), so most
# positions of ordinary text are rejected by one character test.
_NAME_START = (
    r"(?=[ackpstACKPST])(?:(?<![A-Za-z0-9])"
    r"|(?<=(?-i:[a-z0-9]))(?=(?-i:[A-Z]))"
    r"|(?<=(?-i:[A-Z]))(?=(?-i:[A-Z][a-z])))"
)
# Emphasis units: "*", "_" and a backtick (the backtick only AFTER a name), each optionally
# escaped with a backslash (\*\*Password\*\*), and a short HTML tag (<b>, </strong>, <code>).
_TAG = r"</?[A-Za-z][A-Za-z0-9]{0,15}>"
_EM_A = r"(?:\\?[`*_]|" + _TAG + r")"  # between a name and its separator
_EM_A_NO_US = r"(?:\\?[`*]|" + _TAG + r")"  # same, without "_" (plain identifier suffixes)
_EM_B = r"(?:\\?[*_]|" + _TAG + r")"  # between the separator and the value
_STARS = r"(?:\\?[*_])"  # a star or underscore, optionally escaped

# PEM private-key block: the whole block when an END line exists, else header to end of text.
_PEM = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"
    r"(?:.*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|.*\Z)",
    re.DOTALL,
)

# AWS-style access key IDs and well-known token prefixes.
_TOKENS = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|sk-[A-Za-z0-9_-]{20,}"
    r")(?![A-Za-z0-9])"
)

# name = value / name: value, where the name ends in key, token, password, passwd, pwd or secret.
# T13 Attempt 3 (human-authorized change to approved T02): the old optional prefix
# (?:[\w.-]*[_.-])? is gone (it made scanning quadratic on "a_a_a_...") and the suffix \w* is
# bounded to \w{0,64}. Attempt 8: the name may also start at a camel-case boundary (_NAME_START),
# and the blanks and the separator are the wider _HS / _SEP; nothing the Attempt 4 text matched
# is lost (proven by a one-way superset test).
# Group 1 = everything up to the value (kept), group 2 = opening quote, group 3 = the value (masked).
_NAME = r"(?:(?:api|access|secret|auth|private|client|app)?key|token|password|passwd|pwd|secret)"
_ASSIGNMENT = re.compile(
    r"(" + _NAME_START + _NAME + r"(?:[_.-]\w{0,64})?[\"']?" + _HS + r"*" + _SEP + _HS + r"*)"
    r"(?:([\"'])(.*?)\2|([^\s,;\"'`]+))",
    re.IGNORECASE,
)

# --- Additive extension (T13 Attempt 2, human-authorized; existing patterns above are unchanged).
# Every pattern below is anchored on a literal, uses a lookbehind so a match cannot start in the
# middle of a run, or bounds its repetitions, so scanning stays linear on hostile long lines.

# Authorization header with a Bearer or Basic credential. Group 1 kept, group 2 masked.
_BEARER = re.compile(
    r"((?<![A-Za-z0-9])authorization[\"']?[ \t]*[:=][ \t]*[\"']?(?:bearer|basic)[ \t]+)"
    r"([A-Za-z0-9._~+/=-]{8,})",
    re.IGNORECASE,
)

# JSON Web Token: three dot-separated base64url segments, the first starting with "eyJ" (a JSON
# header). Header "eyJ" + at least 5 characters; payload at least 1 character; signature may be
# EMPTY (the "alg":"none" form is detected; a sentence-ending dot after a two-segment token is a
# fail-closed false positive) or of any length; optional "=" padding (0 to 2) after each segment.
# The lookbehind stops a match from starting inside a token. Linear: segments cannot contain "."
# so each attempt reads at most three segments.
_JWT = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{5,}={0,2}\.[A-Za-z0-9_-]+={0,2}\.(?:[A-Za-z0-9_-]+={0,2})?"
)

# scheme://user:password@host. Group 1 (scheme, user and colon) kept, group 2 (password) masked.
# The user may be EMPTY (scheme://:password@host). Every repetition is bounded and the scheme is
# anchored by a lookbehind and the literal "://", so scanning stays linear.
_URL_CRED = re.compile(
    r"((?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{0,31}://[^\s:/@\"'<>]{0,256}:)"
    r"([^\s@/\"'<>]{1,256})(?=@)"
)

# passphrase / credential(s) assignments; same group layout as _ASSIGNMENT.
_EXTRA_ASSIGNMENT = re.compile(
    r"(" + _NAME_START + r"(?:pass[_.-]?phrase|credentials?)"
    r"(?:[_.-][A-Za-z0-9]{1,32})?[\"']?" + _HS + r"*" + _SEP + _HS + r"*)"
    r"(?:([\"'])(.{1,512}?)\2|([^\s,;\"'`]+))",
    re.IGNORECASE,
)

# --- Markdown-formatted names (Attempt 5, extended in Attempts 7 and 8). Same group layout as
# _ASSIGNMENT (group 1 kept, group 2 opening quote, group 3 quoted value, group 4 unquoted value).
# Name = any _ASSIGNMENT name plus passphrase / credential(s), then the same optional suffix.
# The middle part must hold at least one emphasis character or tag (plain forms belong to the
# older patterns). Three shapes: (A) emphasis right after the name, then the separator,
# optionally emphasis after it (`API_KEY`: x, **API_KEY**: x, <b>Password</b>: x, \*\*Password\*\*: x);
# (B) the separator and then emphasis (**Password:** x, <strong>Password:</strong> x);
# (C) the separator then a backtick-quoted value (password: `x`). The value is a quoted string of
# 1 to 256 characters (quote, apostrophe or backtick; a masked [REDACTED] is not a value) or an
# unquoted run that is not only emphasis characters and not [REDACTED]. Every repetition is
# bounded or a single run of one class, so scanning is linear.
_MD_NAME = (
    r"(?:(?:api|access|secret|auth|private|client|app)?key|token|password|passwd|pwd|secret"
    r"|pass[_.-]?phrase|credentials?)"
)
_MD_ASSIGNMENT = re.compile(
    r"(" + _NAME_START + _MD_NAME + r"(?:[_.-]\w{0,64})?"
    r"(?:" + _EM_A + r"{1,3}" + _HS + r"*" + _SEP + _HS + r"*(?:" + _EM_B + r"{1,3}" + _HS + r"*)?"
    r"|" + _HS + r"*" + _SEP + _HS + r"*" + _EM_B + r"{1,3}" + _HS + r"*"
    r"|" + _HS + r"*" + _SEP + _HS + r"*(?=`)))"
    r"(?:([\"'`])(?!\2)(?!\[?redacted\]?\2)(.{1,256}?)\2"
    r"|(?!" + _EM_B + r"+(?:[\s,;\"'`]|\Z))(?!" + _EM_B + r"*\[?redacted\]?(?:\s|\Z))"
    r"(?!(?<=:)=)([^\s,;\"'`]+))",
    re.IGNORECASE,
)

# Unclosed or long backtick value (Attempt 6): ``password: `abc`` with no closing backtick, or a
# backtick value the 256-character quoted form above cannot reach the end of. Group 1 (name,
# separator, opening backtick, spaces) is kept; group 2 is masked. DECISION: the value is the
# REST OF THE LINE up to the next backtick (leading spaces skipped), not one token: a secret with
# spaces is masked whole and nothing is left after it. It is unbounded on purpose (a bound would
# leave a tail unmasked and break idempotence) and linear because each match consumes its value.
_MD_BACKTICK_OPEN = re.compile(
    r"(" + _NAME_START + _MD_NAME + r"(?:[_.-]\w{0,64})?" + _EM_A + r"{0,3}" + _HS + r"*" + _SEP + _HS + r"*"
    r"(?:" + _EM_B + r"{1,3}" + _HS + r"*)?`" + _HS + r"*)"
    r"(?!\[redacted\]" + _HS + r"*(?:`|[\r\n]|\Z))"
    r"([^\s`][^`\r\n]*)",
    re.IGNORECASE,
)

# Markdown table row: | <secret-like name cell> | <one token> |. Group 1 kept, group 2 masked.
# NAME cell: optional emphasis / backticks, then optional prefix (a prefix ending in "_", "." or
# "-"; or a camel-case prefix directly before a capital letter, userPassword; or ONE word and
# spaces, ``API Key`` / ``Admin Password``), a secret-like name, an optional suffix after one
# separator. VALUE cell: ONE token of 1 to 256 characters (no space, no "|") that ends the cell
# (admin, 12345, default and none ARE values). A value cell with spaces is prose and is not a
# value. Not a value: a token starting with "<", "[", "{" or "%" (placeholder, link, template); a
# ``$`` variable reference ($NAME, $name, ${...}, $(...)); starting with ``your-`` / ``your_``;
# only filler (* x . # _ - and the bullet and dashes); or one of the type / header / placeholder
# words listed below (any case). Attempt 8 (table policy): the data-type vocabulary (text, int,
# bool, float, double, uuid, varchar, char, json, date, datetime, timestamp, bytes, binary, list,
# map, enum, any) joined the words, and a HEADER ROW (see _is_table_header_row) is exempt.
# Linear: anchored on "|", every repetition is bounded or one run of one class.
_CELL_END = r"(?=[ \t]*(?:\||\r?$))"
_NOT_A_VALUE = (
    r"[<\[{%]"
    r"|\$(?:[{(]|(?-i:[A-Z_][A-Z0-9_]*)" + _CELL_END + r"|[A-Za-z_]+" + _CELL_END + r")"
    r"|your[-_]"
    r"|[*xX.#_•–—-]+" + _CELL_END +
    r"|(?:n/a|string|required|optional|boolean|integer|number|object|array|redacted|secret"
    r"|password|token|key|value|values|type|types|description|descriptions|details|notes?"
    r"|comments?|example|examples|name|names|status|usage|purpose|meaning"
    r"|true|false|yes|no"
    r"|text|int|bool|float|double|uuid|varchar|char|json|date|datetime|timestamp|bytes|binary"
    r"|list|map|enum|any)" + _CELL_END
)
_NAME_CELL_PREFIX = (
    r"(?:[A-Za-z0-9_.-]{0,40}[_.-]"
    r"|[A-Za-z0-9]{1,40}(?-i:(?=[A-Z]))"
    r"|[A-Za-z0-9]{1,20}[ \t]+)?"
)
_MD_TABLE = re.compile(
    r"(\|[ \t]*[`*_]{0,3}" + _NAME_CELL_PREFIX + _MD_NAME +
    r"(?:[_.-][A-Za-z0-9_.-]{0,32})?[`*_]{0,3}[ \t]*\|[ \t]*[`*_]{0,3})"
    r"(?!" + _NOT_A_VALUE + r")"
    r"([^\s|`*_][^\s|]{0,255})" + _CELL_END,
    re.IGNORECASE | re.MULTILINE,
)

# HEADER-ROW EXEMPTION (Attempt 8, table policy). A table row whose NEXT line is a separator row
# (``| --- | --- |``, ``|:---:|---:|``) is a header row. It is exempt ONLY when EVERY cell is made
# of 1 to 3 words from this closed list of column-header words (empty cells allowed, emphasis and
# backticks ignored). A data row is never exempt, so ``| password | hunter2 |`` stays detected even
# directly under a header, and a header cell that is not on the list keeps the row detected.
_TABLE_HEADER_WORDS = frozenset(
    "name names key keys value values type types description descriptions detail details default "
    "defaults required optional example examples note notes status usage purpose token tokens "
    "password passwords secret secrets field fields parameter parameters param params option "
    "options setting settings variable variables explanation meaning property properties "
    "attribute attributes comment comments format environment env".split()
)
_TABLE_SEPARATOR_CELL = re.compile(r":?-+:?\Z")
_EMPHASIS_CHARS = re.compile(r"[`*_]")


def _table_cells(line):
    """The cells of a table row line (it must start with "|"), or None."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_header_row(line, next_line):
    """True when ``line`` is a header row made only of header words and ``next_line`` is a separator row."""
    if next_line is None:
        return False
    separator = _table_cells(next_line)
    if not separator or not all(_TABLE_SEPARATOR_CELL.match(cell) for cell in separator):
        return False
    cells = _table_cells(line)
    if not cells:
        return False
    for cell in cells:
        words = _EMPHASIS_CHARS.sub("", cell).lower().split()
        if len(words) > 3 or not all(word in _TABLE_HEADER_WORDS for word in words):
            return False
    return True


def _header_row_filter(text):
    """A predicate ``is_header(match)`` for matches of _MD_TABLE found in ``text`` in order.

    The line of a match is looked up once per line (the previous line extent is reused), so the
    cost is linear even when one very long line holds very many matches.
    """
    state = [0, -1, False]  # line start, line end (index of its LF or len(text)), is a header row

    def is_header(match):
        position = match.start()
        if not (state[0] <= position < state[1]):
            start = text.rfind("\n", 0, position) + 1
            end = text.find("\n", position)
            if end < 0:
                end = len(text)
            next_line = None
            if end < len(text):
                next_end = text.find("\n", end + 1)
                next_line = text[end + 1: len(text) if next_end < 0 else next_end]
            state[0], state[1] = start, end
            state[2] = _is_table_header_row(text[start:end], next_line)
        return state[2]

    return is_header


def _table_hits(text):
    is_header = _header_row_filter(text)
    return [m for m in _MD_TABLE.finditer(text) if not is_header(m)]


def _mask_table(text):
    is_header = _header_row_filter(text)
    return _MD_TABLE.sub(lambda m: m.group(0) if is_header(m) else _mask_prefixed(m), text)


def _emphasised_name(after_emphasis, before_value_blank):
    """Regex text for an EMPHASISED name and its separator (Attempt 7, shared by two patterns).

    Form A: emphasis after the name, then the separator, then optional emphasis
    (``**API_KEY**:``, ``*password*:``, ``__password__:``, ``<b>Password</b>:``). Form B: the
    separator, then emphasis (``**Password:**``, ``*token:*``, ``<strong>Password:</strong>``).
    "_" counts as emphasis after the name ONLY when the name itself follows a run of "_" that
    starts at a non-word character, so a plain identifier such as ``secret__:`` or
    ``my_password_:`` is not read as emphasised here (the plain patterns decide).
    """
    name = _NAME_START + _MD_NAME + r"(?:[_.-]\w{0,64})?"
    tail = _HS + r"*" + _SEP + _HS + r"*" + after_emphasis
    form_b = _HS + r"*" + _SEP + _HS + r"*" + _EM_B + r"{1,3}" + before_value_blank
    return (
        r"(?:(?<![A-Za-z0-9_])_{1,3}" + name + r"(?:" + _EM_A + r"{1,3}" + tail + r"|" + form_b + r")"
        r"|" + name + r"(?:" + _EM_A_NO_US + r"{1,3}" + tail + r"|" + form_b + r"))"
    )


# Attempt 7: an emphasised name followed by a value that no other pattern reads: an UNCLOSED quote
# (or a closed one over 256 characters), a comma or a semicolon. ``**Password:** "abc``,
# ``**Password:** ,abc``, ``**API_KEY**: 'abc``, ``__password__: ;abc``. Group 1 (name, separator,
# emphasis, opener, spaces) is kept; the VALUE, the REST OF THE LINE, is masked. Not a value: an
# empty pair (``""``), nothing after the opener, or a ``[REDACTED]`` that closes the quote or ends
# the line (so masked text stays put). Group 2 is the quote opener when the opener is a quote.
_MD_ODD_VALUE = re.compile(
    r"(" + _emphasised_name(r"(?:" + _EM_B + r"{1,3}" + _HS + r"*)?", _HS + r"*") +
    r"(?:([\"'])|[,;])" + _HS + r"*)"
    r"(?(2)(?!\2))"
    r"(?!\[redacted\](?:[\"']|[ \t]*(?:[\r\n]|\Z)))"
    r"[^\s][^\r\n]*",
    re.IGNORECASE,
)

# Attempt 7: an emphasised name followed by a value made only of "*" / "_" characters that ends
# at whitespace or the end of the text: ``**Password:** ***``, ``*password*: **``. Group 1 kept,
# group 2 (the run) masked. The emphasis before a value needs whitespace after it, so
# ``password: ***`` is not read here (the plain pattern handles it exactly as in Attempt 4).
_MD_STAR_VALUE = re.compile(
    r"(" + _emphasised_name(r"(?:" + _EM_B + r"{1,3}" + _HS + r"+)?", _HS + r"+") + r")"
    r"(" + _STARS + r"+)(?=\s|\Z)(?![ \t]*\[redacted\])",
    re.IGNORECASE,
)

# Attempt 8 (A1): a PLAIN (not emphasised) name followed by an UNCLOSED quote, a comma or a
# semicolon: ``password: "abc``, ``password: 'abc``, ``password: ,abc``, ``password: ;abc``, and
# the first line of a quoted value that closes on a LATER line (``password: "abc`` newline
# ``def"``). Group 1 (name, separator, opener, spaces) is kept and the REST OF THE LINE after the
# opener is masked (the same decision as _MD_ODD_VALUE: after an unclosed quote the end of the
# value is unknown, a secret may hold spaces, and a shorter rule would leave a tail). The next
# lines are never touched: redact() leaves the continuation of a multi-line value raw (a pinned
# LEAK), but the hunk is flagged and the writer withholds it. A quote that IS closed on the same
# line is _ASSIGNMENT's (the lookahead below, scanning to the first closing quote or the end of
# the line, keeps the two disjoint). Not a value: nothing after the opener (``password: "`` alone,
# ``password: ,`` alone), an empty pair, or a ``[REDACTED]`` ending the line (masked text stays put).
# Linear: the closing-quote scan runs at most to the next quote of the same kind or the end of
# the line, so the scans of different starts do not overlap; blanks are checked with (?=\S) BEFORE
# the scan so backtracking over blanks never repeats it.
_ODD_VALUE = re.compile(
    r"(" + _NAME_START + _MD_NAME + r"(?:[_.-]\w{0,64})?[\"']?" + _HS + r"*" + _SEP + _HS + r"*"
    r"(?:([\"'])|[,;])" + _HS + r"*)"
    r"(?=\S)"
    r"(?(2)(?![^\n]*?\2))"
    r"(?!\[redacted\](?:[\"']|[ \t]*(?:[\r\n]|\Z)))"
    r"[^\s][^\r\n]*",
    re.IGNORECASE,
)

# Attempt 8 (A3d): a name and separator that END the line (emphasis, tags and a closing quote of
# the name allowed), and on the IMMEDIATELY NEXT line a single token (indent allowed) that looks
# like a value: ``password:`` newline ``hunter2``, ``**Password:**`` newline ``abc``. Group 1 (the
# name line, the line break, the indent) is kept; group 2 (the token) is masked; the reported
# line is the NAME's line. Conservative rule (decision): only the next line (a blank line in
# between is not bridged), a token of 1 to 256 characters and nothing else on the line, and the
# token is NOT: a heading / comment / quote / table / tag / link / template / variable / percent
# start (``# > | < [ { $ %``), a code fence (three backticks or tildes), filler only (``--- ===
# *** ... xxx``), ``REDACTED`` / ``n/a``, or a label (ends with a colon, optionally followed by
# emphasis: ``secretKeyRef:``, ``**Other:**``). A list item (``- abc``) has a space, so it is not a
# single token. Emphasis AFTER the separator (``**Password:**``) counts only when the word that
# holds the name also has emphasis or a tag directly BEFORE it (_next_line_hit), so a plain star
# value such as ``key = ***`` is never read as a label. Group 1 kept, group 2 the emphasis after
# the separator, group 3 the token (masked). Fail-closed false positives: ``**Key:**`` newline
# ``value``, ``Primary key:`` newline ``id``. Linear: bounded token and lookahead lengths, one
# attempt per name.
_NEXT_LINE_END = _HS + r"*(?:\r?\n|\Z)"
_NEXT_LINE_VALUE = re.compile(
    r"(" + _NAME_START + _MD_NAME + r"(?:[_.-]\w{0,64})?(?:" + _EM_A + r"|[\"']){0,3}" + _HS + r"*" + _SEP + _HS + r"*"
    r"(" + _EM_B + r"{1,3}" + _HS + r"*)?\r?\n" + _HS + r"*)"
    r"(?=\S{1,256}" + _NEXT_LINE_END + r")"
    r"(?![#>|<\[{$%]|```|~~~"
    r"|(?:redacted|n/a)" + _NEXT_LINE_END +
    r"|[*xX.#_•–—=~-]+" + _NEXT_LINE_END +
    r"|\S{0,255}:[*_`\\]*" + _NEXT_LINE_END + r")"
    r"(\S{1,256})",
    re.IGNORECASE,
)

# What follows a star-only plain hit when there is NO value to protect: end of the line (after
# optional blanks), a ``[REDACTED]`` (optionally after a quote, backtick, comma or semicolon, the
# forms the masking passes leave), or an empty quote pair that ends the line.
_NO_VALUE_AFTER = re.compile(
    r"[^\S\r\n]*(?:[\"'`,;]?\[redacted\]|[\r\n]|\Z|[\"'`,;][^\S\r\n]*(?:[\r\n]|\Z)"
    r"|([\"'`])\1[^\S\r\n]*(?:[\r\n]|\Z))",
    re.IGNORECASE,
)
_ESCAPED_STARS = re.compile(r"(?:\\?\*)+\Z")
_CLOSING_TAGS = re.compile(r"(?:</[A-Za-z][A-Za-z0-9]{0,15}>)+\Z")


def _is_bold_marker(match):
    """True when an assignment match is only the closing marker of an emphasised LABEL.

    Two shapes, both dropped ONLY when what follows PROVES there is no value to protect
    (``_NO_VALUE_AFTER``: end of line, ``[REDACTED]``, a lone opener, an empty pair):
      * a star-only value (``**Password:**``): the value is unquoted and only "*" (a star may be
        backslash-escaped), and the run of "*" directly before the name is at least as long as the
        value (``**Password:**``, ``*token:*``, ``***key:***``, ``\\*\\*Password:\\*\\*``);
        ``*password: **`` has a longer value than opening, so it is a value;
      * a value made only of HTML closing tags (``<strong>Password:</strong>``, Attempt 8).
    Anything else (``**Password:** "abc``, ``**Password:** ,abc``) keeps the hit. A plain
    ``password: ***`` (no "*" before the name) is never a bold marker.
    """
    if match.group(2):
        return False
    value = match.group(4)
    if not value:
        return False
    if _CLOSING_TAGS.match(value):
        return bool(_NO_VALUE_AFTER.match(match.string, match.end()))
    if not _ESCAPED_STARS.match(value):
        return False
    text, count, opening, position = match.string, value.count("*"), 0, match.start(1)
    # A camel-case name starts inside its word (``**userPassword:**``): step back over the rest of
    # the word first (at most 128 characters, so a long identifier run costs a bounded amount).
    position = _word_start(text, position)
    while opening < count and position > 0 and text[position - 1] == "*":
        opening += 1
        position -= 1
        if position > 0 and text[position - 1] == "\\":
            position -= 1
    if opening < count:
        return False
    return bool(_NO_VALUE_AFTER.match(text, match.end()))


def _word_start(text, position):
    """Start of the word that holds a name starting at ``position`` (at most 128 characters back)."""
    limit = max(0, position - 128)
    while position > limit and (text[position - 1].isalnum() or text[position - 1] in "_.-"):
        position -= 1
    return position


def _next_line_hit(match):
    """False for a _NEXT_LINE_VALUE candidate whose emphasis after the separator has no partner.

    ``**Password:**`` newline ``abc`` is a label (emphasis before the word and after the
    separator); ``key = ***`` newline ``b`` is a plain star value followed by another line.
    """
    if match.group(2) is None:
        return True
    start = _word_start(match.string, match.start(1))
    return start > 0 and match.string[start - 1] in "*_`>"


def _next_line_hits(text):
    return [m for m in _NEXT_LINE_VALUE.finditer(text) if _next_line_hit(m)]


def _mask_next_line(match):
    return match.group(1) + MASK if _next_line_hit(match) else match.group(0)


def _assignment_value(match):
    return match.group(3) if match.group(2) else match.group(4)


def _assignment_hits(text):
    return [m for m in _ASSIGNMENT.finditer(text) if _assignment_value(m) and not _is_bold_marker(m)]


def _mask_assignment_text(match):
    return match.group(0) if _is_bold_marker(match) else _mask_assignment(match)


def _mask_prefixed(match):
    return match.group(1) + MASK


def _extra_assignment_hits(text):
    return [m for m in _EXTRA_ASSIGNMENT.finditer(text) if _assignment_value(m) and not _is_bold_marker(m)]


def _mask_assignment(match):
    prefix, quote = match.group(1), match.group(2)
    if quote:
        if not match.group(3):
            return match.group(0)  # empty quoted value: nothing to mask
        return "%s%s%s%s" % (prefix, quote, MASK, quote)
    return prefix + MASK


# Patterns whose every match is a hit (group 1 is the kept prefix). The ONE list read by
# contains_secret and secret_line_numbers; redact() masks the same patterns in its own order.
_LINE_PATTERNS = (_MD_ASSIGNMENT, _MD_BACKTICK_OPEN, _MD_ODD_VALUE, _MD_STAR_VALUE, _ODD_VALUE)


def redact(text):
    """Return text with every secret-like value replaced by MASK."""
    if not isinstance(text, str) or not text:
        return text
    text = _PEM.sub(MASK, text)
    text = _TOKENS.sub(MASK, text)
    # The Markdown pattern runs BEFORE _ASSIGNMENT: in ``_password:_ x`` the older pattern takes
    # the closing "_" as its value, which would leave ``x`` unmasked if it ran first.
    text = _MD_ASSIGNMENT.sub(_mask_assignment, text)
    text = _MD_BACKTICK_OPEN.sub(_mask_prefixed, text)
    # Attempt 7: values the passes above cannot read (unclosed quote, comma, semicolon, a star
    # run) after an emphasised name are masked here, so the bold-marker filter below only ever
    # sees a hit with no value after it, or with a value that was just masked.
    text = _MD_ODD_VALUE.sub(_mask_prefixed, text)
    text = _MD_STAR_VALUE.sub(_mask_prefixed, text)
    # Attempt 8: a value on the next line, and a plain unclosed quote / comma / semicolon value.
    text = _NEXT_LINE_VALUE.sub(_mask_next_line, text)
    text = _ODD_VALUE.sub(_mask_prefixed, text)
    # Attempt 6: after the Markdown passes the real value of ``**Password:** x`` is already masked,
    # so the "**" that _ASSIGNMENT would take as a value is only the closing bold marker: it is kept.
    text = _ASSIGNMENT.sub(_mask_assignment_text, text)
    text = _BEARER.sub(_mask_prefixed, text)
    text = _JWT.sub(MASK, text)
    text = _URL_CRED.sub(_mask_prefixed, text)
    text = _EXTRA_ASSIGNMENT.sub(_mask_assignment_text, text)
    text = _mask_table(text)
    return text


def contains_secret(text):
    """True when the text holds a secret-like value (used to withhold a hunk, D8)."""
    if not isinstance(text, str) or not text:
        return False
    if _PEM.search(text) or _TOKENS.search(text):
        return True
    if _BEARER.search(text) or _JWT.search(text) or _URL_CRED.search(text) or _extra_assignment_hits(text):
        return True
    if any(pattern.search(text) for pattern in _LINE_PATTERNS) or _next_line_hits(text):
        return True
    is_header = _header_row_filter(text)
    if any(not is_header(m) for m in _MD_TABLE.finditer(text)):
        return True
    return bool(_assignment_hits(text))


def secret_line_numbers(text):
    """1-based line numbers holding a match. Returns numbers only, never values.

    Linear (T13 Attempt 4): the offsets of the newlines are found once, lazily, and each match
    is placed with a binary search. The old version counted newlines from the start of the text
    for every match, which was quadratic on a line with very many matches. Results are identical.
    """
    if not isinstance(text, str) or not text:
        return []
    offsets = []
    scanned = []

    def line_of(position):
        if not scanned:
            scanned.append(True)
            offsets.extend(m.start() for m in re.finditer(r"\n", text))
        return bisect.bisect_left(offsets, position) + 1  # newlines before position, plus one

    lines = set()
    for pattern in (_PEM, _TOKENS):
        for m in pattern.finditer(text):
            lines.add(line_of(m.start()))
    for m in _assignment_hits(text):
        lines.add(line_of(m.start(1)))
    for pattern in (_BEARER, _JWT, _URL_CRED):
        for m in pattern.finditer(text):
            lines.add(line_of(m.start()))
    for m in _extra_assignment_hits(text):
        lines.add(line_of(m.start(1)))
    for pattern in _LINE_PATTERNS:
        for m in pattern.finditer(text):
            lines.add(line_of(m.start(1)))
    for m in _next_line_hits(text) + _table_hits(text):
        lines.add(line_of(m.start(1)))
    return sorted(lines)
