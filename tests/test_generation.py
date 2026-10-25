"""T10 tests: Doc Generator (AC-02, AC-03, NFR-04, NFR-05, E9, D17, D20)."""

import dataclasses
import unittest

from docsync import generation
from docsync.contracts import MappingResult, NotFoundItem, ProposedEdit


@dataclasses.dataclass(frozen=True)
class Ev:  # local stand-in for the analyzer's FileEvidence (stages cannot import each other)
    path: str
    symbol_names: tuple = ()


class GenerateTests(unittest.TestCase):
    def test_python_function_gives_one_minimal_edit(self):
        out = generation.generate([Ev("pkg/billing.py", ("charge",))],
                                  [MappingResult("pkg/billing.py", "docs/billing.md")])
        self.assertEqual(len(out.edits), 1)
        self.assertEqual(out.not_found, ())
        edit = out.edits[0]
        self.assertIsInstance(edit, ProposedEdit)
        self.assertEqual(edit.target, "docs/billing.md")
        self.assertEqual(edit.symbol_names, ("charge",))
        self.assertEqual(edit.supporting_sources, ("pkg/billing.py",))
        self.assertNotIn("\n", edit.reason)
        self.assertIn("pkg/billing.py", edit.reason)

    def test_non_python_change_is_not_found(self):
        out = generation.generate([Ev("web/app.js", ())], [MappingResult("web/app.js", "README.md")])
        self.assertEqual(out.edits, ())
        self.assertEqual(len(out.not_found), 1)
        self.assertIsInstance(out.not_found[0], NotFoundItem)
        self.assertEqual(out.not_found[0].files, ("web/app.js",))

    def test_missing_evidence_is_not_found(self):
        out = generation.generate([], [MappingResult("a.py", "README.md")])
        self.assertEqual(out.edits, ())
        self.assertEqual(out.not_found[0].files, ("a.py",))

    def test_conflicting_sources_list_both_files_and_get_no_edit(self):
        ev = [Ev("a/util.py", ("run",)), Ev("b/util.py", ("run", "stop"))]
        maps = [MappingResult("a/util.py", "docs/util.md"), MappingResult("b/util.py", "docs/util.md")]
        out = generation.generate(ev, maps)
        self.assertEqual(out.edits, ())
        self.assertEqual(len(out.not_found), 1)
        self.assertEqual(out.not_found[0].files, ("a/util.py", "b/util.py"))

    def test_conflict_does_not_block_unrelated_pairs(self):
        ev = [Ev("a/u.py", ("run",)), Ev("b/u.py", ("run",)), Ev("c.py", ("go",))]
        maps = [MappingResult("a/u.py", "docs/u.md"), MappingResult("b/u.py", "docs/u.md"),
                MappingResult("c.py", "docs/u.md")]
        out = generation.generate(ev, maps)
        self.assertEqual([e.supporting_sources for e in out.edits], [("c.py",)])
        self.assertEqual(out.not_found[0].files, ("a/u.py", "b/u.py"))

    def test_disagreeing_records_for_one_path_conflict(self):
        out = generation.generate([Ev("a.py", ("x",)), Ev("a.py", ("y",))],
                                  [MappingResult("a.py", "README.md")])
        self.assertEqual(out.edits, ())
        self.assertEqual(out.not_found[0].files, ("a.py",))

    def test_unmapped_and_skipped_get_nothing(self):
        out = generation.generate(
            [Ev("a.py", ("x",))],
            [MappingResult("a.py"), MappingResult("t.py", skipped_reason="test file, not mapped")])
        self.assertEqual(out, generation.GenerationOutcome())
        self.assertFalse(out.has_edits)

    def test_empty_change_set(self):
        self.assertEqual(generation.generate([], []), generation.GenerationOutcome())

    def test_target_filter_limits_scope(self):
        ev = [Ev("a.py", ("x",)), Ev("b.py", ("y",))]
        maps = [MappingResult("a.py", "docs/a.md"), MappingResult("b.py", "README.md")]
        out = generation.generate(ev, maps, target="README.md")
        self.assertEqual([e.target for e in out.edits], ["README.md"])

    def test_deterministic_sorted_and_input_untouched(self):
        ev = [Ev("b.py", ("z", "a", "a")), Ev("a.py", ("m",))]
        maps = [MappingResult("b.py", "README.md"), MappingResult("a.py", "README.md")]
        before = (list(ev), list(maps))
        first = generation.generate(ev, maps)
        self.assertEqual(first, generation.generate(list(reversed(ev)), list(reversed(maps))))
        self.assertEqual((ev, maps), before)
        self.assertEqual([e.supporting_sources for e in first.edits], [("a.py",), ("b.py",)])
        self.assertEqual(first.edits[1].symbol_names, ("a", "z"))

    def test_edit_carries_only_the_allowed_fields(self):
        edit = generation.generate([Ev("a.py", ("x",))], [MappingResult("a.py", "README.md")]).edits[0]
        self.assertEqual({f.name for f in dataclasses.fields(edit)},
                         {"target", "reason", "supporting_sources", "symbol_names"})
        self.assertEqual(edit.reason, generation.REASON_TEMPLATE % ("a.py", "README.md"))

    def test_bad_input_types_are_rejected(self):
        with self.assertRaises(TypeError):
            generation.generate("a.py", [])
        with self.assertRaises(TypeError):
            generation.generate([], ["a.py"])
        with self.assertRaises(TypeError):
            generation.generate([object()], [])


if __name__ == "__main__":
    unittest.main()
