import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from pbip_inventory import build_inventory
from static_checks import RULES, main, run_checks

# Rules that must fire on BadModel (GOV001 is exercised separately: inside this repo the root
# .gitignore already covers the fixture).
EXPECTED_BAD = set(RULES) - {"GOV001", "SEC003"}


class StaticChecksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bad = run_checks(build_inventory(helpers.BAD))
        cls.good = run_checks(build_inventory(helpers.GOOD))

    def ids(self, result):
        return {f["id"] for f in result["findings"]}

    def find(self, rule, obj=None):
        return [f for f in self.bad["findings"] if f["id"] == rule and (obj is None or obj in f["object"])]

    def test_every_expected_rule_fires_on_bad_model(self):
        self.assertEqual(EXPECTED_BAD - self.ids(self.bad), set())

    def test_good_model_is_clean(self):
        self.assertEqual(self.good["findings"], [], json.dumps(self.good["findings"], indent=1))
        self.assertEqual(self.good["scores"]["overall"], 100)

    def test_every_finding_has_location_and_evidence(self):
        for f in self.bad["findings"]:
            self.assertTrue(f["file"], f)
            self.assertTrue(f["evidence"], f)
            if f["id"] != "GOV001":
                self.assertIsInstance(f["line"], int, f)
                self.assertTrue((helpers.BAD / f["file"]).exists(), f["file"])

    def test_exact_locations(self):
        bulk = self.find("DAX001", "Bulk Sales")[0]
        self.assertEqual((bulk["file"].rsplit("/", 1)[1], bulk["line"]), ("Sales.tmdl", 27))
        growth = self.find("DAX002", "Sales Growth %")[0]
        self.assertEqual(growth["line"], 59)  # the "/" inside the fenced expression
        self.assertIn("/ CALCULATE", growth["evidence"])
        bidi = self.find("MOD001")[0]
        self.assertEqual(bidi["evidence"], "crossFilteringBehavior: bothDirections")

    def test_secret_is_masked_in_evidence(self):
        f = self.find("PQ002")[0]
        self.assertEqual(f["severity"], "critical")
        self.assertNotIn("Summer2024!", f["evidence"])
        self.assertIn("pwd=***", f["evidence"])

    def test_no_double_reporting_of_secret_as_hardcoded_path(self):
        self.assertFalse(self.find("PQ001", "Product"))

    def test_critical_caps_score(self):
        self.assertLessEqual(self.bad["scores"]["overall"], 60)

    def test_disable_rules(self):
        res = run_checks(build_inventory(helpers.BAD), disabled={"DAX002", "MOD001"})
        self.assertFalse({"DAX002", "MOD001"} & self.ids(res))

    def test_scope_filters_findings(self):
        res = run_checks(build_inventory(helpers.BAD), scope={"scopeKeys": ["measure:Sales[Bulk Sales]"]})
        self.assertEqual(self.ids(res), {"DAX001", "DAX005"})
        self.assertEqual(res["mode"], "pr")

    def test_gitignore_rule_outside_git(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            for name, src in (("bad", helpers.BAD), ("good", helpers.GOOD)):
                shutil.copytree(src, Path(tmp) / name)
            bad = run_checks(build_inventory(Path(tmp) / "bad"))
            good = run_checks(build_inventory(Path(tmp) / "good"))
        self.assertIn("GOV001", self.ids(bad))
        self.assertNotIn("GOV001", self.ids(good))

    @unittest.skipUnless(helpers.HAS_GIT, "git not installed")
    def test_gitignore_rule_detects_committed_cache(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = Path(tmp) / "repo"
            shutil.copytree(helpers.GOOD, proj)
            pbi = proj / "GoodModel.SemanticModel" / ".pbi"
            pbi.mkdir()
            (pbi / "cache.abf").write_bytes(b"data")
            helpers.git(proj, "init", "-q")
            helpers.git(proj, "add", "-A")
            helpers.git(proj, "add", "-f", str(pbi / "cache.abf"))
            res = run_checks(build_inventory(proj))
        gov = [f for f in res["findings"] if f["id"] == "GOV001"]
        self.assertEqual(gov[0]["severity"], "critical")

    def test_sec003_username(self):
        inv = build_inventory(helpers.GOOD)
        inv["models"][0]["roles"][0]["tablePermissions"][1]["expression"] = "Security[UserPrincipalName] = USERNAME()"
        self.assertIn("SEC003", self.ids(run_checks(inv)))

    def test_cli(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out = Path(tmp) / "findings.json"
            self.assertEqual(main([str(helpers.BAD), "-o", str(out), "--disable", "dax002"]), 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotIn("DAX002", {f["id"] for f in data["findings"]})


if __name__ == "__main__":
    unittest.main()
