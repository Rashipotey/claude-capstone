"""T14 tests: Reporter. Local fixtures only; fake secrets are built at runtime."""

import builtins
import io
import os
import socket
import sys
import unittest
from unittest import mock

from docsync import redact as redactor_module
from docsync.contracts import (
    CHECK_MARKDOWN_SYNTAX,
    CHECK_NON_EMPTY_OUTPUT,
    CHECK_RELATIVE_LINKS,
    CheckResult,
    CheckStatus,
    ExitCode,
    NotFoundItem,
    ProposedEdit,
    ValidationReport,
)
from docsync.report import (
    LIMITATIONS,
    MAX_FREE_TEXT,
    NAME_PLACEHOLDER,
    TRUNCATION_MARKER,
    CandidateGroup,
    NotAddressed,
    ReportInput,
    SkippedFile,
    WithheldFinding,
    emit_report,
    fallback_report,
    render_report,
)

R = redactor_module
CONSISTENCY = NotFoundItem("consistency", "Not Found: consistency is not computed in v1")
FAKE_VALUE = "Fake" + "Value" + "123"  # obviously fake, built at runtime
FAKE_ASSIGN = "pass" + "word=" + FAKE_VALUE

LIMITS_TEXT = "\n".join("  - " + t for t in LIMITATIONS)
LIMITS_BLOCK = "Limitations (not checked, outside v1 scope):\n" + LIMITS_TEXT + "\n"


def passing_validation():
    return ValidationReport(
        results=(
            CheckResult(CHECK_MARKDOWN_SYNTAX, CheckStatus.PASSED, file="docs/a.md"),
            CheckResult(CHECK_RELATIVE_LINKS, CheckStatus.PASSED, file="docs/a.md", rule="added-inline-relative-links"),
            CheckResult(CHECK_NON_EMPTY_OUTPUT, CheckStatus.PASSED),
        ),
        not_found=(CONSISTENCY,),
    )


def success_input(**kw):
    base = dict(
        outcome=ExitCode.OK,
        patch_path="/w/output/docsync.patch",
        default_patch_path="/w/output/docsync.patch",
        examined=("src/b.py", "src/a.py"),
        edits=(ProposedEdit("docs/a.md", "reason", ("src/a.py",), ("run", "go")),),
        validation=passing_validation(),
    )
    base.update(kw)
    return ReportInput(**base)


class GoldenTests(unittest.TestCase):
    def test_passing_run(self):
        expected = (
            "DOCSYNC report\n"
            "Outcome: OK (exit 0): Patch written\n"
            "Planned patch: /w/output/docsync.patch\n"
            "Files examined (2):\n  src/a.py\n  src/b.py\n"
            "Files proposed (1):\n  docs/a.md; sources: src/a.py; symbols: go, run\n"
            "Validation: passed\n"
            "  PASSED markdown_syntax docs/a.md\n"
            "  PASSED non_empty_output\n"
            "  PASSED relative_links docs/a.md: no broken inline relative link on the added lines"
            " (scope: rule added-inline-relative-links; other link kinds are under Limitations)\n"
            "Not Found (1):\n  Not Found: consistency is not computed in v1\n" + LIMITS_BLOCK
        )
        self.assertEqual(render_report(success_input(), redactor=R), expected)

    def test_size_cap_stop(self):
        text = render_report(
            ReportInput(ExitCode.OVER_CAP, message="51 files and 100 changed lines; limits 50 files, 2000 lines; split the change"),
            redactor=R,
        )
        expected = (
            "DOCSYNC report\n"
            "Outcome: OVER_CAP (exit 5): Diff over the cap\n"
            "Run stopped: no patch was written.\n"
            "Detail: 51 files and 100 changed lines; limits 50 files, 2000 lines; split the change\n"
            "Validation: not run\n" + LIMITS_BLOCK
        )
        self.assertEqual(text, expected)

    def test_multi_candidate_stop(self):
        text = render_report(
            ReportInput(
                ExitCode.UNRESOLVED_CANDIDATES,
                candidates=(CandidateGroup("README.md", ("b.py",)), CandidateGroup("docs/a.md", ("z.py", "a.py"))),
                unresolved=("c.py",),
                not_addressed=(NotAddressed("b.py", "README.md"),),
            ),
            redactor=R,
        )
        self.assertIn("Candidates (2):\n  README.md <- b.py\n  docs/a.md <- a.py, z.py\n", text)
        self.assertIn("Not addressed in this run (1):\n  b.py -> README.md\n", text)
        self.assertIn("Unresolved changes (no candidate) (1):\n  c.py\n", text)
        self.assertIn("Outcome: UNRESOLVED_CANDIDATES (exit 8)", text)

    def test_failed_validation_has_file_line_rule_and_not_checked_has_no_line(self):
        validation = ValidationReport(
            results=(
                CheckResult(CHECK_MARKDOWN_SYNTAX, CheckStatus.FAILED, file="docs/a.md", line=7, rule="unclosed-fence"),
                CheckResult(CHECK_RELATIVE_LINKS, CheckStatus.NOT_CHECKED, file="docs/a.md", line=3, rule="not-run"),
            )
        )
        text = render_report(ReportInput(ExitCode.VALIDATION_FAILED, validation=validation), redactor=R)
        self.assertIn("Validation: not passed\n", text)
        self.assertIn("  FAILED markdown_syntax docs/a.md line 7 rule unclosed-fence\n", text)
        self.assertIn("  NOT CHECKED relative_links docs/a.md rule not-run\n", text)
        self.assertNotIn("line 3", text)
        self.assertIn("Outcome: VALIDATION_FAILED (exit 9)", text)

    def test_withheld_hunk_shows_file_and_line_only(self):
        text = render_report(
            ReportInput(ExitCode.WITHHELD_HUNK, withheld=(WithheldFinding("src/b.py", 9), WithheldFinding("src/a.py", 4))),
            redactor=R,
        )
        self.assertIn("Outcome: WITHHELD_HUNK (exit 10)", text)
        self.assertIn("Withheld hunks (file and line only) (2):\n  src/a.py line 4\n  src/b.py line 9\n", text)

    def test_fake_secret_in_name_and_message_is_absent(self):
        bad_name = "docs/" + FAKE_ASSIGN + ".md"
        self.assertTrue(R.contains_secret(bad_name))  # fixture really is flagged
        result = ReportInput(
            ExitCode.OVER_CAP,
            message="see " + FAKE_ASSIGN,
            examined=(bad_name,),
            skipped=(SkippedFile("x.lock", "generated " + FAKE_ASSIGN),),
            withheld=(),
            not_found=(NotFoundItem("s", "detail " + FAKE_ASSIGN, (bad_name,)),),
        )
        text = render_report(result, redactor=R)
        self.assertNotIn(FAKE_VALUE, text)
        self.assertIn(NAME_PLACEHOLDER, text)
        self.assertIn("Detail: [REDACTED-MESSAGE]\n", text)

    def test_no_op_redactor_shows_the_dependence(self):
        class NoOp:
            def redact(self, text):
                return text

            def contains_secret(self, text):
                return False

        text = render_report(ReportInput(ExitCode.OVER_CAP, message=FAKE_ASSIGN), redactor=NoOp())
        self.assertIn(FAKE_VALUE, text)  # masking is the injected Redactor's job


class PurityTests(unittest.TestCase):
    def test_render_report_does_no_io(self):
        def boom(*a, **k):
            raise AssertionError("I/O attempted")

        result = success_input()
        targets = [
            mock.patch.object(builtins, "open", boom),
            mock.patch.object(builtins, "print", boom),
            mock.patch.object(sys, "stdout", mock.Mock(write=boom, flush=boom)),
            mock.patch.object(socket, "socket", boom),
        ]
        for name in ("open", "remove", "mkdir", "write", "rename", "replace", "makedirs"):
            if hasattr(os, name):
                targets.append(mock.patch.object(os, name, boom))
        for t in targets:
            t.start()
            self.addCleanup(t.stop)
        text = render_report(result, redactor=R)
        self.assertIn("DOCSYNC report", text)

    def test_deterministic_sorted_no_timestamps(self):
        a = success_input(examined=("b", "a", "c"))
        b = success_input(examined=("c", "b", "a"))
        self.assertEqual(render_report(a, redactor=R), render_report(b, redactor=R))
        self.assertEqual(render_report(a, redactor=R), render_report(a, redactor=R))
        self.assertIn("Files examined (3):\n  a\n  b\n  c\n", render_report(a, redactor=R))
        self.assertNotRegex(render_report(a, redactor=R), r"\d{4}-\d{2}-\d{2}")

    def test_control_characters_cannot_forge_lines(self):
        text = render_report(ReportInput(ExitCode.OVER_CAP, examined=("a\nOutcome: OK (exit 0)",)), redactor=R)
        self.assertEqual([l for l in text.splitlines() if l.startswith("Outcome:")], ["Outcome: OVER_CAP (exit 5): Diff over the cap"])
        self.assertIn("  a?Outcome: OK (exit 0)\n", text)


class FallbackAndEmitTests(unittest.TestCase):
    def test_fallback_has_only_the_outcome_class(self):
        self.assertEqual(fallback_report("VALIDATION_FAILED"), "Run stopped: VALIDATION_FAILED\n")
        self.assertEqual(fallback_report(ExitCode.WITHHELD_HUNK), "Run stopped: WITHHELD_HUNK\n")

    def test_fallback_unknown_class_is_not_echoed(self):
        for bad in (FAKE_ASSIGN, "OK", ExitCode.OK, None, 5, "x\ny"):
            out = fallback_report(bad)
            self.assertEqual(out, "Run stopped: unknown outcome\n")

    def test_emit_writes_and_flushes(self):
        stream = mock.Mock()
        with mock.patch.object(sys, "stdout", stream):
            emit_report("hello\n")
        stream.write.assert_called_once_with("hello\n")
        stream.flush.assert_called_once_with()

    def test_emit_with_real_stringio(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            emit_report("x\n")
        self.assertEqual(buf.getvalue(), "x\n")

    def test_emit_raises_when_stdout_raises(self):
        bad = mock.Mock()
        bad.write.side_effect = BrokenPipeError("closed")
        with mock.patch.object(sys, "stdout", bad):
            with self.assertRaises(BrokenPipeError):
                emit_report("x")
        bad2 = mock.Mock()
        bad2.flush.side_effect = OSError("flush")
        with mock.patch.object(sys, "stdout", bad2):
            with self.assertRaises(OSError):
                emit_report("x")

    def test_emit_rejects_non_string(self):
        with self.assertRaises(TypeError):
            emit_report(b"x")


class RuleTests(unittest.TestCase):
    def test_limitations_always_shown_on_every_report_kind(self):
        kinds = [
            success_input(),
            ReportInput(ExitCode.OVER_CAP),
            ReportInput(ExitCode.WITHHELD_HUNK, withheld=(WithheldFinding("a.py", 1),)),
            ReportInput(ExitCode.UNEXPECTED, stage="validation", message="boom"),
            ReportInput(ExitCode.NO_CHANGES, validation=ValidationReport()),
        ]
        for item in kinds:
            text = render_report(item, redactor=R)
            self.assertIn(LIMITS_BLOCK, text, item.outcome)
        self.assertIn("External URLs are not checked", LIMITS_TEXT)
        self.assertIn("No dependency or security scanner is run", LIMITS_TEXT)
        self.assertIn("Untracked files are not analyzed", LIMITS_TEXT)
        self.assertIn("Consistency is not computed", LIMITS_TEXT)

    def test_not_found_prefix_added_only_when_missing(self):
        items = (NotFoundItem("a", "Not Found: already prefixed"), NotFoundItem("b", "plain detail", ("f.py",)))
        text = render_report(ReportInput(ExitCode.OVER_CAP, not_found=items), redactor=R)
        self.assertIn("  Not Found: already prefixed\n", text)
        self.assertIn("  Not Found: plain detail (files: f.py)\n", text)
        self.assertNotIn("Not Found: Not Found:", text)

    def test_limitation_items_go_under_limitations_not_passing(self):
        item = NotFoundItem("relative_links_limitation", "external link on an added line", ("docs/a.md",))
        text = render_report(success_input(not_found=(item,)), redactor=R)
        head, tail = text.split("Limitations (", 1)
        self.assertNotIn("external link on an added line", head)
        self.assertIn("  - Not Found: external link on an added line (files: docs/a.md)\n", tail)

    def test_relative_links_pass_is_always_scoped(self):
        text = render_report(success_input(), redactor=R)
        self.assertNotIn("links passed", text)
        self.assertIn("scope: rule added-inline-relative-links", text)

    def test_resolved_destination_shown_only_when_different(self):
        same = render_report(ReportInput(ExitCode.OVER_CAP, patch_path="/w/o.patch", default_patch_path="/w/o.patch"), redactor=R)
        self.assertNotIn("destination", same)
        diff = render_report(ReportInput(ExitCode.OVER_CAP, patch_path="/real/o.patch", default_patch_path="/w/o.patch"), redactor=R)
        self.assertIn("Resolved patch destination: /real/o.patch\n", diff)
        self.assertIn("differs from the default: /w/o.patch\n", diff)
        ok = render_report(success_input(patch_path="/real/o.patch"), redactor=R)
        self.assertIn("Planned patch: /real/o.patch\n", ok)
        self.assertIn("differs from the default", ok)
        none_given = render_report(ReportInput(ExitCode.OVER_CAP, patch_path="/real/o.patch"), redactor=R)
        self.assertNotIn("destination", none_given)

    def test_secret_like_destination_is_replaced_whole(self):
        path = "/w/" + FAKE_ASSIGN + "/o.patch"
        text = render_report(success_input(patch_path=path), redactor=R)
        self.assertNotIn(FAKE_VALUE, text)
        self.assertIn("Planned patch: " + NAME_PLACEHOLDER + "\n", text)

    def test_every_stop_outcome_names_class_and_code(self):
        for code in ExitCode:
            if code is ExitCode.OK:
                continue
            text = render_report(ReportInput(code), redactor=R)
            self.assertIn("Outcome: %s (exit %d)" % (code.name, int(code)), text)

    def test_invalid_inputs_raise(self):
        with self.assertRaises(TypeError):
            render_report({"outcome": 5}, redactor=R)
        with self.assertRaises(TypeError):
            render_report(success_input(), redactor=object())
        with self.assertRaises(TypeError):
            ReportInput(outcome=5)
        with self.assertRaises(TypeError):
            ReportInput(ExitCode.OVER_CAP, examined="abc")
        with self.assertRaises(TypeError):
            ReportInput(ExitCode.OVER_CAP, edits=("x",))
        with self.assertRaises(TypeError):
            ReportInput(ExitCode.OVER_CAP, validation="ok")
        with self.assertRaises(ValueError):
            ReportInput(ExitCode.OK, validation=passing_validation())  # success needs the planned patch path
        with self.assertRaises(ValueError):
            ReportInput(
                ExitCode.OK, patch_path="p", validation=passing_validation(), withheld=(WithheldFinding("a", 1),)
            )
        with self.assertRaises(ValueError):
            WithheldFinding("a.py", 0)
        with self.assertRaises(ValueError):
            SkippedFile("", "x")
        with self.assertRaises(TypeError):
            CandidateGroup("d", "abc")


class FreeTextCapTests(unittest.TestCase):
    CAP = MAX_FREE_TEXT
    MARK = TRUNCATION_MARKER

    def renders(self):
        """One render per free-text field: (name, builder(text) -> report text, line prefix)."""
        return (
            ("message", lambda t: render_report(ReportInput(ExitCode.OVER_CAP, message=t), redactor=R), "Detail: "),
            ("stage", lambda t: render_report(ReportInput(ExitCode.UNEXPECTED, stage=t), redactor=R), "Stage: "),
            (
                "skipped.reason",
                lambda t: render_report(ReportInput(ExitCode.OVER_CAP, skipped=(SkippedFile("a.py", t),)), redactor=R),
                "  a.py: ",
            ),
            (
                "not_found.detail",
                lambda t: render_report(ReportInput(ExitCode.OVER_CAP, not_found=(NotFoundItem("s", t),)), redactor=R),
                "  Not Found: ",  # the whole shown item "Not Found: <detail>" is capped
            ),
        )

    def field_of(self, text, prefix):
        line = [l for l in text.splitlines() if l.startswith(prefix)]
        self.assertEqual(len(line), 1)
        return line[0][len(prefix):]

    def test_long_text_is_truncated_with_marker_in_every_field(self):
        for name, build, prefix in self.renders():
            with self.subTest(field=name):
                shown = self.field_of(build("x" * 5000), prefix)
                extra = len("Not Found: ") if name == "not_found.detail" else 0
                self.assertEqual(len(shown) + extra, self.CAP)
                self.assertTrue(shown.endswith(self.MARK))
                self.assertNotIn("x" * (self.CAP + 1), shown)

    def test_text_exactly_at_cap_is_unchanged_and_one_over_is_cut(self):
        for name, build, prefix in self.renders():
            with self.subTest(field=name):
                limit = self.CAP - (len("Not Found: ") if name == "not_found.detail" else 0)
                text = "y" * limit
                self.assertEqual(self.field_of(build(text), prefix), text)
                self.assertNotIn(self.MARK, build(text))
                over = self.field_of(build("y" * (limit + 1)), prefix)
                self.assertTrue(over.endswith(self.MARK))
                self.assertLessEqual(len(over), self.CAP)

    def test_cap_applies_before_redaction_check_and_to_final_output(self):
        class Expanding:
            seen = []

            def contains_secret(self, text):
                self.seen.append(len(text))
                return False

            def redact(self, text):
                return text + "Z" * 500  # redaction that grows the text

        red = Expanding()
        text = render_report(ReportInput(ExitCode.OVER_CAP, message="m" * 5000), redactor=red)
        self.assertLessEqual(max(red.seen), self.CAP)  # the redactor never saw more than the cap
        self.assertEqual(len(self.field_of(text, "Detail: ")), self.CAP)

    def test_long_secret_like_text_is_still_withheld_or_cut(self):
        text = render_report(ReportInput(ExitCode.OVER_CAP, message=FAKE_ASSIGN + " " + "w" * 5000), redactor=R)
        self.assertNotIn(FAKE_VALUE, text)
        self.assertIn("Detail: [REDACTED-MESSAGE]\n", text)


class SuccessRequiresPassedValidationTests(unittest.TestCase):
    def test_ok_without_validation_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            ReportInput(ExitCode.OK, patch_path="/w/p.patch")
        self.assertEqual(str(ctx.exception), "a success report requires a passed validation")

    def test_ok_with_not_passed_validation_is_rejected_without_echo(self):
        failed = ValidationReport(results=(CheckResult(CHECK_MARKDOWN_SYNTAX, CheckStatus.FAILED, file="docs/a.md", line=1, rule="unclosed-fence"),))
        for validation in (failed, ValidationReport()):
            self.assertFalse(validation.passed)
            with self.assertRaises(ValueError) as ctx:
                ReportInput(ExitCode.OK, patch_path="/w/" + FAKE_ASSIGN, validation=validation)
            self.assertNotIn(FAKE_VALUE, str(ctx.exception))

    def test_ok_with_passed_validation_is_accepted(self):
        self.assertTrue(passing_validation().passed)
        text = render_report(success_input(), redactor=R)
        self.assertIn("Outcome: OK (exit 0)", text)

    def test_stop_outcomes_do_not_need_passed_validation(self):
        ReportInput(ExitCode.VALIDATION_FAILED)
        ReportInput(ExitCode.OVER_CAP, validation=ValidationReport())


if __name__ == "__main__":
    unittest.main()
