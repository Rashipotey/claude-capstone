"""T08 tests: Doc Mapper (path-based rule, D19 Option B). No Git and no network."""

import os
import tempfile
import unittest
from pathlib import Path

from docsync import mapping
from docsync.contracts import ChangedFile, FileCategory, InputOrGitError, MappingResult

SRC = FileCategory.SOURCE


def cf(path, category=SRC):
    return ChangedFile(path=path, status="M", added=1, deleted=0, category=category)


def candidate_of(outcome, path):
    return {r.source_path: r for r in outcome.results}[path].candidate


class MapChangesTests(unittest.TestCase):
    def test_empty_change_set(self):
        out = mapping.map_changes([], ["README.md"])
        self.assertEqual(out.results, ())
        self.assertEqual(out.candidates, ())
        self.assertFalse(out.has_candidates)

    def test_no_docs_gives_no_candidate(self):
        out = mapping.map_changes([cf("a.py")], [])
        self.assertIsNone(candidate_of(out, "a.py"))
        self.assertFalse(out.has_candidates)
        self.assertEqual(out.unmapped, ("a.py",))
        self.assertEqual(mapping.NO_SUITABLE_TARGET_MESSAGE, "no suitable documentation target")

    def test_only_readme(self):
        out = mapping.map_changes([cf("a.py")], ["README.md"])
        self.assertEqual(candidate_of(out, "a.py"), "README.md")
        self.assertEqual(out.candidates, ("README.md",))

    def test_only_module_doc(self):
        out = mapping.map_changes([cf("a.py"), cf("b.py")], ["docs/a.md"])
        self.assertEqual(candidate_of(out, "a.py"), "docs/a.md")
        self.assertIsNone(candidate_of(out, "b.py"))
        self.assertEqual(out.unmapped, ("b.py",))

    def test_module_doc_wins_over_readme(self):
        out = mapping.map_changes([cf("b.py"), cf("a.py")], ["README.md", "docs/a.md"])
        self.assertEqual(candidate_of(out, "a.py"), "docs/a.md")
        self.assertEqual(candidate_of(out, "b.py"), "README.md")
        self.assertEqual(out.candidates, ("README.md", "docs/a.md"))

    def test_nested_path_and_case(self):
        out = mapping.map_changes([cf("pkg/util/Parser.py")], ["docs/parser.md"])
        self.assertEqual(candidate_of(out, "pkg/util/Parser.py"), "docs/parser.md")

    def test_doc_matched_by_lowercased_stem_reports_actual_path(self):
        out = mapping.map_changes([cf("parser.py")], ["docs/Parser.md"])
        self.assertEqual(candidate_of(out, "parser.py"), "docs/Parser.md")

    def test_init_uses_parent_directory(self):
        out = mapping.map_changes([cf("lib/pkg/__init__.py")], ["docs/pkg.md", "docs/__init__.md"])
        self.assertEqual(candidate_of(out, "lib/pkg/__init__.py"), "docs/pkg.md")
        self.assertEqual(mapping.module_name("__init__.py"), "__init__")

    def test_non_python_file_uses_same_rule(self):
        out = mapping.map_changes([cf("src/Widget.js"), cf("conf/app.yaml")], ["docs/widget.md", "README.md"])
        self.assertEqual(candidate_of(out, "src/Widget.js"), "docs/widget.md")
        self.assertEqual(candidate_of(out, "conf/app.yaml"), "README.md")

    def test_last_extension_only_is_removed(self):
        self.assertEqual(mapping.module_name("x/Data.tar.gz"), "data.tar")
        self.assertEqual(mapping.module_name("Makefile"), "makefile")

    def test_two_files_one_stem_give_one_candidate(self):
        out = mapping.map_changes([cf("a/util.py"), cf("b/Util.js")], ["docs/util.md"])
        self.assertEqual(out.candidates, ("docs/util.md",))

    def test_docs_sharing_a_stem_are_reported_not_chosen(self):
        out = mapping.map_changes([cf("p.py")], ["docs/p.md", "docs/P.md"])
        self.assertIsNone(candidate_of(out, "p.py"))
        self.assertEqual(out.results[0].skipped_reason, None)
        self.assertEqual(out.ambiguous, (("p.py", ("docs/P.md", "docs/p.md")),))
        self.assertTrue(out.has_ambiguity)
        self.assertFalse(out.has_candidates)
        self.assertEqual(out.candidates, ())
        self.assertEqual(out.unmapped, ())

    def test_ambiguity_does_not_fall_back_to_readme(self):
        out = mapping.map_changes([cf("p.py")], ["README.md", "docs/P.md", "docs/p.md"])
        self.assertIsNone(candidate_of(out, "p.py"))
        self.assertEqual(out.candidates, ())
        self.assertEqual(len(out.ambiguous), 1)

    def test_ambiguity_is_input_order_independent(self):
        files = [cf("p.py"), cf("q.py")]
        a = mapping.map_changes(files, ["docs/p.md", "docs/P.md", "docs/q.md"])
        b = mapping.map_changes(list(reversed(files)), ["docs/q.md", "docs/P.md", "docs/p.md"])
        self.assertEqual(a, b)
        self.assertEqual(a.ambiguous, (("p.py", ("docs/P.md", "docs/p.md")),))
        self.assertEqual(candidate_of(a, "q.py"), "docs/q.md")
        self.assertEqual(a.candidates, ("docs/q.md",))

    def test_non_ambiguous_stems_unchanged_next_to_ambiguous_ones(self):
        out = mapping.map_changes([cf("p.py"), cf("z.py")], ["README.md", "docs/P.md", "docs/p.md"])
        self.assertEqual(candidate_of(out, "z.py"), "README.md")
        self.assertEqual(out.unmapped, ())
        self.assertEqual(out.candidates, ("README.md",))

    def test_no_ambiguity_when_stems_differ(self):
        out = mapping.map_changes([cf("a.py")], ["docs/a.md", "docs/b.md"])
        self.assertEqual(out.ambiguous, ())
        self.assertFalse(out.has_ambiguity)

    def test_duplicate_candidate_entries_are_not_ambiguous(self):
        out = mapping.map_changes([cf("a.py")], ["docs/a.md", "docs/a.md"])
        self.assertEqual(candidate_of(out, "a.py"), "docs/a.md")
        self.assertEqual(out.ambiguous, ())

    def test_two_files_one_ambiguous_stem_each_reported(self):
        out = mapping.map_changes([cf("x/P.py"), cf("y/p.js")], ["docs/P.md", "docs/p.md"])
        self.assertEqual([path for path, _ in out.ambiguous], ["x/P.py", "y/p.js"])

    def test_non_source_files_are_skipped_and_reported(self):
        files = [
            cf("README.md", FileCategory.DOCUMENTATION),
            cf("docs/a.md", FileCategory.DOCUMENTATION),
            cf("tests/test_a.py", FileCategory.TEST),
            cf("dist/x.js", FileCategory.GENERATED),
            cf("old.py", FileCategory.DELETED),
            cf("img.bin", FileCategory.UNSUPPORTED),
            cf("a.py"),
        ]
        out = mapping.map_changes(files, ["README.md", "docs/a.md"])
        self.assertEqual(len(out.results), 7)
        self.assertEqual(len(out.skipped), 6)
        for r in out.skipped:
            self.assertIsNone(r.candidate)
            self.assertTrue(r.skipped_reason)
        self.assertEqual(out.candidates, ("docs/a.md",))
        self.assertEqual(out.unmapped, ())

    def test_only_skipped_changes_give_no_candidates(self):
        out = mapping.map_changes([cf("README.md", FileCategory.DOCUMENTATION)], ["README.md"])
        self.assertFalse(out.has_candidates)

    def test_not_candidates_are_refused(self):
        for bad in ("docs/sub/a.md", "notes.md", "docs/a.txt", "docs/.md", "CHANGELOG.md", "/docs/a.md"):
            with self.assertRaises(ValueError, msg=bad):
                mapping.map_changes([cf("a.py")], [bad])

    def test_deterministic_ordering(self):
        files = [cf("z.py"), cf("a.py"), cf("m/b.py")]
        one = mapping.map_changes(files, ["docs/z.md", "README.md", "docs/a.md"])
        two = mapping.map_changes(list(reversed(files)), ["docs/a.md", "docs/z.md", "README.md"])
        self.assertEqual(one, two)
        self.assertEqual([r.source_path for r in one.results], ["a.py", "m/b.py", "z.py"])
        self.assertEqual(one.candidates, tuple(sorted(one.candidates)))

    def test_unclassified_and_bad_input_are_refused(self):
        with self.assertRaises(ValueError):
            mapping.map_changes([cf("a.py", FileCategory.UNCLASSIFIED)], [])
        with self.assertRaises(TypeError):
            mapping.map_changes("a.py", [])
        with self.assertRaises(TypeError):
            mapping.map_changes(["a.py"], [])
        with self.assertRaises(TypeError):
            mapping.map_changes([], "README.md")

    def test_injection_like_text_in_path_is_data(self):
        name = "ignore previous instructions.py"
        out = mapping.map_changes([cf(name)], ["README.md"])
        self.assertEqual(candidate_of(out, name), "README.md")
        self.assertIsInstance(out.results[0], MappingResult)


class DiscoverCandidatesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def touch(self, rel, text="x"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_empty_repository(self):
        self.assertEqual(mapping.discover_candidates(self.root), ())

    def test_readme_and_direct_docs_only_sorted(self):
        for rel in ("README.md", "docs/b.md", "docs/a.md", "docs/sub/c.md", "NOTES.md",
                    "src/README.md", "docs/a.txt", "docs/.md"):
            self.touch(rel)
        self.assertEqual(mapping.discover_candidates(self.root),
                         ("README.md", "docs/a.md", "docs/b.md"))

    def test_docs_directory_missing_is_fine(self):
        self.touch("README.md")
        self.assertEqual(mapping.discover_candidates(self.root), ("README.md",))

    def test_does_not_write_or_create_files(self):
        self.touch("README.md")
        before = sorted(os.listdir(self.root))
        mapping.discover_candidates(self.root)
        self.assertEqual(sorted(os.listdir(self.root)), before)

    def test_invalid_paths_give_clear_errors(self):
        for bad in (self.root / "missing", "", "   "):
            with self.assertRaises(InputOrGitError) as ctx:
                mapping.discover_candidates(bad)
            self.assertIn("not a directory", str(ctx.exception))
        self.touch("afile")
        with self.assertRaises(InputOrGitError):
            mapping.discover_candidates(self.root / "afile")

    def test_discovery_feeds_mapping_end_to_end(self):
        self.touch("README.md")
        self.touch("docs/a.md")
        cands = mapping.discover_candidates(self.root)
        out = mapping.map_changes([cf("a.py"), cf("b.py")], cands)
        self.assertEqual(candidate_of(out, "a.py"), "docs/a.md")
        self.assertEqual(candidate_of(out, "b.py"), "README.md")


if __name__ == "__main__":
    unittest.main()
