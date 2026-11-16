"""Tests for check_ledger.py: python3 -I -B -m unittest discover -s docs/ledger"""
import json
import os
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_ledger as C  # noqa: E402

DOC = "The exporter has about 2,400 lines of Pascal and 24 of 70 glbs fail the validator.\n"
SRC = json.dumps([{"errors": 3}, {"errors": 0}, {"errors": 5}])
QUOTE_SRC = '{\n "light": {\n  "x3d": 43,\n  "shape_tree_exporter": 41\n }\n}\n'


class Ledger(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        for name, text in (("doc.md", DOC), ("r.json", SRC), ("q.json", QUOTE_SRC), ("code.pas", "x\n" * 2412)):
            with open(os.path.join(self.d.name, name), "w", encoding="utf-8") as fh:
                fh.write(text)

    def run_one(self, **kw):
        base = dict(id="T", where="doc.md", where_quote="24 of 70 glbs fail the validator", value=24, source="r.json", op="count_where",
                    when=[["errors", ">", 0]])
        base.update(kw)
        return C.check(base, self.d.name)[0]

    def test_a_recompute_that_disagrees_with_the_doc_is_check(self):
        self.assertEqual(self.run_one(value=24, op="count"), "check")  # the source has 3 records, the doc says 24
        self.assertEqual(self.run_one(value=24, op="count_where", when=[["errors", ">", 0]]), "check")  # 2 records have errors

    def test_recompute_agrees_when_doc_and_file_agree(self):
        self.assertEqual(self.run_one(where_quote="2 of 3 glbs fail", value=2), "check")  # the quote is not in the doc
        with open(os.path.join(self.d.name, "doc.md"), "w", encoding="utf-8") as fh:
            fh.write("2 of 3 glbs fail the validator\n")
        self.assertEqual(self.run_one(where_quote="2 of 3 glbs fail the validator", value=2), "verified")
        self.assertEqual(self.run_one(where_quote="2 of 3 glbs fail the validator", value=2, op="sum", key="errors"), "check")

    def test_a_number_that_is_not_in_the_words_is_check(self):
        self.assertEqual(self.run_one(where_quote="24 of 70 glbs fail the validator", value=25), "check")

    def test_quote_op(self):
        e = dict(where_quote="about 2,400 lines of Pascal", value=2400, source="q.json", op="quote", quote='"x3d": 43, "shape_tree_exporter": 41')
        self.assertEqual(self.run_one(**e), "check")  # 2400 is not a number of the quote
        e.update(where_quote="41 of 43 lights", value=41)
        with open(os.path.join(self.d.name, "doc.md"), "w", encoding="utf-8") as fh:
            fh.write("41 of 43 lights kept\n")
        self.assertEqual(self.run_one(**e), "verified")
        e["quote"] = '"x3d": 43, "shape_tree_exporter": 40'
        self.assertEqual(self.run_one(**e), "check")  # the quote is not in the source

    def test_lines_op_catches_the_old_drift(self):
        e = dict(where_quote="about 2,400 lines of Pascal", value=2400, source="code.pas", op="lines", approx=0.01)
        self.assertEqual(self.run_one(**e), "verified")
        with open(os.path.join(self.d.name, "doc.md"), "w", encoding="utf-8") as fh:
            fh.write("about 1,700 lines of Pascal\n")
        e.update(where_quote="about 1,700 lines of Pascal", value=1700)
        self.assertEqual(self.run_one(**e), "check")

    def test_missing_files_are_check_not_a_crash(self):
        self.assertEqual(self.run_one(source="nope.json"), "check")
        self.assertEqual(self.run_one(where="nope.md"), "check")


if __name__ == "__main__":
    unittest.main()
