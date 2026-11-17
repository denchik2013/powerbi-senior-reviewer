import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from field_usage import build_usage
from pbip_inventory import build_inventory


class FieldUsageTests(unittest.TestCase):
    def test_bad_model_unused_objects(self):
        u = build_usage(build_inventory(helpers.BAD))["models"][0]
        self.assertEqual(u["reportCoverage"], "linked")
        self.assertEqual(sorted((c["table"], c["name"]) for c in u["unusedColumns"]), [
            ("Customer", "Fax"), ("FactBudget", "Month"), ("Product", "Legacy Code"),
            ("Sales", "TransactionGUID"), ("dim_store", "Region")])
        self.assertEqual([m["name"] for m in u["unusedMeasures"]], ["Discount Rate (old)"])

    def test_usage_sources_are_recorded(self):
        u = build_usage(build_inventory(helpers.BAD))["models"][0]
        cols = {(c["table"], c["name"]): c for c in u["columns"]}
        self.assertTrue(any(b.startswith("relationship") for b in cols[("Sales", "ShipDate")]["usedBy"]))
        self.assertTrue(any(b.startswith("sortByColumn") for b in cols[("Date", "Month Number")]["usedBy"]))
        self.assertTrue(any(b.startswith("rls") for b in cols[("dim_store", "Manager Email")]["usedBy"]))
        self.assertTrue(any("filter" in b for b in cols[("Customer", "Segment")]["usedBy"]))

    def test_good_model_has_nothing_unused(self):
        u = build_usage(build_inventory(helpers.GOOD))["models"][0]
        self.assertEqual(u["unusedColumns"], [])
        self.assertEqual(u["unusedMeasures"], [])

    def test_model_without_report_reports_no_coverage(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            shutil.copytree(helpers.GOOD / "GoodModel.SemanticModel", Path(tmp) / "GoodModel.SemanticModel")
            u = build_usage(build_inventory(Path(tmp)))["models"][0]
            self.assertEqual(u["reportCoverage"], "none")
            self.assertIsNotNone(u["note"])


if __name__ == "__main__":
    unittest.main()
