"""T13 tests: Patch Writer (docsync.output).

All fixtures are local and temporary. Secret values are obviously fake. Tests change the
working directory only inside temporary directories and always restore it. Symlink cases are
skipped where symlinks cannot be created; Windows junction variants run where possible.
"""

import ast
import contextlib
import copy
import dataclasses
import errno
import hashlib
import inspect
import io
import os
import re
import stat
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from docsync import contracts, output, redact, validation
from docsync.contracts import (
    CheckResult,
    CheckStatus,
    ExitCode,
    NotFoundItem,
    PatchWriteError,
    UnexpectedStageError,
    ValidationReport,
    WithheldHunkError,
)
from docsync.output import (
    DocumentChange,
    PatchToken,
    WithheldFinding,
    WithheldHunksError,
    approve_patch,
    check_no_existing_patch,
    publish_patch,
    raise_if_withheld,
    render_patch,
    rollback_patch,
)
from tests.helpers.gitrepo import TempGitRepo, git_available

ORIG_LINES = [
    "# API", "", "Intro line.", "", "## Usage", "", "Call run().", "", "## Notes", "", "See below.",
]
ORIG = "\n".join(ORIG_LINES) + "\n"
PASSED = ValidationReport(
    results=tuple(CheckResult(c, CheckStatus.PASSED) for c in contracts.MANDATORY_CHECKS)
)
SECRETS = {
    "key": (["api_key = \"FAKEKEYVALUE1234567890\""], ["FAKEKEYVALUE1234567890"]),
    "token": (["auth_token: FAKETOKENVALUE123456"], ["FAKETOKENVALUE123456"]),
    "password": (["password = \"FakePassw0rdNotReal\""], ["FakePassw0rdNotReal"]),
    "secret": (["client_secret=FAKESECRETVALUE9876"], ["FAKESECRETVALUE9876"]),
    "pem": (
        ["-----BEGIN RSA PRIVATE KEY-----", "FAKEPEMBODYNOTREAL", "-----END RSA PRIVATE KEY-----"],
        ["FAKEPEMBODYNOTREAL"],
    ),
    "aws": (["AWS id AKIAFAKEFAKEFAKE1234 here"], ["AKIAFAKEFAKEFAKE1234"]),
    # Added in T13 Attempt 2 (M4); fake values only.
    "bearer": (["Authorization: Bearer FAKEBEARERVALUE12345"], ["FAKEBEARERVALUE12345"]),
    "jwt": (
        ["JWT eyJhbGciOiJub25lIn0.eyJzdWIiOiJmYWtlIn0.ZmFrZXNpZ25hdHVyZQ here"],
        ["eyJhbGciOiJub25lIn0.eyJzdWIiOiJmYWtlIn0.ZmFrZXNpZ25hdHVyZQ"],
    ),
    "url": (["clone https://deploy:FakeUrlPass123@git.example.com/r.git"], ["FakeUrlPass123"]),
    # Added in T13 Attempt 4: URL credentials with an EMPTY user name.
    "url_empty_user": (["cache redis://:FakeEmptyUserPass123@cache.local:6379/0"], ["FakeEmptyUserPass123"]),
    "passphrase": (["gpg passphrase = \"FakePassphraseNotReal\""], ["FakePassphraseNotReal"]),
    # Added in T13 Attempt 5 (B1, B2): short JWT segments and Markdown-formatted names.
    "jwt_empty_signature": (["JWT eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0. here"], ["eyJhbGciOiJub25lIn0"]),
    "jwt_short_segments": (["JWT eyJhbGciOiJub25lIn0.e30.sig here"], ["eyJhbGciOiJub25lIn0"]),
    "md_backtick_name": (["- `API_KEY`: FakeBacktickSecret1"], ["FakeBacktickSecret1"]),
    "md_bold_name": (["**Password:** FakeBoldSecret1"], ["FakeBoldSecret1"]),
    "md_bold_name_colon_outside": (["**API_KEY**: FakeBoldSecret2"], ["FakeBoldSecret2"]),
    "md_table_cell": (["| password | FakeTableSecret1 |"], ["FakeTableSecret1"]),
    # Added in T13 Attempt 6: unclosed backtick, short/default-like table values, star runs.
    "md_unclosed_backtick": (["password: `FakeUnclosedSecret1"], ["FakeUnclosedSecret1"]),
    "md_table_admin": (["| password | admin |"], ["admin"]),
    "md_table_12345": (["| password | 12345 |"], ["12345"]),
    "md_table_default": (["| password | default |"], ["default"]),
    "md_table_none": (["| password | none |"], ["none"]),
    "star_run": (["password: ***"], ["***"]),
    # Added in T13 Attempt 8: camel-case names, plain unclosed quote / comma, HTML-tag name, escaped
    # emphasis, no-break space, full-width colon, and a value on the next line.
    "camel_db_password": (["dbPassword: FakeCamelSecret1"], ["FakeCamelSecret1"]),
    "camel_access_token": (["accessToken=FakeCamelToken1"], ["FakeCamelToken1"]),
    "plain_unclosed_quote": (['password: "FakeUnclosedQuote1'], ["FakeUnclosedQuote1"]),
    "plain_comma_opener": (["password: ,FakeCommaSecret1"], ["FakeCommaSecret1"]),
    "html_tag_name": (["<b>Password</b>: FakeHtmlSecret1"], ["FakeHtmlSecret1"]),
    "escaped_emphasis": ([r"\*\*Password\*\*: FakeEscapedSecret1"], ["FakeEscapedSecret1"]),
    "nbsp_after_separator": (["password: FakeNbspSecret1"], ["FakeNbspSecret1"]),
    "fullwidth_colon": (["Password：FakeFullWidth1"], ["FakeFullWidth1"]),
    "next_line_value": (["**Password:**", "FakeNextLineSecret1"], ["FakeNextLineSecret1"]),
    "next_line_plain": (["token:", "FakeNextLineToken1"], ["FakeNextLineToken1"]),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    """SHA-256 of every file under root, excluding .git (links are not followed)."""
    result = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            full = os.path.join(base, name)
            result[os.path.relpath(full, root).replace(os.sep, "/")] = sha(Path(full).read_bytes())
    return result


@contextlib.contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def make_change(path="docs/api.md", original=ORIG, proposed=None):
    if proposed is None:
        proposed = original + "\n- `run`: behavior changed.\n"
    return DocumentChange(path, original, proposed)


def approved_for(repo, change=None, report=PASSED):
    rendered = render_patch([change or make_change()], redact)
    return approve_patch(rendered, report, str(repo), (), redact)


def apply_patch_text(original, patch_text):
    """Test-only: apply the single-file hunks of ``patch_text`` to ``original`` (LF rule)."""
    src = output._split_lf(original)
    out, pos = [], 0
    lines = patch_text.split("\n")
    # drop the final empty element produced by the trailing newline
    if lines and lines[-1] == "":
        lines.pop()
    i = 2  # skip '---' and '+++'
    while i < len(lines):
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
        assert m, lines[i]
        start = int(m.group(1)) if m.group(2) == "0" else int(m.group(1)) - 1
        out.extend(src[pos:start])
        pos = start
        i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            line = lines[i]
            if line.startswith("\\"):
                out[-1] = out[-1].rstrip("\n") if line.startswith("\\ No newline") and out and not lines[i - 1].startswith("-") else out[-1]
            elif line[0] == " ":
                assert src[pos] == line[1:] + "\n" or src[pos] == line[1:], "context mismatch"
                out.append(src[pos])
                pos += 1
            elif line[0] == "-":
                pos += 1
            else:
                out.append(line[1:] + "\n")
            i += 1
    out.extend(src[pos:])
    return "".join(out)


def symlinks_available():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink(os.path.join(tmp, "target"), os.path.join(tmp, "link"))
        except (OSError, NotImplementedError, AttributeError):
            return False
        return True


SYMLINKS = symlinks_available()
SYMLINK_SKIP = "symlink creation unavailable on this machine (no privilege)"


def make_junction(target, link):
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, AttributeError, OSError) as exc:
        raise unittest.SkipTest("junction creation unavailable: %s" % type(exc).__name__)


class WorkCase(unittest.TestCase):
    """A repository (never the working directory) and a separate working directory."""

    def setUp(self):
        if not git_available():
            self.skipTest("git not available")
        self.repo = TempGitRepo({
            "README.md": "# Project\n",
            "docs/api.md": ORIG,
            ".gitignore": "*.pyc\n",
            "src/main.py": "print('hi')\n",
        })
        self.addCleanup(self.repo.cleanup)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve()
        old = os.getcwd()
        self.addCleanup(os.chdir, old)  # runs before the directory cleanups (LIFO)
        os.chdir(self.work)
        self.root = self.repo.path.resolve()
        self.before = snapshot(self.root)

    def approved(self, **kw):
        return approved_for(self.root, **kw)

    def assert_repo_untouched(self):
        self.assertEqual(snapshot(self.root), self.before)


# ------------------------------------------------------------------------- rendering
class RenderTests(unittest.TestCase):
    def test_unified_diff_is_deterministic_and_has_no_timestamps(self):
        a = DocumentChange("docs/b.md", ORIG, ORIG + "x\n")
        b = DocumentChange("docs/a.md", ORIG, ORIG + "y\n")
        r1 = render_patch([a, b], redact)
        r2 = render_patch([b, a], redact)
        self.assertEqual(r1.text, r2.text)
        self.assertLess(r1.text.index("--- a/docs/a.md"), r1.text.index("--- a/docs/b.md"))
        for line in r1.text.splitlines():
            if line.startswith(("--- ", "+++ ")):
                self.assertNotIn("\t", line)
                self.assertRegex(line, r"^(---|\+\+\+) [ab]/docs/[ab]\.md$")
        self.assertEqual(r1.files, ("docs/a.md", "docs/b.md"))

    def test_round_trip_and_minimal_edit(self):
        proposed = ORIG + "\n- `run`: behavior changed.\n"
        r = render_patch([DocumentChange("docs/api.md", ORIG, proposed)], redact)
        self.assertEqual(apply_patch_text(ORIG, r.text), proposed)
        added = [l for l in r.text.splitlines()[2:] if l.startswith("+")]
        removed = [l for l in r.text.splitlines()[2:] if l.startswith("-")]
        self.assertEqual(removed, [])  # NFR-05: unrelated lines are only context
        self.assertEqual(added, ["+", "+- `run`: behavior changed."])
        self.assertEqual(r.added_lines, {"docs/api.md": (12, 13)})

    def test_middle_change_round_trip_and_two_hunks(self):
        orig = "\n".join("line%d" % i for i in range(1, 31)) + "\n"
        prop = orig.replace("line2\n", "LINE2\n").replace("line28\n", "LINE28\n")
        r = render_patch([DocumentChange("docs/a.md", orig, prop)], redact)
        self.assertEqual(len(r.hunks), 2)
        self.assertEqual(apply_patch_text(orig, r.text), prop)

    def test_crlf_is_preserved_and_only_lf_breaks_lines(self):
        orig = "a\r\nb\r\n"
        prop = "a\r\nb\r\nc\r\n"
        r = render_patch([DocumentChange("docs/a.md", orig, prop)], redact)
        self.assertIn("+c\r\n", r.text)
        self.assertIn(" b\r\n", r.text)
        # a lone CR / U+2028 does not start a new numbered line (Git numbering)
        r2 = render_patch([DocumentChange("docs/a.md", "x\n", "x\ny\rz\u2028w\n")], redact)
        self.assertEqual(r2.added_lines, {"docs/a.md": (2,)})

    def test_no_newline_marker(self):
        r = render_patch([DocumentChange("docs/a.md", "a\nb", "a\nb\nc")], redact)
        self.assertIn("-b\n\\ No newline at end of file\n", r.text)
        self.assertIn("+b\n+c\n\\ No newline at end of file\n", r.text)

    def test_identical_and_empty_inputs_produce_nothing(self):
        r = render_patch([DocumentChange("docs/a.md", ORIG, ORIG)], redact)
        self.assertEqual((r.text, r.hunks, r.withheld), ("", (), ()))
        self.assertEqual(render_patch([], redact).text, "")

    def test_invalid_inputs(self):
        for bad in ("../x.md", "/etc/x.md", "docs/../README.md", "docs\\a.md", "docs/a.md\n+++ b/x",
                    "C:/x.md", "src/a.py", "docs/", "", "docs//a.md", "docs/a\tb.md"):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                DocumentChange(bad, "a\n", "b\n")
        with self.assertRaises(ValueError):
            DocumentChange("docs/a.md", "a\x00", "b")
        with self.assertRaises(TypeError):
            DocumentChange("docs/a.md", b"a", "b")
        with self.assertRaises(ValueError):
            render_patch([make_change(), make_change()], redact)
        with self.assertRaises(TypeError):
            render_patch([make_change()], object())
        with self.assertRaises(TypeError):
            render_patch(["docs/a.md"], redact)
        DocumentChange("README.md", "a\n", "b\n")  # allowed

    def test_proposed_edit_contract_has_no_text(self):
        # Input-shape tension: T10 ProposedEdit carries no document text, so the writer cannot
        # render from it; DocumentChange is the writer's own input.
        fields = {f for f in contracts.ProposedEdit.__slots__}
        self.assertFalse(fields & {"original", "proposed", "added_lines", "text", "content"})


# ----------------------------------------------------------------------------- secrets
class SecretTests(WorkCase):
    def build(self, kind, where):
        lines, values = SECRETS[kind]
        n = len(lines)
        if where == "added":
            orig = list(ORIG_LINES)
            prop = orig[:7] + lines + orig[7:]
        elif where == "removed":
            prop = list(ORIG_LINES)
            orig = prop[:7] + lines + prop[7:]
        else:  # context: the secret is unchanged and immediately before the change
            base = ORIG_LINES[:7] + lines + ORIG_LINES[7:]
            orig = base
            prop = base[:7 + n] + ["Added line."] + base[7 + n:]
        return "\n".join(orig) + "\n", "\n".join(prop) + "\n", values

    def test_secret_in_added_removed_and_context_line_each_withhold(self):
        for kind in SECRETS:
            for where in ("added", "removed", "context"):
                with self.subTest(kind=kind, where=where):
                    orig, prop, values = self.build(kind, where)
                    r = render_patch([DocumentChange("docs/api.md", orig, prop)], redact)
                    self.assertTrue(r.has_withheld)
                    self.assertEqual(r.text, "")
                    self.assertEqual(r.withheld, (WithheldFinding("docs/api.md", 8),))
                    with self.assertRaises(WithheldHunksError) as ctx:
                        raise_if_withheld(r)
                    err = ctx.exception
                    self.assertIsInstance(err, WithheldHunkError)
                    self.assertEqual(err.exit_code, ExitCode.WITHHELD_HUNK)
                    self.assertEqual(err.findings, r.withheld)
                    shown = "%s|%r|%r|%r" % (err, r, r.hunks, err.findings)
                    for value in values:
                        self.assertNotIn(value, shown)
                    # the writer refuses it too, as an unexpected failure, and writes nothing
                    with self.assertRaises(UnexpectedStageError) as ctx2:
                        approve_patch(r, PASSED, str(self.root), (), redact)
                    self.assertEqual(ctx2.exception.exit_code, ExitCode.UNEXPECTED)
                    self.assertEqual(os.listdir(self.work), [])

    def test_attempt_8_forms_are_withheld_with_file_and_line_only(self):
        # End to end for each form fixed in Attempt 8: no patch text, the error carries file and
        # line only, the secret value is absent from every output, and approve_patch refuses it.
        for kind in ("camel_db_password", "camel_access_token", "plain_unclosed_quote", "plain_comma_opener",
                     "html_tag_name", "escaped_emphasis", "nbsp_after_separator", "fullwidth_colon",
                     "next_line_value", "next_line_plain"):
            _lines, values = SECRETS[kind]
            orig, prop, _ = self.build(kind, "added")
            r = render_patch([DocumentChange("docs/api.md", orig, prop)], redact)
            with self.subTest(kind=kind):
                self.assertTrue(r.has_withheld)
                self.assertEqual(r.text, "")
                self.assertEqual(r.withheld, (WithheldFinding("docs/api.md", 8),))
                with self.assertRaises(WithheldHunksError) as ctx:
                    raise_if_withheld(r)
                shown = "%s|%r|%r|%r|%r" % (ctx.exception, r, r.hunks, ctx.exception.findings, r.withheld)
                for value in values:
                    self.assertNotIn(value, shown)
                self.assertTrue(all(h.lines == () for h in r.hunks if h.withheld))
                with self.assertRaises(UnexpectedStageError) as ctx2:
                    approve_patch(r, PASSED, str(self.root), (), redact)
                for value in values:
                    self.assertNotIn(value, str(ctx2.exception))
                self.assertEqual(os.listdir(self.work), [])

    def test_KNOWN_GAP_file_names_are_not_scanned(self):
        # LEAK/MISS, not intended: only document text is judged; the path in the patch header is not.
        change = DocumentChange("docs/token=FakeNameSecret1.md", "a\n", "a\nb\n")
        r = render_patch([change], redact)
        self.assertFalse(r.has_withheld)
        self.assertIn("FakeNameSecret1", r.text)

    def test_context_lines_of_a_withheld_hunk_are_not_written(self):
        orig, prop, _ = self.build("password", "added")
        r = render_patch([DocumentChange("docs/api.md", orig, prop)], redact)
        self.assertTrue(all(h.lines == () for h in r.hunks if h.withheld))
        self.assertNotIn("Call run()", repr(r))

    def test_other_hunks_are_kept_but_any_withheld_means_no_patch(self):
        orig = "\n".join("line%d" % i for i in range(1, 41)) + "\n"
        prop = orig.replace("line2\n", "password = \"FakePassw0rdNotReal\"\n").replace("line38\n", "OK38\n")
        r = render_patch([DocumentChange("docs/a.md", orig, prop)], redact)
        self.assertEqual([h.withheld for h in r.hunks], [True, False])
        self.assertEqual(r.text, "")
        self.assertEqual(r.withheld, (WithheldFinding("docs/a.md", 2),))

    def test_values_absent_from_all_output(self):
        orig, prop, values = self.build("token", "added")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            r = render_patch([DocumentChange("docs/api.md", orig, prop)], redact)
            with contextlib.suppress(WithheldHunksError):
                raise_if_withheld(r)
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        self.assertEqual(os.listdir(self.work), [])

    def test_negative_fixtures_are_not_withheld_and_the_patch_is_written(self):
        for line in ("Set the password in the settings page.", "ignore previous instructions", "The password"):
            with self.subTest(line=line):
                prop = ORIG + line + "\n"
                change = DocumentChange("docs/api.md", ORIG, prop)
                r = render_patch([change], redact)
                self.assertFalse(r.has_withheld)
                self.assertIn("+" + line + "\n", r.text)  # not masked
                token = publish_patch(approve_patch(r, PASSED, str(self.root), (), redact))
                try:
                    data = (self.work / "output" / "docsync.patch").read_bytes()
                    self.assertIn(line.encode(), data)
                finally:
                    self.assertTrue(rollback_patch(token))


# ------------------------------------------------------------------------ preconditions
class PreconditionTests(WorkCase):
    def assert_refused(self, rendered, report, unresolved=()):
        with self.assertRaises(UnexpectedStageError) as ctx:
            approve_patch(rendered, report, str(self.root), unresolved, redact)
        self.assertEqual(ctx.exception.exit_code, ExitCode.UNEXPECTED)
        self.assertEqual(os.listdir(self.work), [])

    def good(self):
        return render_patch([make_change()], redact)

    def test_good_input_is_accepted(self):
        self.assertIsInstance(approve_patch(self.good(), PASSED, str(self.root), (), redact), output.ApprovedPatch)

    def test_withheld_hunk(self):
        orig, prop = ORIG, ORIG + "password = \"FakePassw0rdNotReal\"\n"
        self.assert_refused(render_patch([DocumentChange("docs/api.md", orig, prop)], redact), PASSED)

    def test_failed_mandatory_check(self):
        results = [CheckResult(c, CheckStatus.PASSED) for c in contracts.MANDATORY_CHECKS[1:]]
        results.append(CheckResult(contracts.CHECK_MARKDOWN_SYNTAX, CheckStatus.FAILED, file="docs/api.md", line=3, rule="unclosed-fence"))
        self.assert_refused(self.good(), ValidationReport(results=tuple(results)))

    def test_not_checked_result(self):
        results = [CheckResult(c, CheckStatus.PASSED) for c in contracts.MANDATORY_CHECKS[:2]]
        results.append(CheckResult(contracts.CHECK_NON_EMPTY_OUTPUT, CheckStatus.NOT_CHECKED, file="docs/api.md", rule="not-checked"))
        self.assert_refused(self.good(), ValidationReport(results=tuple(results)))

    def test_missing_check_and_empty_report(self):
        self.assert_refused(self.good(), ValidationReport())

    def test_empty_output(self):
        self.assert_refused(render_patch([], redact), PASSED)
        self.assert_refused(render_patch([DocumentChange("docs/api.md", ORIG, ORIG)], redact), PASSED)

    def test_unresolved_in_scope_change(self):
        self.assert_refused(self.good(), PASSED, unresolved=("src/x.py",))

    def test_unresolved_must_be_an_explicit_collection(self):
        # T13 Attempt 3, L1: an empty str / bytes / dict is not "none unresolved".
        def gen():
            return (x for x in ())

        for case, bad in (("empty str", ""), ("empty bytes", b""), ("empty dict", {}), ("None", None),
                          ("generator", gen()), ("str", "x"), ("int", 0), ("range", range(0)),
                          ("non-empty dict", {"a": 1}), ("bytes", b"x")):
            with self.subTest(case=case):
                self.assert_refused(self.good(), PASSED, unresolved=bad)

    def test_empty_explicit_collections_are_accepted(self):
        for case, ok in (("tuple", ()), ("list", []), ("set", set()), ("frozenset", frozenset())):
            with self.subTest(case=case):
                self.assertIsInstance(approve_patch(self.good(), PASSED, str(self.root), ok, redact), output.ApprovedPatch)

    def test_non_empty_collections_are_refused(self):
        for case, bad in (("list", ["src/x.py"]), ("tuple", ("src/x.py",)), ("set", {"src/x.py"}), ("frozenset", frozenset({"a"}))):
            with self.subTest(case=case):
                self.assert_refused(self.good(), PASSED, unresolved=bad)

    def test_subclasses_and_lookalike_collections_are_refused(self):
        # T13 Attempt 4: only the exact built-in types are accepted, so len() is trustworthy.
        import collections

        class LyingList(list):
            def __len__(self):
                return 0

            def __bool__(self):
                return False

        class LyingSet(set):
            def __len__(self):
                return 0

        class LyingTuple(tuple):
            def __len__(self):
                return 0

        class LyingFrozenset(frozenset):
            def __len__(self):
                return 0

        class EmptySubclass(list):
            pass

        Pair = collections.namedtuple("Pair", "a b")
        Nothing = collections.namedtuple("Nothing", "")
        for case, bad in (
            ("list subclass, lying len, has items", LyingList(["src/x.py"])),
            ("set subclass, lying len, has items", LyingSet({"src/x.py"})),
            ("tuple subclass, lying len, has items", LyingTuple(("src/x.py",))),
            ("frozenset subclass, lying len, has items", LyingFrozenset({"src/x.py"})),
            ("honest empty list subclass", EmptySubclass()),
            ("namedtuple with items", Pair("a", "b")),
            ("empty namedtuple", Nothing()),
            ("deque non-empty", collections.deque(["src/x.py"])),
            ("deque empty", collections.deque()),
        ):
            with self.subTest(case=case):
                self.assert_refused(self.good(), PASSED, unresolved=bad)

    def test_exact_type_rule_is_what_decides(self):
        # The rule is documented as exactly ``type(unresolved) in (tuple, list, set, frozenset)``.
        self.assertIn("type(unresolved) in (tuple, list, set, frozenset)", output.approve_patch.__doc__)
        self.assertIn("BEHAVIOR CHANGE", output.approve_patch.__doc__)

    def test_not_found_items_do_not_block(self):
        report = ValidationReport(results=PASSED.results, not_found=(NotFoundItem("consistency", "Not Found: consistency is not computed in v1"),))
        approve_patch(self.good(), report, str(self.root), (), redact)

    def test_bad_argument_types_and_forged_content(self):
        with self.assertRaises(UnexpectedStageError):
            approve_patch("text", PASSED, str(self.root), (), redact)
        with self.assertRaises(UnexpectedStageError):
            approve_patch(self.good(), PASSED, "", (), redact)
        with self.assertRaises(UnexpectedStageError):
            output.ApprovedPatch("x", str(self.root))
        for bad in ("text", b"text", None, self.good()):
            with self.assertRaises(UnexpectedStageError):
                publish_patch(bad)
        self.assertEqual(os.listdir(self.work), [])

    def test_real_validator_output_is_accepted(self):
        change = make_change()
        rendered = render_patch([change], redact)
        report = validation.validate_content({change.path: change.proposed}, root=str(self.root), added_lines=rendered.added_lines)
        self.assertTrue(report.passed, report.results)
        approve_patch(rendered, report, str(self.root), (), redact)


# ---------------------------------------------------------------- destination, publish
class FixedDestinationTests(WorkCase):
    def test_publish_takes_no_destination_argument(self):
        self.assertEqual(list(inspect.signature(publish_patch).parameters), ["content"])
        self.assertEqual(list(inspect.signature(check_no_existing_patch).parameters), [])
        self.assertEqual(list(inspect.signature(rollback_patch).parameters), ["token"])
        for name in output.__all__:
            obj = getattr(output, name)
            if callable(obj) and not inspect.isclass(obj):
                for param in inspect.signature(obj).parameters:
                    self.assertNotRegex(param, r"(?i)dest|out(put)?_?(path|dir|file)|path$")

    def test_run_writes_only_the_fixed_file_and_documents_are_untouched(self):
        self.assertNotEqual(self.work, self.root)
        content = self.approved()
        check_no_existing_patch()
        token = publish_patch(content)
        self.assertEqual(sorted(os.listdir(self.work)), ["output"])
        self.assertEqual(os.listdir(self.work / "output"), ["docsync.patch"])
        data = (self.work / "output" / "docsync.patch").read_bytes()
        self.assertEqual(data.decode("utf-8"), content.text)
        self.assertEqual((token.size, token.sha256), (len(data), sha(data)))
        self.assertEqual(token.path, os.path.join(os.path.realpath(self.work), "output", "docsync.patch"))
        self.assert_repo_untouched()
        self.assertTrue(self.before["README.md"])
        self.assertFalse([f for f in os.listdir(self.root / "docs") if f != "api.md"])
        self.assertTrue(rollback_patch(token))
        self.assertEqual(os.listdir(self.work / "output"), [])

    def test_output_is_created_only_when_missing(self):
        content = self.approved()
        token = publish_patch(content)
        self.assertTrue(rollback_patch(token))
        marker = self.work / "output" / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        publish_patch(content)
        self.assertEqual(sorted(os.listdir(self.work / "output")), ["docsync.patch", "keep.txt"])
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_empty_edits_produce_no_file(self):
        with self.assertRaises(UnexpectedStageError):
            approve_patch(render_patch([], redact), PASSED, str(self.root), (), redact)
        self.assertEqual(os.listdir(self.work), [])

    def test_gitignore_is_never_edited(self):
        publish_patch(self.approved())
        self.assert_repo_untouched()


class GuardTests(WorkCase):
    def assert_refused(self, content, expect=None):
        with self.assertRaises(PatchWriteError) as ctx:
            publish_patch(content)
        self.assertEqual(ctx.exception.exit_code, ExitCode.PATCH_WRITE)
        if expect:
            self.assertIn(expect, str(ctx.exception))
        self.assertIn("docsync.patch", str(ctx.exception))
        return ctx.exception

    def test_cwd_inside_docs_is_refused(self):
        content = self.approved()
        with chdir(self.root / "docs"):
            err = self.assert_refused(content, "README.md or inside docs/")
            self.assertIn(os.path.realpath(self.root / "docs"), str(err))
        self.assertFalse((self.root / "docs" / "output").exists())
        self.assert_repo_untouched()

    def test_cwd_in_nested_docs_dir_is_refused(self):
        nested = self.root / "docs" / "sub"
        nested.mkdir()
        before = snapshot(self.root)
        content = self.approved()
        with chdir(nested):
            self.assert_refused(content)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((nested / "output").exists())

    @unittest.skipUnless(os.name == "nt", "case-insensitive comparison is a Windows rule")
    def test_case_variants_are_refused_on_windows(self):
        content = approved_for(str(self.root).upper())
        with chdir(self.root / "docs"):
            self.assert_refused(content)
        content = approved_for(self.root)
        upper = str(self.root / "docs").upper()
        with chdir(upper):
            self.assert_refused(content)
        self.assert_repo_untouched()

    LINK_REFUSAL = "symbolic link, junction or reparse point"

    def test_output_junction_to_docs_is_refused(self):
        link = self.work / "output"
        make_junction(self.root / "docs", link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        # Policy B (Attempt 5): refused earlier, as a link, before the docs comparison runs.
        self.assert_refused(self.approved(), self.LINK_REFUSAL)
        self.assert_repo_untouched()

    def test_output_symlink_to_docs_is_refused(self):
        if not SYMLINKS:
            self.skipTest(SYMLINK_SKIP)
        link = self.work / "output"
        os.symlink(self.root / "docs", link, target_is_directory=True)
        self.assert_refused(self.approved(), self.LINK_REFUSAL)
        self.assert_repo_untouched()

    def test_output_junction_elsewhere_is_refused_and_nothing_is_written(self):
        # Policy B: this test used to assert that the junction was FOLLOWED.
        elsewhere = self.work / "elsewhere"
        elsewhere.mkdir()
        link = self.work / "output"
        make_junction(elsewhere, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        err = self.assert_refused(self.approved(), self.LINK_REFUSAL)
        self.assertEqual(err.exit_code, 11)
        self.assertIn(str(link), str(err))
        self.assertEqual(os.listdir(elsewhere), [])
        self.assertEqual(sorted(os.listdir(self.work)), ["elsewhere", "output"])
        self.assert_repo_untouched()

    def test_output_that_is_a_regular_file_is_refused(self):
        (self.work / "output").write_bytes(b"i am a file")
        self.assert_refused(self.approved(), "not a directory")
        self.assertEqual((self.work / "output").read_bytes(), b"i am a file")
        self.assert_repo_untouched()

    def test_repo_root_writes(self):
        content = self.approved()
        with chdir(self.root):
            token = publish_patch(content)
            self.assertTrue(os.path.isfile(self.root / "output" / "docsync.patch"))
            self.assertTrue(rollback_patch(token))

    def test_src_subdirectory_creates_only_src_output(self):
        content = self.approved()
        with chdir(self.root / "src"):
            publish_patch(content)
        after = snapshot(self.root)
        new = set(after) - set(self.before)
        self.assertEqual(new, {"src/output/docsync.patch"})
        for name, digest in self.before.items():
            self.assertEqual(after[name], digest, name)

    def test_unc_paths_are_refused_before_any_resolution(self):
        for repo in ("\\\\server\\share\\repo", "//server/share/repo"):
            with self.subTest(repo=repo), mock.patch("os.path.realpath", side_effect=AssertionError("resolved")):
                content = approve_patch(render_patch([make_change()], redact), PASSED, repo, (), redact)
                self.assert_refused(content, "UNC")
        self.assertEqual(os.listdir(self.work), [])
        self.assertTrue(output._is_unc("\\\\?\\UNC\\s\\x"))
        self.assertFalse(output._is_unc("\\\\?\\C:\\x"))


class OutputLinkPolicyTests(WorkCase):
    """Policy B (Attempt 5): an ``output`` that is a symlink, junction or other reparse point is
    refused with exit 11 before ``output`` is resolved; links in the working directory or an
    ancestor are still followed."""

    REFUSAL = "symbolic link, junction or reparse point"

    def other_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def out_path(self):
        return os.path.join(os.getcwd(), "output")

    def is_out(self, path):
        try:
            return os.path.normcase(os.fspath(path)) == os.path.normcase(self.out_path())
        except TypeError:
            return False

    def assert_publish_refused(self, content=None):
        with self.assertRaises(PatchWriteError) as ctx:
            publish_patch(content or self.approved())
        self.assertEqual(ctx.exception.exit_code, ExitCode.PATCH_WRITE)
        self.assertIn(self.REFUSAL, str(ctx.exception))
        self.assertIn("docsync.patch", str(ctx.exception))
        self.assertIn(self.out_path(), str(ctx.exception))
        return ctx.exception

    def assert_precheck_refused(self):
        with self.assertRaises(PatchWriteError) as ctx:
            check_no_existing_patch()
        self.assertEqual(ctx.exception.exit_code, ExitCode.PATCH_WRITE)
        self.assertIn(self.REFUSAL, str(ctx.exception))
        self.assertIn(self.out_path(), str(ctx.exception))

    def test_junction_to_a_non_docs_directory_elsewhere_is_refused_and_target_unchanged(self):
        target = self.other_dir() / "not-docs"
        target.mkdir()
        (target / "keep.txt").write_bytes(b"KEEP")
        before = (sorted(os.listdir(target)), (target / "keep.txt").read_bytes())
        link = self.work / "output"
        make_junction(target, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        content = self.approved()
        self.assert_precheck_refused()
        self.assert_publish_refused(content)
        self.assertEqual((sorted(os.listdir(target)), (target / "keep.txt").read_bytes()), before)
        self.assertEqual(os.listdir(self.work), ["output"])
        self.assert_repo_untouched()

    def test_junction_to_a_non_existent_target_is_refused(self):
        target = self.other_dir() / "will-vanish"
        target.mkdir()
        link = self.work / "output"
        make_junction(target, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        target.rmdir()  # the junction now dangles
        self.assertFalse(os.path.exists(link))
        self.assertTrue(os.path.lexists(link))
        content = self.approved()
        self.assert_precheck_refused()
        self.assert_publish_refused(content)
        self.assertFalse(target.exists())  # nothing was created at the missing target
        self.assertEqual(os.listdir(target.parent), [])

    def test_symlink_to_a_non_docs_directory_elsewhere_is_refused_and_target_unchanged(self):
        if not SYMLINKS:
            self.skipTest(SYMLINK_SKIP)
        target = self.other_dir() / "not-docs"
        target.mkdir()
        (target / "keep.txt").write_bytes(b"KEEP")
        os.symlink(target, self.work / "output", target_is_directory=True)
        content = self.approved()
        self.assert_precheck_refused()
        self.assert_publish_refused(content)
        self.assertEqual(sorted(os.listdir(target)), ["keep.txt"])

    def test_dangling_symlink_and_symlink_to_a_non_existent_target_are_refused(self):
        if not SYMLINKS:
            self.skipTest(SYMLINK_SKIP)
        missing = self.other_dir() / "missing"
        os.symlink(missing, self.work / "output", target_is_directory=True)
        content = self.approved()
        self.assert_precheck_refused()
        self.assert_publish_refused(content)
        self.assertFalse(missing.exists())

    def reparse_lstat(self):
        real = os.lstat
        fake = types.SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o777, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT | 0x10,
            st_dev=1, st_ino=2, st_size=0,
        )

        def lstat(path, *a, **k):
            return fake if self.is_out(path) else real(path, *a, **k)

        return mock.patch("docsync.output.os.lstat", lstat)

    def test_simulated_reparse_point_at_output_is_refused_by_lstat_attribute(self):
        content = self.approved()
        with self.reparse_lstat():
            self.assert_precheck_refused()
            self.assert_publish_refused(content)
        self.assertEqual(os.listdir(self.work), [])
        self.assert_repo_untouched()

    def test_simulated_symlink_mode_at_output_is_refused_by_lstat_mode(self):
        content = self.approved()
        real = os.lstat
        fake = types.SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0, st_dev=1, st_ino=2, st_size=0)
        with mock.patch("docsync.output.os.lstat", lambda p, *a, **k: fake if self.is_out(p) else real(p, *a, **k)):
            self.assert_precheck_refused()
            self.assert_publish_refused(content)
        self.assertEqual(os.listdir(self.work), [])

    def test_simulated_islink_at_output_is_refused(self):
        content = self.approved()
        real = os.path.islink
        with mock.patch("docsync.output.os.path.islink", lambda p: True if self.is_out(p) else real(p)):
            self.assert_precheck_refused()
            self.assert_publish_refused(content)
        self.assertEqual(os.listdir(self.work), [])

    def test_simulated_isjunction_at_output_is_refused(self):
        content = self.approved()
        real = os.path.isjunction
        with mock.patch("docsync.output.os.path.isjunction", lambda p: True if self.is_out(p) else real(p)):
            self.assert_precheck_refused()
            self.assert_publish_refused(content)
        self.assertEqual(os.listdir(self.work), [])

    def test_realpath_of_output_is_not_called_when_output_is_a_link(self):
        content = self.approved()
        calls = []

        def spy(path, *a, **k):
            calls.append(os.fspath(path))
            raise AssertionError("realpath must not be called when output is a link")

        with self.reparse_lstat(), mock.patch("docsync.output.os.path.realpath", spy):
            self.assert_precheck_refused()
            self.assert_publish_refused(content)
        self.assertEqual(calls, [])

    def test_realpath_is_never_called_on_output_itself_when_it_is_a_real_directory(self):
        content = self.approved()
        out = self.work / "output"
        out.mkdir()
        seen = []
        real = os.path.realpath

        def spy(path, *a, **k):
            seen.append(os.path.normcase(os.fspath(path)))
            return real(path, *a, **k)

        with mock.patch("docsync.output.os.path.realpath", spy):
            token = publish_patch(content)
        self.assertNotIn(os.path.normcase(str(out)), seen)
        self.assertTrue(rollback_patch(token))

    def test_junction_at_output_is_refused_without_resolving_it(self):
        target = self.other_dir() / "t"
        target.mkdir()
        link = self.work / "output"
        make_junction(target, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        content = self.approved()
        with mock.patch("docsync.output.os.path.realpath", side_effect=AssertionError("resolved")):
            self.assert_precheck_refused()
            self.assert_publish_refused(content)
        self.assertEqual(os.listdir(target), [])

    def test_missing_output_is_still_created(self):
        content = self.approved()
        check_no_existing_patch()
        token = publish_patch(content)
        self.assertTrue(os.path.isfile(self.work / "output" / "docsync.patch"))
        self.assertTrue(rollback_patch(token))

    def test_link_swapped_in_for_output_between_guard_and_open_is_refused_before_os_open(self):
        out = self.work / "output"
        out.mkdir()
        content = self.approved()
        real_guard = output._guard
        real = os.lstat
        armed = []
        fake = types.SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o777, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            st_dev=1, st_ino=2, st_size=0,
        )

        def guard(repo):
            result = real_guard(repo)
            armed.append(True)  # from here on "output" looks like a reparse point
            return result

        def lstat(path, *a, **k):
            return fake if armed and self.is_out(path) else real(path, *a, **k)

        with mock.patch("docsync.output._guard", guard), mock.patch("docsync.output.os.lstat", lstat), \
                mock.patch("docsync.output.os.open", side_effect=AssertionError("os.open must not be called")):
            self.assert_publish_refused(content)
        self.assertEqual(os.listdir(out), [])

    def test_junction_as_the_working_directory_is_still_resolved(self):
        real_work = self.other_dir() / "real-work"
        real_work.mkdir()
        link = self.work / "cwd-link"
        make_junction(real_work, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        content = self.approved()
        with chdir(link):
            token = publish_patch(content)
            self.assertEqual(token.path, os.path.join(os.path.realpath(real_work), "output", "docsync.patch"))
            self.assertTrue(rollback_patch(token))
        self.assertEqual(os.listdir(real_work), ["output"])
        self.assertEqual(os.listdir(real_work / "output"), [])

    def test_junction_as_an_ancestor_of_the_working_directory_is_still_resolved(self):
        real_parent = self.other_dir() / "real-parent"
        (real_parent / "sub").mkdir(parents=True)
        link = self.work / "ancestor-link"
        make_junction(real_parent, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        content = self.approved()
        with chdir(link / "sub"):
            token = publish_patch(content)
            self.assertEqual(token.path, os.path.join(os.path.realpath(real_parent), "sub", "output", "docsync.patch"))
            self.assertTrue(rollback_patch(token))

    def test_junction_working_directory_into_docs_is_still_protected(self):
        link = self.work / "to-docs"
        make_junction(self.root / "docs", link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        content = self.approved()
        with chdir(link):
            with self.assertRaises(PatchWriteError) as ctx:
                publish_patch(content)
        self.assertIn("README.md or inside docs/", str(ctx.exception))
        self.assertEqual(ctx.exception.exit_code, 11)
        self.assert_repo_untouched()

    def test_symlink_working_directory_is_still_resolved(self):
        if not SYMLINKS:
            self.skipTest(SYMLINK_SKIP)
        real_work = self.other_dir() / "real-work"
        real_work.mkdir()
        link = self.work / "cwd-link"
        os.symlink(real_work, link, target_is_directory=True)
        content = self.approved()
        with chdir(link):
            token = publish_patch(content)
            self.assertTrue(rollback_patch(token))
        self.assertEqual(os.listdir(real_work), ["output"])

    def test_link_target_of_a_chain_is_not_resolved(self):
        victim = self.other_dir() / "victim.txt"
        victim.write_bytes(b"V")
        real_is_link = output._is_link_like
        with mock.patch("docsync.output.os.readlink", return_value=str(victim)), \
                mock.patch("docsync.output._is_link_like", lambda p: True if os.path.normcase(str(p)) == os.path.normcase(str(victim)) else real_is_link(p)), \
                mock.patch("docsync.output.os.path.realpath", side_effect=AssertionError("resolved")):
            self.assertEqual(output._link_target(str(self.work / "x")), os.path.normpath(str(victim)))
        self.assertEqual(victim.read_bytes(), b"V")


class ExistingPatchTests(WorkCase):
    def test_precheck_passes_when_nothing_exists(self):
        check_no_existing_patch()
        (self.work / "output").mkdir()
        check_no_existing_patch()

    def test_existing_file_is_refused_unchanged(self):
        out = self.work / "output"
        out.mkdir()
        target = out / "docsync.patch"
        target.write_bytes(b"OLD")
        with self.assertRaises(PatchWriteError) as ctx:
            check_no_existing_patch()
        self.assertEqual(ctx.exception.exit_code, 11)
        self.assertIn("docsync.patch", str(ctx.exception))
        with self.assertRaises(PatchWriteError):
            publish_patch(self.approved())
        self.assertEqual(sha(target.read_bytes()), sha(b"OLD"))
        self.assert_repo_untouched()

    def test_file_created_between_precheck_and_write_is_not_overwritten(self):
        content = self.approved()
        check_no_existing_patch()
        (self.work / "output").mkdir()
        target = self.work / "output" / "docsync.patch"
        target.write_bytes(b"RACED")
        with self.assertRaises(PatchWriteError) as ctx:
            publish_patch(content)
        self.assertEqual(ctx.exception.exit_code, 11)
        self.assertEqual(target.read_bytes(), b"RACED")

    def test_directory_at_destination_is_refused_and_left(self):
        target = self.work / "output" / "docsync.patch"
        target.mkdir(parents=True)
        (target / "inner.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(PatchWriteError):
            check_no_existing_patch()
        with self.assertRaises(PatchWriteError):
            publish_patch(self.approved())
        self.assertEqual(os.listdir(target), ["inner.txt"])

    def test_junction_at_destination_counts_as_existing_and_target_is_untouched(self):
        victim = self.work / "victim"
        victim.mkdir()
        (victim / "f.txt").write_text("x", encoding="utf-8")
        (self.work / "output").mkdir()
        link = self.work / "output" / "docsync.patch"
        make_junction(victim, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        with self.assertRaises(PatchWriteError):
            check_no_existing_patch()
        with self.assertRaises(PatchWriteError):
            publish_patch(self.approved())
        self.assertEqual(os.listdir(victim), ["f.txt"])

    def test_dangling_symlink_counts_as_existing(self):
        if not SYMLINKS:
            self.skipTest(SYMLINK_SKIP)
        (self.work / "output").mkdir()
        target = self.root / "docs" / "new-target.md"
        os.symlink(target, self.work / "output" / "docsync.patch")
        with self.assertRaises(PatchWriteError) as ctx:
            check_no_existing_patch()
        self.assertEqual(ctx.exception.exit_code, 11)
        with self.assertRaises(PatchWriteError):
            publish_patch(self.approved())
        self.assertFalse(target.exists())
        self.assert_repo_untouched()

    def test_dangling_symlink_appearing_between_precheck_and_write(self):
        if not SYMLINKS:
            self.skipTest(SYMLINK_SKIP)
        content = self.approved()
        check_no_existing_patch()
        (self.work / "output").mkdir()
        target = self.root / "README.md"
        missing = self.root / "docs" / "missing.md"
        os.symlink(missing, self.work / "output" / "docsync.patch")
        with self.assertRaises(PatchWriteError):
            publish_patch(content)
        self.assertFalse(missing.exists())
        self.assert_repo_untouched()
        self.assertTrue(target.exists())


class RollbackAndErrorTests(WorkCase):
    def test_rollback_removes_its_own_file(self):
        token = publish_patch(self.approved())
        self.assertIsInstance(token, PatchToken)
        self.assertTrue(rollback_patch(token))
        self.assertFalse(os.path.lexists(token.path))
        self.assertFalse(rollback_patch(token))  # already gone: nothing to do

    def test_rollback_does_not_delete_a_replacement_with_different_content(self):
        token = publish_patch(self.approved())
        dest = Path(token.path)
        dest.unlink()
        dest.write_bytes(b"someone else's file")
        self.assertFalse(rollback_patch(token))
        self.assertEqual(dest.read_bytes(), b"someone else's file")

    def test_rollback_does_not_delete_same_content_under_a_new_identity(self):
        content = self.approved()
        token = publish_patch(content)
        dest = Path(token.path)
        data = dest.read_bytes()
        tmp = dest.with_name("replacement.tmp")
        tmp.write_bytes(data)  # created while the original still exists: a different identity
        os.replace(tmp, dest)
        if (os.stat(dest).st_dev, os.stat(dest).st_ino) == (token.device, token.file_index):
            self.skipTest("file system reused the file identity")
        self.assertFalse(rollback_patch(token))
        self.assertEqual(dest.read_bytes(), data)

    def test_rollback_leaves_a_modified_file_alone(self):
        token = publish_patch(self.approved())
        dest = Path(token.path)
        with open(dest, "r+b") as f:
            f.write(b"X")  # same size, same identity, different hash
        self.assertFalse(rollback_patch(token))
        self.assertTrue(dest.exists())
        with open(dest, "ab") as f:
            f.write(b"more")  # different size
        self.assertFalse(rollback_patch(token))

    def test_rollback_with_the_file_held_open_raises_a_reportable_error(self):
        if os.name != "nt":
            self.skipTest("an open file can be deleted on POSIX; the held-open failure is a Windows case")
        token = publish_patch(self.approved())
        with open(token.path, "rb"):
            with self.assertRaises(output.RollbackError) as ctx:
                rollback_patch(token)
        self.assertEqual(ctx.exception.path, token.path)
        self.assertIn(token.path, str(ctx.exception))
        self.assertEqual(ctx.exception.exit_code, ExitCode.UNEXPECTED)
        self.assertTrue(os.path.exists(token.path))
        self.assertTrue(rollback_patch(token))

    def test_rollback_refuses_a_non_token_and_ignores_non_regular_paths(self):
        with self.assertRaises(UnexpectedStageError):
            rollback_patch("output/docsync.patch")
        path = self.work / "output" / "docsync.patch"
        path.mkdir(parents=True)
        token = PatchToken(0, 0, 0, sha(b""), str(path))
        self.assertFalse(rollback_patch(token))
        self.assertTrue(path.is_dir())

    def test_rollback_does_not_follow_a_symlink(self):
        if not SYMLINKS:
            self.skipTest(SYMLINK_SKIP)
        token = publish_patch(self.approved())
        dest = Path(token.path)
        saved = dest.read_bytes()
        other = self.work / "other.txt"
        other.write_bytes(saved)
        dest.unlink()
        os.symlink(other, dest)
        self.assertFalse(rollback_patch(token))
        self.assertEqual(other.read_bytes(), saved)

    def test_write_error_removes_partial_file_and_exits_11(self):
        content = self.approved()
        with mock.patch("docsync.output.os.fsync", side_effect=OSError(errno.ENOSPC, "No space left")):
            with self.assertRaises(PatchWriteError) as ctx:
                publish_patch(content)
        self.assertEqual(ctx.exception.exit_code, ExitCode.PATCH_WRITE)
        self.assertFalse(os.path.lexists(self.work / "output" / "docsync.patch"))
        self.assert_repo_untouched()

    def test_write_error_in_write_call_exits_11(self):
        content = self.approved()
        real = os.fdopen

        class Failing:
            def __init__(self, handle):
                self.handle = handle

            def write(self, data):
                raise OSError(errno.ENOSPC, "No space left")

            def __getattr__(self, name):
                return getattr(self.handle, name)

        with mock.patch("docsync.output.os.fdopen", lambda fd, mode: Failing(real(fd, mode))):
            with self.assertRaises(PatchWriteError):
                publish_patch(content)
        self.assertFalse(os.path.lexists(self.work / "output" / "docsync.patch"))

    def test_other_exception_removes_partial_file_and_propagates(self):
        content = self.approved()
        with mock.patch("docsync.output.os.fsync", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                publish_patch(content)
        self.assertFalse(os.path.lexists(self.work / "output" / "docsync.patch"))

    def test_failed_publish_removes_only_a_file_with_its_own_identity(self):
        # If the path no longer holds the file this call created (identity differs), cleanup
        # leaves it alone. Simulated by making the identity read from the open file differ.
        content = self.approved()
        real = os.fstat

        class Fake:
            def __init__(self, st):
                self.st_dev, self.st_ino = st.st_dev + 1, st.st_ino + 1

        with mock.patch("docsync.output.os.fstat", lambda fd: Fake(real(fd))):
            with mock.patch("docsync.output.os.fsync", side_effect=OSError(errno.ENOSPC, "No space left")):
                with self.assertRaises(PatchWriteError) as ctx:
                    publish_patch(content)
        self.assertIn("left untouched", str(ctx.exception))
        self.assertTrue(os.path.isfile(self.work / "output" / "docsync.patch"))

    def test_guard_failure_after_creation_removes_the_new_file(self):
        content = self.approved()
        real_guard = output._guard
        calls = []

        def guard(repo):
            calls.append(1)
            if len(calls) == 3:  # the re-check after the file was written
                raise PatchWriteError("output", "destination moved")
            return real_guard(repo)

        with mock.patch("docsync.output._guard", guard):
            with self.assertRaises(PatchWriteError):
                publish_patch(content)
        self.assertFalse(os.path.lexists(self.work / "output" / "docsync.patch"))

    def test_errors_carry_no_document_content(self):
        content = self.approved()
        with mock.patch("docsync.output.os.fsync", side_effect=OSError(errno.ENOSPC, "No space left")):
            with self.assertRaises(PatchWriteError) as ctx:
                publish_patch(content)
        self.assertNotIn("behavior changed", str(ctx.exception))
        self.assertNotIn("behavior changed", repr(content))


# ---------------------------------------------------------------- Attempt 2 additions
def make_secret_free_rendered(change=None):
    return render_patch([change or make_change()], redact)


class NoOpRedactor:
    """A redactor that finds nothing: the documented limitation of an injected redactor."""

    def contains_secret(self, text):
        return False

    def secret_line_numbers(self, text):
        return []


BEGIN_LINE = "-----BEGIN RSA PRIVATE KEY-----"
END_LINE = "-----END RSA PRIVATE KEY-----"
PEM_BODY = ["FAKEPEMBODYLINE%02d" % i for i in range(50)]


def long_doc(lines):
    return "\n".join(lines) + "\n"


class SplitPemTests(unittest.TestCase):
    """M4: a PEM block that starts in one hunk and continues in another is withheld whole,
    judged at the writer level over the full document text."""

    HEAD = ["line%d" % i for i in range(1, 10)]
    TAIL = ["tail%d" % i for i in range(20)]

    def edit(self, lines, index, value):
        lines = list(lines)
        lines[index] = value
        return lines

    def test_block_split_across_two_hunks_is_withheld_in_both(self):
        orig = self.HEAD + [BEGIN_LINE] + PEM_BODY + [END_LINE] + self.TAIL  # BEGIN is line 10
        prop = self.edit(orig, 7, "LINE8")  # hunk 1 holds BEGIN and the first body lines
        prop = self.edit(prop, 40, "FAKEPEMBODYCHANGED")  # hunk 2 holds body lines only
        change = DocumentChange("docs/api.md", long_doc(orig), long_doc(prop))
        for redactor in (redact, NoOpRedactor()):
            with self.subTest(redactor=type(redactor).__name__):
                r = render_patch([change], redactor)
                self.assertEqual(len(r.hunks), 2)
                self.assertEqual([h.withheld for h in r.hunks], [True, True])
                self.assertEqual(r.text, "")
                self.assertEqual(r.withheld, (WithheldFinding("docs/api.md", 10),))
                self.assertNotIn("FAKEPEMBODY", repr(r))
        # hunk 2 alone holds no pattern the redactor knows: the writer-level rule caught it
        self.assertFalse(redact.contains_secret("\n".join(prop[37:44])))

    def test_unterminated_block_in_the_proposed_document_runs_to_the_end(self):
        orig = self.HEAD + PEM_BODY + self.TAIL
        prop = self.HEAD + [BEGIN_LINE] + PEM_BODY + self.TAIL  # BEGIN added, END missing
        prop = self.edit(prop, 40, "FAKEPEMBODYCHANGED")
        change = DocumentChange("docs/api.md", long_doc(orig), long_doc(prop))
        r = render_patch([change], NoOpRedactor())
        self.assertEqual([h.withheld for h in r.hunks], [True, True])
        self.assertEqual(r.withheld, (WithheldFinding("docs/api.md", 10),))

    def test_block_removed_is_reported_at_its_begin_line(self):
        orig = self.HEAD + [BEGIN_LINE] + PEM_BODY + [END_LINE] + self.TAIL
        prop = self.HEAD + ["x1", "x2"] + self.TAIL  # whole block deleted
        r = render_patch([DocumentChange("docs/api.md", long_doc(orig), long_doc(prop))], NoOpRedactor())
        self.assertTrue(r.has_withheld)
        self.assertEqual(r.withheld, (WithheldFinding("docs/api.md", 10),))

    def test_changes_outside_the_block_and_public_keys_are_not_withheld(self):
        block = [BEGIN_LINE, "FAKEBODYA", END_LINE]
        orig = self.HEAD + block + ["m%d" % i for i in range(40)]
        prop = self.edit(orig, 8 + 3 + 30, "CHANGED")  # far below the block
        r = render_patch([DocumentChange("docs/api.md", long_doc(orig), long_doc(prop))], NoOpRedactor())
        self.assertFalse(r.has_withheld)
        pub = ["-----BEGIN PUBLIC KEY-----", "FAKEPUBLIC", "-----END PUBLIC KEY-----"]
        orig2 = self.HEAD + pub + self.TAIL
        r2 = render_patch([DocumentChange("docs/api.md", long_doc(orig2), long_doc(self.edit(orig2, 10, "CHANGED")))], redact)
        self.assertFalse(r2.has_withheld)

    def test_hostile_begin_lines_are_scanned_in_linear_time(self):
        hostile = "-----BEGIN " * 20000 + "\n" + "-----BEGIN A B C " * 5000 + "\n"
        start = time.perf_counter()
        render_patch([DocumentChange("docs/a.md", "x\n", hostile)], NoOpRedactor())
        self.assertLess(time.perf_counter() - start, 5.0)


class LineNumberSemanticsTests(unittest.TestCase):
    def test_removed_lines_use_original_numbers_and_added_lines_use_proposed_numbers(self):
        secret = "client_secret=FAKESECRETVALUE9876"
        orig = ["a", "b", secret, "c", "d", "e"]
        prop = ["x1", "x2", "a", "b", "c", "d", "e"]
        r = render_patch([DocumentChange("docs/a.md", long_doc(orig), long_doc(prop))], redact)
        self.assertEqual(r.withheld, (WithheldFinding("docs/a.md", 3),))  # original number (proposed would be 5)
        prop2 = ["x1", "x2", "a", "b", secret, "c", "d", "e"]
        r2 = render_patch([DocumentChange("docs/a.md", long_doc(["a", "b", "c", "d", "e"]), long_doc(prop2))], redact)
        self.assertEqual(r2.withheld, (WithheldFinding("docs/a.md", 5),))  # proposed number


class SealTests(WorkCase):
    """M2, M5: approve_patch does not trust a caller-built or altered RenderedPatch."""

    def good(self):
        return make_secret_free_rendered()

    def assert_refused(self, rendered, redactor=redact):
        with self.assertRaises(UnexpectedStageError) as ctx:
            approve_patch(rendered, PASSED, str(self.root), (), redactor)
        self.assertEqual(ctx.exception.exit_code, ExitCode.UNEXPECTED)
        self.assertEqual(os.listdir(self.work), [])
        return ctx.exception

    def test_unresolved_and_redactor_are_required(self):
        params = inspect.signature(approve_patch).parameters
        self.assertEqual(list(params), ["rendered", "validation", "repository", "unresolved", "redactor"])
        for name in ("unresolved", "redactor"):
            self.assertIs(params[name].default, inspect.Parameter.empty)
        with self.assertRaises(TypeError):
            approve_patch(self.good(), PASSED, str(self.root), redactor=redact)  # no unresolved
        with self.assertRaises(TypeError):
            approve_patch(self.good(), PASSED, str(self.root), ())  # no redactor
        with self.assertRaises(UnexpectedStageError):
            approve_patch(self.good(), PASSED, str(self.root), (), object())
        with self.assertRaises(UnexpectedStageError):
            approve_patch(self.good(), PASSED, str(self.root), None, redact)

    def test_hand_built_rendered_patch_with_a_secret_is_refused(self):
        secret_line = "+password = \"FakePassw0rdNotReal\"\n"
        hunk = output.Hunk("docs/api.md", 1, 1, 1, 2, ("@@ -1,1 +1,2 @@\n", " # API\n", secret_line), (2,))
        text = "--- a/docs/api.md\n+++ b/docs/api.md\n" + "".join(hunk.lines)
        forged = output.RenderedPatch((hunk,), (), text)
        err = self.assert_refused(forged)
        self.assertNotIn("FakePassw0rd", str(err))
        # even a forged object with no secret is refused: it lacks the seal
        clean = output.Hunk("docs/api.md", 1, 1, 1, 2, ("@@ -1,1 +1,2 @@\n", " # API\n", "+hello\n"), (2,))
        self.assert_refused(output.RenderedPatch((clean,), (), "--- a/docs/api.md\n+++ b/docs/api.md\n" + "".join(clean.lines)))
        self.assert_refused(output.RenderedPatch())

    def test_altered_rendered_patch_is_refused(self):
        rendered = self.good()
        approve_patch(rendered, PASSED, str(self.root), (), redact)  # the original is fine
        self.assert_refused(dataclasses.replace(rendered, text=rendered.text + "+extra\n"))
        self.assert_refused(dataclasses.replace(rendered, text=rendered.text + "+password = \"FakePassw0rdNotReal\"\n"))
        self.assert_refused(dataclasses.replace(rendered, hunks=rendered.hunks[:0]))
        self.assert_refused(dataclasses.replace(rendered, withheld=(WithheldFinding("docs/api.md", 1),)))
        self.assert_refused(dataclasses.replace(rendered, hunks=list(rendered.hunks)))
        object.__setattr__(rendered, "text", "tampered")  # direct attribute tampering
        self.assert_refused(rendered)

    def test_text_that_does_not_match_the_hunks_is_refused_even_with_a_matching_digest(self):
        rendered = self.good()
        fake_digest = output._rendered_digest(rendered.hunks, rendered.withheld, "other text\n")
        forged = dataclasses.replace(rendered, text="other text\n", _digest=fake_digest)
        err = self.assert_refused(forged)
        self.assertIn("does not match", str(err))

    def test_secret_rendered_with_a_noop_redactor_is_caught_by_the_real_one(self):
        change = DocumentChange("docs/api.md", ORIG, ORIG + "client_secret=FAKESECRETVALUE9876\n")
        rendered = render_patch([change], NoOpRedactor())
        self.assertFalse(rendered.has_withheld)
        err = self.assert_refused(rendered, redact)
        self.assertNotIn("FAKESECRETVALUE9876", str(err))

    def test_noop_redactor_is_a_documented_limitation(self):
        # Documented in the module docstring: a deliberate caller can inject a no-op redactor,
        # and nothing then stops a secret. The defense is against accidents and forged objects.
        self.assertIn("no-op redactor", output.__doc__)
        change = DocumentChange("docs/api.md", ORIG, ORIG + "client_secret=FAKESECRETVALUE9876\n")
        rendered = render_patch([change], NoOpRedactor())
        approved = approve_patch(rendered, PASSED, str(self.root), (), NoOpRedactor())
        self.assertIn("FAKESECRETVALUE9876", approved.text)

    def test_new_secret_kinds_are_rechecked_in_hunk_lines(self):
        for kind in ("bearer", "jwt", "url", "passphrase"):
            with self.subTest(kind=kind):
                lines, _values = SECRETS[kind]
                change = DocumentChange("docs/api.md", ORIG, ORIG + "\n".join(lines) + "\n")
                self.assert_refused(render_patch([change], NoOpRedactor()))

    def test_copies_of_valid_objects_stay_valid_and_unchanged(self):
        rendered = self.good()
        for clone in (copy.copy(rendered), copy.deepcopy(rendered)):
            self.assertEqual(clone, rendered)
            approved = approve_patch(clone, PASSED, str(self.root), (), redact)
            self.assertEqual(approved.text, rendered.text)
        approved = approve_patch(rendered, PASSED, str(self.root), (), redact)
        for clone in (copy.copy(approved), copy.deepcopy(approved)):
            self.assertEqual(clone, approved)
            token = publish_patch(clone)
            self.assertTrue(rollback_patch(token))

    def test_altered_approved_patch_is_refused(self):
        approved = approve_patch(self.good(), PASSED, str(self.root), (), redact)
        with self.assertRaises(UnexpectedStageError):
            dataclasses.replace(approved, text="malicious\n")  # the seal no longer fits
        with self.assertRaises(UnexpectedStageError):
            dataclasses.replace(approved, repository=str(self.work))
        object.__setattr__(approved, "text", "malicious\n")  # tampering after construction
        with self.assertRaises(UnexpectedStageError) as ctx:
            publish_patch(approved)
        self.assertEqual(ctx.exception.exit_code, ExitCode.UNEXPECTED)
        self.assertEqual(os.listdir(self.work), [])
        with self.assertRaises(UnexpectedStageError):
            output.ApprovedPatch("x", str(self.root), "not-a-digest")
        with self.assertRaises(UnexpectedStageError):
            output.ApprovedPatch("x", str(self.root), object())


class RollbackRestrictionTests(WorkCase):
    """M3: the rollback only ever deletes a file at <dir>/output/docsync.patch."""

    def token_for(self, path, data=None):
        path = Path(path)
        st = os.stat(path)
        data = path.read_bytes() if data is None else data
        return PatchToken(st.st_dev, st.st_ino, len(data), sha(data), str(path))

    def test_forged_token_for_another_path_never_deletes(self):
        tracked = self.root / "docs" / "api.md"  # a tracked-looking file, size and hash known
        other = self.work / "notes.md"
        other.write_text("keep me\n", encoding="utf-8")
        (self.work / "output").mkdir()
        wrong_name = self.work / "output" / "docsync.patch.bak"
        wrong_name.write_bytes(b"keep me too")
        (self.work / "elsewhere").mkdir()
        wrong_dir = self.work / "elsewhere" / "docsync.patch"
        wrong_dir.write_bytes(b"keep me three")
        for target in (tracked, other, wrong_name, wrong_dir, self.root / "README.md"):
            with self.subTest(target=target.name):
                token = self.token_for(target)
                with self.assertRaises(UnexpectedStageError) as ctx:
                    rollback_patch(token)
                self.assertEqual(ctx.exception.exit_code, ExitCode.UNEXPECTED)
                self.assertTrue(target.exists())
        self.assert_repo_untouched()
        self.assertEqual(other.read_text(encoding="utf-8"), "keep me\n")

    def test_forged_token_with_unnormalized_or_relative_path_is_refused(self):
        token = publish_patch(self.approved())
        good = Path(token.path)
        for bad in (
            os.path.join(str(good.parent), "..", "output", "docsync.patch"),
            os.path.join("output", "docsync.patch"),
            "docsync.patch",
            str(good.parent) + os.sep + "." + os.sep + "docsync.patch",
            "\\\\server\\share\\output\\docsync.patch",
        ):
            with self.subTest(path=bad):
                forged = dataclasses.replace(token, path=bad)
                with self.assertRaises(UnexpectedStageError):
                    rollback_patch(forged)
                self.assertTrue(good.exists())
        self.assertTrue(rollback_patch(token))

    def test_output_path_with_mismatching_identity_size_or_hash_deletes_nothing(self):
        out = self.work / "output"
        out.mkdir()
        dest = out / "docsync.patch"
        dest.write_bytes(b"somebody else's patch")
        st = os.stat(dest)
        data = dest.read_bytes()
        good = (st.st_dev, st.st_ino, len(data), sha(data), str(dest))
        for label, changed in {
            "inode": (good[0], good[1] + 1) + good[2:],
            "device": (good[0] + 1,) + good[1:],
            "size": good[:2] + (len(data) + 1,) + good[3:],
            "hash": good[:3] + (sha(b"different"),) + good[4:],
        }.items():
            with self.subTest(mismatch=label):
                self.assertFalse(rollback_patch(PatchToken(*changed)))
                self.assertEqual(dest.read_bytes(), data)
        self.assertTrue(rollback_patch(PatchToken(*good)))  # and the matching one does delete

    def test_token_field_types_are_validated(self):
        path = str(self.work / "output" / "docsync.patch")
        digest = sha(b"x")
        for args in (("1", 0, 1, digest, path), (0, 1.5, 1, digest, path), (0, 0, True, digest, path),
                     (0, 0, 1, digest, 5), (0, 0, 1, digest, None), (None, 0, 1, digest, path)):
            with self.subTest(args=args), self.assertRaises(TypeError):
                PatchToken(*args)
        for args in ((0, 0, -1, digest, path), (0, 0, 1, "xyz", path), (0, 0, 1, digest.upper(), path), (0, 0, 1, 12, path)):
            with self.subTest(args=args), self.assertRaises((ValueError, TypeError)):
                PatchToken(*args)
        token = PatchToken(0, 0, 1, digest, path)
        object.__setattr__(token, "size", "1")  # tampered after construction
        with self.assertRaises(UnexpectedStageError):
            rollback_patch(token)

    def test_unusable_file_index_zero_is_never_deleted(self):
        token = publish_patch(self.approved())
        zero = dataclasses.replace(token, file_index=0)
        with self.assertRaises(output.RollbackError) as ctx:
            rollback_patch(zero)
        self.assertEqual(ctx.exception.path, token.path)
        self.assertTrue(os.path.exists(token.path))
        self.assertTrue(rollback_patch(token))

    def test_nothing_is_published_when_output_is_a_junction(self):
        # Policy B: the old test asserted that the token path stayed named "output" while the
        # junction was followed. A junction at "output" is now refused, so no token exists.
        elsewhere = self.work / "elsewhere"
        elsewhere.mkdir()
        link = self.work / "output"
        make_junction(elsewhere, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        with self.assertRaises(PatchWriteError) as ctx:
            publish_patch(self.approved())
        self.assertEqual(ctx.exception.exit_code, 11)
        self.assertEqual(os.listdir(elsewhere), [])


class DestinationRaceTests(WorkCase):
    """M1: refuse anything at the destination immediately before os.open; O_EXCL stays."""

    def no_open(self):
        return mock.patch("docsync.output.os.open", side_effect=AssertionError("os.open must not be called"))

    def other_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name).resolve()

    def test_link_appearing_between_guard_and_open_is_refused_before_os_open(self):
        out = self.work / "output"
        out.mkdir()
        content = self.approved()
        real_guard, real_lstat, real_lexists = output._guard, os.lstat, os.path.lexists
        armed, seen = [], []

        def guard(repo):
            result = real_guard(repo)
            armed[:] = [os.path.normcase(result[1])]  # from here on a link "appears" at the destination
            return result

        def is_dest(path):
            return bool(armed) and os.path.normcase(os.fspath(path)) == armed[0]

        link = types.SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0, st_dev=1, st_ino=2)
        reparse = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_file_attributes=0x400, st_dev=1, st_ino=2)

        def lstat_as(fake):
            def fake_lstat(path, *a, **k):
                if is_dest(path):
                    seen.append(path)
                    return fake
                return real_lstat(path, *a, **k)
            return fake_lstat

        def fake_lexists(path):
            return True if is_dest(path) else real_lexists(path)

        cases = {
            "symlink in lstat": [mock.patch("docsync.output.os.lstat", lstat_as(link))],
            "reparse point in lstat": [mock.patch("docsync.output.os.lstat", lstat_as(reparse))],
            "lexists": [mock.patch("docsync.output.os.path.lexists", fake_lexists)],
        }
        for name, patches in cases.items():
            with self.subTest(case=name):
                armed.clear()
                seen.clear()
                with contextlib.ExitStack() as stack:
                    stack.enter_context(mock.patch("docsync.output._guard", guard))
                    for p in patches:
                        stack.enter_context(p)
                    stack.enter_context(self.no_open())  # the real os.open must not be reached
                    with self.assertRaises(PatchWriteError) as ctx:
                        publish_patch(content)
                self.assertEqual(ctx.exception.exit_code, ExitCode.PATCH_WRITE)
                self.assertIn("docsync.patch", str(ctx.exception))
                self.assertIn("nothing was written", str(ctx.exception))
                self.assertEqual(os.listdir(out), [])
        # the lstat-based check itself ran (lexists reports False, lstat reports a link)
        armed.clear()
        seen.clear()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("docsync.output._guard", guard))
            stack.enter_context(mock.patch("docsync.output.os.lstat", lstat_as(link)))
            stack.enter_context(mock.patch("docsync.output.os.path.lexists", lambda p: False if is_dest(p) else real_lexists(p)))
            stack.enter_context(self.no_open())
            with self.assertRaises(PatchWriteError) as ctx:
                publish_patch(content)
        self.assertTrue(seen)
        self.assertIn("link or reparse point", str(ctx.exception))
        self.assertEqual(os.listdir(out), [])

    def test_junction_at_destination_pointing_outside_docs_is_refused_and_target_untouched(self):
        victim = self.other_dir() / "not-docs"
        victim.mkdir()
        (victim / "f.txt").write_text("x", encoding="utf-8")
        before = (sorted(os.listdir(victim)), (victim / "f.txt").read_bytes())
        out = self.work / "output"
        out.mkdir()
        link = out / "docsync.patch"
        make_junction(victim, link)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        content = self.approved()
        with self.no_open():
            with self.assertRaises(PatchWriteError) as ctx:
                publish_patch(content)
        self.assertEqual(ctx.exception.exit_code, ExitCode.PATCH_WRITE)
        self.assertIn("docsync.patch", str(ctx.exception))
        with self.assertRaises(PatchWriteError):
            check_no_existing_patch()
        self.assertEqual((sorted(os.listdir(victim)), (victim / "f.txt").read_bytes()), before)
        self.assert_repo_untouched()

    def test_dangling_symlink_to_a_non_docs_target_creates_nothing(self):
        if not SYMLINKS:
            self.skipTest(SYMLINK_SKIP)
        target = self.other_dir() / "created-through-link.txt"
        (self.work / "output").mkdir()
        os.symlink(target, self.work / "output" / "docsync.patch")
        content = self.approved()
        with self.assertRaises(PatchWriteError) as ctx:
            check_no_existing_patch()
        self.assertEqual(ctx.exception.exit_code, 11)
        with self.assertRaises(PatchWriteError):
            publish_patch(content)
        self.assertFalse(target.exists())
        self.assertEqual(os.listdir(target.parent), [])
        self.assert_repo_untouched()

    def stray_setup(self):
        stray = self.work / "stray.txt"
        real_open = os.open

        def follow_a_link(path, flags, mode=0o777):
            return real_open(str(stray), flags, mode)  # as if the open followed a link

        return stray, follow_a_link

    def test_file_created_through_a_followed_link_is_removed_and_reported(self):
        content = self.approved()
        stray, follow = self.stray_setup()
        with mock.patch("docsync.output.os.open", follow), mock.patch("docsync.output._link_target", return_value=str(stray)):
            with self.assertRaises(PatchWriteError) as ctx:
                publish_patch(content)
        self.assertEqual(ctx.exception.exit_code, ExitCode.PATCH_WRITE)
        self.assertIn("a link was followed", str(ctx.exception))
        self.assertIn(str(stray), str(ctx.exception))
        self.assertFalse(stray.exists())

    def test_stray_that_cannot_be_located_is_reported_not_hidden(self):
        content = self.approved()
        stray, follow = self.stray_setup()
        with mock.patch("docsync.output.os.open", follow), mock.patch("docsync.output._link_target", return_value=None):
            with self.assertRaises(PatchWriteError) as ctx:
                publish_patch(content)
        self.assertIn("by hand", str(ctx.exception))
        self.assertIn("docsync.patch", str(ctx.exception))
        self.assertTrue(stray.exists())  # honestly left and reported

    def test_file_index_zero_is_unsafe_for_cleanup(self):
        content = self.approved()
        real = os.fstat

        def zero_ino(fd):
            st = real(fd)
            return types.SimpleNamespace(st_dev=st.st_dev, st_ino=0)

        with mock.patch("docsync.output.os.fstat", zero_ino):
            with mock.patch("docsync.output.os.fsync", side_effect=OSError(errno.ENOSPC, "No space left")):
                with self.assertRaises(PatchWriteError) as ctx:
                    publish_patch(content)
        self.assertIn("could not be removed", str(ctx.exception))
        self.assertTrue(os.path.isfile(self.work / "output" / "docsync.patch"))  # not deleted on a weak identity
        (self.work / "output" / "docsync.patch").unlink()


class ModuleRuleTests(unittest.TestCase):
    def test_writer_imports_only_the_standard_library_and_contracts(self):
        tree = ast.parse(Path(output.__file__).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module)
        self.assertEqual(names, {"difflib", "hashlib", "os", "re", "stat", "dataclasses", "docsync.contracts"})

    def test_pattern_categories_are_all_detected_by_the_injected_redactor(self):
        for kind, (lines, values) in SECRETS.items():
            with self.subTest(kind=kind):
                self.assertTrue(redact.contains_secret("\n".join(lines)))


if __name__ == "__main__":
    unittest.main()
