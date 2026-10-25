"""T06 tests: Size Gate cap, counting rules, and unsupported entries. In-memory records only."""

import unittest

from docsync import sizegate
from docsync.contracts import (
    ChangedFile,
    ExitCode,
    NoChangesError,
    OverCapError,
    UnsupportedEntryError,
)
from docsync.sizegate import check_size


def text(path, added=1, deleted=0, status="M", **kw):
    return ChangedFile(path=path, status=status, added=added, deleted=deleted,
                       old_mode=kw.pop("old_mode", "100644"), new_mode=kw.pop("new_mode", "100644"), **kw)


def many(n, added=1, deleted=0):
    return [text("f%d.py" % i, added, deleted) for i in range(n)]


def gate(files):
    return check_size(files, redactor=lambda s: s)


class CapBoundaryTests(unittest.TestCase):
    def test_50_files_pass_and_51_stop(self):
        result = gate(many(50))
        self.assertEqual((result.file_count, result.line_count), (50, 50))
        with self.assertRaises(OverCapError) as ctx:
            gate(many(51))
        self.assertEqual(ctx.exception.exit_code, ExitCode.OVER_CAP)
        self.assertEqual((ctx.exception.file_count, ctx.exception.line_count), (51, 51))

    def test_2000_lines_pass_and_2001_stop(self):
        self.assertEqual(gate([text("a.py", 1000, 1000)]).line_count, 2000)
        with self.assertRaises(OverCapError) as ctx:
            gate([text("a.py", 1000, 1001)])
        self.assertEqual(ctx.exception.line_count, 2001)

    def test_lines_are_added_plus_deleted_across_files(self):
        self.assertEqual(gate([text("a.py", 600, 400), text("b.py", 500, 500)]).line_count, 2000)
        with self.assertRaises(OverCapError):
            gate([text("a.py", 600, 400), text("b.py", 500, 501)])

    def test_each_limit_alone_and_both(self):
        with self.assertRaises(OverCapError) as files_only:
            gate(many(51))
        self.assertEqual(files_only.exception.line_count, 51)
        with self.assertRaises(OverCapError) as lines_only:
            gate([text("a.py", 2001, 0)])
        self.assertEqual(lines_only.exception.file_count, 1)
        with self.assertRaises(OverCapError) as both:
            gate(many(51, 100, 0))
        self.assertEqual((both.exception.file_count, both.exception.line_count), (51, 5100))

    def test_message_reports_both_counts_and_asks_for_a_split(self):
        with self.assertRaises(OverCapError) as ctx:
            gate(many(51))
        message = str(ctx.exception)
        self.assertIn("51 files", message)
        self.assertIn("51 changed lines", message)
        self.assertIn("split", message)

    def test_a_very_large_file_counts_toward_the_cap_only(self):
        with self.assertRaises(OverCapError):
            gate([text("big.lock", 5000, 0)])


class EmptyAndRedactionTests(unittest.TestCase):
    def test_empty_set_is_no_changes(self):
        for empty in ([], ()):
            with self.assertRaises(NoChangesError) as ctx:
                gate(empty)
            self.assertEqual(ctx.exception.exit_code, ExitCode.NO_CHANGES)
            self.assertIn("no changes", str(ctx.exception))

    def test_bad_arguments(self):
        with self.assertRaises(TypeError):
            check_size([text("a.py")], redactor=None)
        with self.assertRaises(TypeError):
            check_size("a.py", redactor=lambda s: s)
        with self.assertRaises(TypeError):
            check_size([("a.py", 1, 0)], redactor=lambda s: s)

    def test_messages_pass_through_the_redactor(self):
        marker = []

        def redactor(message):
            marker.append(message)
            return message.replace("secretname", "[REDACTED]")

        with self.assertRaises(UnsupportedEntryError) as ctx:
            check_size([ChangedFile(path="secretname.bin", status="M", binary=True)], redactor=redactor)
        self.assertNotIn("secretname", str(ctx.exception))
        self.assertTrue(marker)

    def test_control_characters_in_paths_are_not_shown(self):
        with self.assertRaises(UnsupportedEntryError) as ctx:
            gate([ChangedFile(path="a\nb.bin", status="M", binary=True)])
        self.assertNotIn("\n", str(ctx.exception))


class CountingRuleTests(unittest.TestCase):
    def test_pure_rename_is_one_file_zero_lines(self):
        result = gate([text("new.py", 0, 0, status="R100", old_path="old.py")])
        self.assertEqual((result.file_count, result.line_count), (1, 0))

    def test_pure_copy_is_one_file_zero_lines(self):
        result = gate([text("copy.py", 0, 0, status="C100", old_path="orig.py")])
        self.assertEqual((result.file_count, result.line_count), (1, 0))

    def test_rename_with_edits_counts_changed_lines(self):
        result = gate([text("new.py", 3, 2, status="R80", old_path="old.py")])
        self.assertEqual((result.file_count, result.line_count), (1, 5))

    def test_deleted_file_counts_and_is_not_analyzed(self):
        deleted = ChangedFile(path="gone.py", status="D", added=0, deleted=40,
                              old_mode="100644", new_mode="000000")
        result = gate([deleted, text("kept.py", 2, 1)])
        self.assertEqual((result.file_count, result.line_count), (2, 43))
        self.assertEqual(result.not_analyzed, ("gone.py",))

    def test_no_deleted_files_means_nothing_not_analyzed(self):
        self.assertEqual(gate([text("a.py")]).not_analyzed, ())

    def test_added_empty_file_is_one_file_zero_lines(self):
        empty = ChangedFile(path="empty.txt", status="A", added=0, deleted=0,
                            old_mode="000000", new_mode="100644")
        result = gate([empty])
        self.assertEqual((result.file_count, result.line_count), (1, 0))

    def test_generated_paths_still_count(self):
        result = gate([text("poetry.lock", 10, 0), text("dist/x.js", 5, 5)])
        self.assertEqual((result.file_count, result.line_count), (2, 20))

    def test_deleted_file_lines_count_toward_the_cap(self):
        deleted = ChangedFile(path="gone.py", status="D", added=0, deleted=2001,
                              old_mode="100644", new_mode="000000")
        with self.assertRaises(OverCapError):
            gate([deleted])


class UnsupportedEntryTests(unittest.TestCase):
    def assert_unsupported(self, entry, kind, files=None):
        with self.assertRaises(UnsupportedEntryError) as ctx:
            gate(files if files is not None else [entry])
        err = ctx.exception
        self.assertEqual(err.exit_code, ExitCode.UNSUPPORTED_ENTRY)
        self.assertEqual(err.kind, kind)
        self.assertIn(kind, str(err))
        self.assertIn(entry.path, str(err))
        self.assertEqual(err.path, entry.path)

    def test_binary_entry(self):
        self.assert_unsupported(ChangedFile(path="logo.png", status="M", binary=True), sizegate.KIND_BINARY)

    def test_mode_only_entry(self):
        entry = text("run.sh", 0, 0, old_mode="100644", new_mode="100755")
        self.assert_unsupported(entry, sizegate.KIND_MODE_ONLY)

    def test_submodule_entry(self):
        entry = ChangedFile(path="vendor/lib", status="M", added=1, deleted=1,
                            old_mode="160000", new_mode="160000")
        self.assert_unsupported(entry, sizegate.KIND_SUBMODULE)

    def test_added_submodule_entry(self):
        entry = ChangedFile(path="vendor/lib", status="A", added=1, deleted=0,
                            old_mode="000000", new_mode="160000")
        self.assert_unsupported(entry, sizegate.KIND_SUBMODULE)

    def test_unknown_counts_without_binary_flag_is_never_zero(self):
        entry = ChangedFile(path="odd.py", status="M")
        self.assert_unsupported(entry, sizegate.KIND_UNKNOWN_COUNTS)

    def test_mode_change_with_edits_is_a_normal_entry(self):
        result = gate([text("run.sh", 2, 1, old_mode="100644", new_mode="100755")])
        self.assertEqual(result.line_count, 3)

    def test_unsupported_entry_among_valid_files(self):
        bad = ChangedFile(path="logo.png", status="M", binary=True)
        self.assert_unsupported(bad, sizegate.KIND_BINARY, files=many(3) + [bad])

    def test_over_cap_and_unsupported_reports_the_unsupported_entry(self):
        bad = ChangedFile(path="logo.png", status="M", binary=True)
        with self.assertRaises(UnsupportedEntryError) as ctx:
            gate(many(60, 100, 0) + [bad])
        self.assertEqual(ctx.exception.exit_code, ExitCode.UNSUPPORTED_ENTRY)
        self.assertNotIsInstance(ctx.exception, OverCapError)

    def test_several_unsupported_entries_are_all_listed(self):
        bad1 = ChangedFile(path="a.png", status="M", binary=True)
        bad2 = text("run.sh", 0, 0, old_mode="100644", new_mode="100755")
        with self.assertRaises(UnsupportedEntryError) as ctx:
            gate([bad1, bad2])
        self.assertEqual(ctx.exception.entries, (("a.png", "binary"), ("run.sh", "mode-only")))
        self.assertIn("1 more", str(ctx.exception))

    def test_classify_unsupported_of_normal_entries_is_none(self):
        self.assertIsNone(sizegate.classify_unsupported(text("a.py")))
        self.assertIsNone(sizegate.classify_unsupported(text("a.py", 0, 0, status="R100", old_path="b.py")))


if __name__ == "__main__":
    unittest.main()
