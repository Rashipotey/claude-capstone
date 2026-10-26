"""T01 tests: contracts are immutable, validate their fields, and typed errors carry the right exit codes."""

import dataclasses
import unittest

from docsync import contracts as c


class ImmutabilityTests(unittest.TestCase):
    def assert_frozen(self, instance, field, value="changed"):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(instance, field, value)

    def test_every_contract_is_frozen(self):
        self.assert_frozen(c.ChangeRequest("repo"), "repo_path")
        self.assert_frozen(c.ChangedFile("a.py", "M"), "path")
        self.assert_frozen(c.MappingResult("a.py"), "candidate")
        self.assert_frozen(c.ProposedEdit("README.md", "why"), "reason")
        self.assert_frozen(c.NotFoundItem("x", "y"), "subject")
        self.assert_frozen(c.CheckResult("markdown_syntax", c.CheckStatus.PASSED), "status", c.CheckStatus.FAILED)
        self.assert_frozen(c.ValidationReport(), "results", ())

    def test_contracts_cannot_gain_attributes(self):
        # slots=True: no instance dictionary to smuggle state into
        for instance in (c.ChangeRequest("repo"), c.ChangedFile("a.py", "M"), c.ProposedEdit("README.md", "why")):
            # Python 3.12 raises TypeError here (frozen + slots dataclass quirk); the assignment is refused either way.
            with self.assertRaises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
                instance.extra = 1

    def test_sequences_are_stored_as_tuples(self):
        sources = ["a.py", "b.py"]
        edit = c.ProposedEdit("README.md", "why", supporting_sources=sources, symbol_names=["f"])
        sources.append("c.py")  # mutating the caller's list must not change the contract
        self.assertEqual(edit.supporting_sources, ("a.py", "b.py"))
        self.assertIsInstance(edit.symbol_names, tuple)
        self.assertIsInstance(c.NotFoundItem("x", "y", files=["f"]).files, tuple)
        report = c.ValidationReport(results=[c.CheckResult("markdown_syntax", c.CheckStatus.PASSED)])
        self.assertIsInstance(report.results, tuple)

    def test_contracts_are_hashable(self):
        self.assertEqual(hash(c.ChangedFile("a.py", "M", 1, 2)), hash(c.ChangedFile("a.py", "M", 1, 2)))
        self.assertEqual(c.ProposedEdit("R", "why", ["a"]), c.ProposedEdit("R", "why", ("a",)))


class FieldValidationTests(unittest.TestCase):
    def test_proposed_edit_requires_reason_and_target(self):
        with self.assertRaises(ValueError):
            c.ProposedEdit("README.md", "")
        with self.assertRaises(ValueError):
            c.ProposedEdit("", "why")
        edit = c.ProposedEdit("README.md", "why", supporting_sources=("a.py",), symbol_names=("f",))
        self.assertEqual(edit.reason, "why")
        self.assertEqual(edit.supporting_sources, ("a.py",))  # NFR-04

    def test_a_bare_string_is_not_a_sequence_of_sources(self):
        with self.assertRaises(TypeError):
            c.ProposedEdit("README.md", "why", supporting_sources="a.py")
        with self.assertRaises(TypeError):
            c.ProposedEdit("README.md", "why", supporting_sources=(1,))

    def test_change_request(self):
        self.assertIsNone(c.ChangeRequest("repo").target)
        with self.assertRaises(ValueError):
            c.ChangeRequest("")
        with self.assertRaises(TypeError):
            c.ChangeRequest(None)

    def test_changed_lines_are_added_plus_deleted_and_never_zero_when_unknown(self):
        self.assertEqual(c.ChangedFile("a.py", "M", 3, 2).changed_lines, 5)
        self.assertEqual(c.ChangedFile("a.py", "M", 0, 0).changed_lines, 0)
        self.assertIsNone(c.ChangedFile("bin.dat", "M", binary=True).changed_lines)  # D23: unknown is not zero
        self.assertIsNone(c.ChangedFile("a.py", "M", added=3).changed_lines)
        with self.assertRaises(ValueError):
            c.ChangedFile("a.py", "M", added=-1)
        with self.assertRaises(ValueError):
            c.ChangedFile("a.py", "M", added=True)

    def test_changed_file_defaults_to_unclassified(self):
        self.assertIs(c.ChangedFile("a.py", "M").category, c.FileCategory.UNCLASSIFIED)
        with self.assertRaises(TypeError):
            c.ChangedFile("a.py", "M", category="source")

    def test_mapping_result_has_a_candidate_or_a_skip_reason_not_both(self):
        self.assertIsNone(c.MappingResult("a.py").candidate)
        self.assertEqual(c.MappingResult("a.py", candidate="docs/a.md").candidate, "docs/a.md")
        self.assertEqual(c.MappingResult("t.py", skipped_reason="test file").skipped_reason, "test file")
        with self.assertRaises(ValueError):
            c.MappingResult("a.py", candidate="README.md", skipped_reason="test file")

    def test_not_found_item_needs_subject_and_detail(self):
        with self.assertRaises(ValueError):
            c.NotFoundItem("", "detail")
        with self.assertRaises(ValueError):
            c.NotFoundItem("subject", " ")
        self.assertEqual(c.NotFoundItem("consistency", "not computed in v1").files, ())

    def test_check_result_that_is_not_passed_names_its_rule(self):
        c.CheckResult("markdown_syntax", c.CheckStatus.PASSED)  # no rule needed
        with self.assertRaises(ValueError):
            c.CheckResult("markdown_syntax", c.CheckStatus.FAILED, file="docs/a.md", line=3)
        with self.assertRaises(ValueError):
            c.CheckResult("relative_links", c.CheckStatus.NOT_CHECKED)
        failed = c.CheckResult("relative_links", c.CheckStatus.FAILED, file="docs/a.md", line=3, rule="missing-file")
        self.assertEqual((failed.file, failed.line, failed.rule), ("docs/a.md", 3, "missing-file"))
        # a not-checked result reports file and rule only (OQ-3 default)
        c.CheckResult("markdown_syntax", c.CheckStatus.NOT_CHECKED, file="docs/a.md", rule="fence-balance")
        with self.assertRaises(ValueError):
            c.CheckResult("x", c.CheckStatus.FAILED, rule="r", line=0)


def _all_passed():
    return [c.CheckResult(name, c.CheckStatus.PASSED) for name in c.MANDATORY_CHECKS]


class ValidationReportTests(unittest.TestCase):
    def test_passes_only_when_every_mandatory_check_passed(self):
        self.assertTrue(c.ValidationReport(results=_all_passed()).passed)

    def test_empty_report_does_not_pass(self):
        self.assertFalse(c.ValidationReport().passed)

    def test_a_missing_mandatory_check_does_not_pass(self):
        for missing in c.MANDATORY_CHECKS:
            results = [r for r in _all_passed() if r.check != missing]
            self.assertFalse(c.ValidationReport(results=results).passed, missing)

    def test_a_failed_mandatory_check_does_not_pass(self):
        results = _all_passed()[:-1] + [c.CheckResult(c.CHECK_NON_EMPTY_OUTPUT, c.CheckStatus.FAILED, rule="empty")]
        self.assertFalse(c.ValidationReport(results=results).passed)

    def test_a_not_checked_mandatory_check_never_passes(self):
        results = _all_passed()[:-1] + [
            c.CheckResult(c.CHECK_NON_EMPTY_OUTPUT, c.CheckStatus.NOT_CHECKED, file="docs/a.md", rule="not-performed")
        ]
        self.assertFalse(c.ValidationReport(results=results).passed)

    def test_a_duplicate_result_that_is_not_passed_blocks_the_pass(self):
        results = _all_passed() + [
            c.CheckResult(c.CHECK_RELATIVE_LINKS, c.CheckStatus.FAILED, file="docs/a.md", line=2, rule="missing-file")
        ]
        self.assertFalse(c.ValidationReport(results=results).passed)

    def test_non_mandatory_results_and_not_found_items_never_affect_the_outcome(self):
        extra = c.CheckResult("consistency", c.CheckStatus.NOT_CHECKED, mandatory=False, rule="not-computed-in-v1")
        note = c.NotFoundItem("consistency", "consistency is not computed in v1")
        report = c.ValidationReport(results=_all_passed() + [extra], not_found=[note])
        self.assertTrue(report.passed)
        self.assertEqual(report.not_found, (note,))

    def test_only_check_results_are_accepted(self):
        with self.assertRaises(TypeError):
            c.ValidationReport(results=["markdown_syntax"])
        with self.assertRaises(TypeError):
            c.ValidationReport(not_found=["x"])


class ExitCodeAndErrorTests(unittest.TestCase):
    # Architecture Section 6a, copied here as the expected contract.
    EXPECTED_CODES = {
        c.UsageError: 2,
        c.InputOrGitError: 3,
        c.NoChangesError: 4,
        c.OverCapError: 5,
        c.UnsupportedEntryError: 6,
        c.NoSuitableTargetError: 7,
        c.UnresolvedCandidatesError: 8,
        c.ValidationFailedError: 9,
        c.WithheldHunkError: 10,
        c.PatchWriteError: 11,
        c.UnexpectedStageError: 12,
    }

    def test_exit_code_values_match_the_architecture(self):
        self.assertEqual(
            {code.name: int(code) for code in c.ExitCode},
            {
                "OK": 0, "USAGE": 2, "INPUT_OR_GIT": 3, "NO_CHANGES": 4, "OVER_CAP": 5,
                "UNSUPPORTED_ENTRY": 6, "NO_SUITABLE_TARGET": 7, "UNRESOLVED_CANDIDATES": 8,
                "VALIDATION_FAILED": 9, "WITHHELD_HUNK": 10, "PATCH_WRITE": 11, "UNEXPECTED": 12,
            },
        )

    def test_each_error_type_carries_its_designated_code(self):
        for error_type, code in self.EXPECTED_CODES.items():
            error = error_type("cli", "message")
            self.assertEqual(int(error.exit_code), code, error_type.__name__)

    def test_codes_are_distinct_and_exit_12_is_reserved_for_unexpected_failures(self):
        codes = [int(t.exit_code) for t in c.EXPECTED_ERRORS]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn(12, codes)
        self.assertEqual(set(c.EXPECTED_ERRORS) | {c.UnexpectedStageError}, set(self.EXPECTED_CODES))
        self.assertEqual(int(c.UnexpectedStageError("cli", "boom").exit_code), 12)
        self.assertEqual(int(c.StageError.exit_code), 12)  # an untyped base error is unexpected

    def test_errors_are_exceptions_with_stage_and_message(self):
        error = c.OverCapError("sizegate", "60 files, 100 lines")
        self.assertIsInstance(error, c.StageError)
        self.assertIsInstance(error, Exception)
        self.assertEqual((error.stage, error.message), ("sizegate", "60 files, 100 lines"))
        self.assertEqual(str(error), "sizegate: 60 files, 100 lines")
        with self.assertRaises(c.OverCapError):
            raise error

    def test_error_needs_a_known_stage_and_a_message(self):
        with self.assertRaises(ValueError):
            c.UsageError("nonexistent", "message")
        with self.assertRaises(ValueError):
            c.UsageError("cli", "")

    def test_stage_modules_list_is_the_eleven_planned_modules(self):
        self.assertEqual(len(c.STAGE_MODULES), 11)
        self.assertEqual(len(set(c.STAGE_MODULES)), 11)


if __name__ == "__main__":
    unittest.main()
