"""The eval grader: expected-issues.md parses, and static output alone finds every static (S) issue."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, ROOT, SCRIPTS

sys.path.insert(0, str(ROOT / "tests" / "eval"))
import grade  # noqa: E402


def static_run(fixture: str, tmp: Path) -> Path:
    shutil.copytree(FIXTURES / fixture, tmp / fixture)
    shutil.copy(ROOT / ".gitignore", tmp / ".gitignore")  # keeps GOV001 quiet, as in the eval setup
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    out = tmp / "out"
    subprocess.run([sys.executable, str(SCRIPTS / "pbip_inventory.py"), fixture, "-o", str(out / "inventory.json")],
                   cwd=tmp, check=True, capture_output=True)
    subprocess.run([sys.executable, str(SCRIPTS / "static_checks.py"), "--inventory", str(out / "inventory.json"),
                    "-o", str(out / "findings.json")], cwd=tmp, check=True, capture_output=True)
    return tmp


class GraderTests(unittest.TestCase):
    def test_expected_issues_parse(self):
        rows = grade.load_expected(grade.DEFAULT_EXPECTED)
        self.assertGreaterEqual(len(rows), 25)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertTrue(all(r["rules"] and r["anchor"] for r in rows))
        self.assertGreaterEqual(sum(r["kind"] == "J" for r in rows), 5)

    def test_static_only_finds_all_static_issues(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            res = grade.grade(static_run("BadModel", Path(t)), "bad")
            n_s = sum(r["kind"] == "S" for r in grade.load_expected(grade.DEFAULT_EXPECTED))
            self.assertTrue(res["recallStatic"].startswith(f"{n_s}/{n_s}"), res["missed"])
            self.assertEqual(res["citationsValid"], res["keptFindings"])

    def test_good_model_has_no_static_false_positives(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            res = grade.grade(static_run("GoodModel", Path(t)), "good")
            self.assertEqual(res["falsePositives"], [])

    def test_dropped_findings_are_not_counted(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            root = static_run("BadModel", Path(t))
            judgment = [{"id": "DAX010", "dropped": True, "reason": "test"},
                        {"id": "DAX101", "category": "DAX", "severity": "high", "object": "Sales[Total Revenue]",
                         "file": "BadModel/BadModel.SemanticModel/definition/tables/Sales.tmdl", "line": 15,
                         "message": "counts rows"}]
            (root / "out" / "judgment.json").write_text(json.dumps(judgment), encoding="utf-8")
            res = grade.grade(root, "bad")
            self.assertIn("B27 (DAX010)", res["missed"])
            self.assertNotIn("B02 (DAX101)", res["missed"])
            self.assertEqual(res["staticDropped"], 1)


if __name__ == "__main__":
    unittest.main()
