import re
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from diff_scope import build_scope

MEASURES = "GoodModel/GoodModel.SemanticModel/definition/tables/_Measures.tmdl"
CUSTOMER = "GoodModel/GoodModel.SemanticModel/definition/tables/Customer.tmdl"


@unittest.skipUnless(helpers.HAS_GIT, "git not installed")
class DiffScopeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = Path(self._tmp.name) / "repo"
        shutil.copytree(helpers.GOOD, self.repo / "GoodModel")
        helpers.git(self.repo, "init", "-q")
        helpers.git(self.repo, "checkout", "-q", "-b", "main")
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "-m", "base")
        helpers.git(self.repo, "checkout", "-q", "-b", "feature")

    def tearDown(self):
        self._tmp.cleanup()

    def edit(self, rel, old, new, count=1):
        p = self.repo / rel
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new, count), encoding="utf-8")

    def commit(self):
        helpers.git(self.repo, "commit", "-q", "-am", "change")

    def keys(self, scope, bucket):
        return {o["key"] for o in scope["objects"][bucket]}

    def test_modified_measure_and_impacted_dependents(self):
        self.edit(MEASURES, "measure Margin = [Sales Amount] - [Total Cost]",
                  "measure Margin = [Sales Amount] / [Total Cost]")
        self.commit()
        scope = build_scope(self.repo, "main", "feature")
        self.assertEqual(self.keys(scope, "modified"), {"measure:_Measures[Margin]"})
        impacted = {o["key"] for o in scope["impacted"]}
        self.assertIn("measure:_Measures[Margin %]", impacted)
        self.assertTrue(any(k.startswith("visual:") for k in impacted))
        self.assertIn("measure:_Measures[Sales Amount]", scope["context"])
        self.assertEqual(scope["scopeKeys"], ["measure:_Measures[Margin]"])
        self.assertEqual(list(scope["changedLines"]), [MEASURES])

    def test_removed_column_reports_broken_visual(self):
        p = self.repo / CUSTOMER
        p.write_text(re.sub(r"\tcolumn Segment\n(\t\t.*\n)+\n", "", p.read_text(encoding="utf-8")), encoding="utf-8")
        self.commit()
        scope = build_scope(self.repo, "main", "feature")
        self.assertEqual(self.keys(scope, "removed"), {"column:Customer[Segment]"})
        self.assertEqual(self.keys(scope, "modified"), set())
        self.assertEqual([b["missing"] for b in scope["brokenReferences"]], ["column:Customer[Segment]"])

    def test_added_measure_in_worktree_mode(self):
        self.edit(MEASURES, "\tcolumn Placeholder",
                  "\tmeasure 'Avg Price' = [Sales Amount] / SUM(Sales[Quantity])\n\t\tformatString: 0.00\n\n"
                  "\tcolumn Placeholder")
        scope = build_scope(self.repo, "main")  # uncommitted change, head = working tree
        self.assertEqual(scope["head"], "WORKTREE")
        self.assertEqual(self.keys(scope, "added"), {"measure:_Measures[Avg Price]"})

    def test_removed_measure_breaks_dax(self):
        p = self.repo / MEASURES
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"\t/// Gross margin in currency\.\n\tmeasure Margin = .*?\n\n", "", text, flags=re.S)
        p.write_text(text, encoding="utf-8")
        self.commit()
        scope = build_scope(self.repo, "main", "feature")
        self.assertIn("measure:_Measures[Margin]", self.keys(scope, "removed"))
        broken = {b["by"] for b in scope["brokenReferences"]}
        self.assertIn("measure:_Measures[Margin %]", broken)

    def test_report_visual_change(self):
        rel = next((self.repo / "GoodModel").rglob("cardSales/visual.json")).relative_to(self.repo).as_posix()
        self.edit(rel, '"height": 100', '"height": 120')
        self.commit()
        scope = build_scope(self.repo, "main", "feature")
        modified = self.keys(scope, "modified")
        self.assertEqual(len(modified), 1)
        key = next(iter(modified))
        self.assertTrue(key.startswith("visual:") and key.endswith("/cardSales"))
        self.assertTrue(any(k.startswith("page:") for k in scope["scopeKeys"]))


if __name__ == "__main__":
    unittest.main()
