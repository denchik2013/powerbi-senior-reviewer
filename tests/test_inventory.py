import json
import tempfile
import unittest
from pathlib import Path

import helpers
from pbip_inventory import build_inventory, main


class InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bad = build_inventory(helpers.BAD)
        cls.good = build_inventory(helpers.GOOD)

    def table(self, inv, name):
        return next(t for t in inv["models"][0]["tables"] if t["name"] == name)

    def test_discovers_model_and_report_and_links_them(self):
        self.assertEqual(len(self.bad["models"]), 1)
        self.assertEqual(len(self.bad["reports"]), 1)
        self.assertEqual(self.bad["reports"][0]["model"], "BadModel")
        self.assertEqual(self.bad["stats"]["visuals"], 24)

    def test_paths_are_relative_and_posix(self):
        m = self.table(self.bad, "Sales")["measures"][0]
        self.assertEqual(m["file"], "BadModel.SemanticModel/definition/tables/Sales.tmdl")
        self.assertEqual(m["line"], 4)

    def test_line_numbers_point_at_declarations(self):
        sales = self.table(self.bad, "Sales")
        lines = (helpers.BAD / sales["file"]).read_text(encoding="utf-8").splitlines()
        for obj in sales["measures"] + sales["columns"]:
            self.assertIn(obj["name"].split()[0].strip("'"), lines[obj["line"] - 1], obj["name"])

    def test_table_kinds_and_flags(self):
        self.assertEqual(self.table(self.bad, "Sales")["kind"], "import")
        self.assertEqual(self.table(self.bad, "Date")["kind"], "calculated")
        auto = [t for t in self.bad["models"][0]["tables"] if t["isAutoDateTable"]]
        self.assertEqual(len(auto), 1)
        self.assertEqual(self.table(self.good, "Date")["dataCategory"], "Time")

    def test_model_settings_read_top_level_annotations(self):
        self.assertTrue(self.bad["models"][0]["settings"]["autoDateTime"])
        self.assertFalse(self.good["models"][0]["settings"]["autoDateTime"])
        self.assertTrue(self.good["models"][0]["settings"]["discourageImplicitMeasures"])

    def test_columns_measures_relationships_roles(self):
        line_total = next(c for c in self.table(self.bad, "Sales")["columns"] if c["name"] == "Line Total")
        self.assertTrue(line_total["isCalculated"])
        rel = next(r for r in self.bad["models"][0]["relationships"] if r["crossFilteringBehavior"] == "bothDirections")
        self.assertEqual((rel["fromTable"], rel["fromColumn"], rel["toTable"]), ("Sales", "customer_code", "Customer"))
        inactive = [r for r in self.bad["models"][0]["relationships"] if not r["isActive"]]
        self.assertEqual(len(inactive), 1)
        role = self.good["models"][0]["roles"][0]
        self.assertEqual(role["columnPermissions"][0]["column"], "Email")
        self.assertIn("USERPRINCIPALNAME()", role["tablePermissions"][0]["expression"])
        exprs = self.good["models"][0]["expressions"]
        self.assertTrue(all(e["isParameter"] for e in exprs))

    def test_measure_description(self):
        m = self.table(self.good, "_Measures")["measures"][0]
        self.assertEqual(m["description"], "Net sales: quantity times net unit price, after discounts.")

    def test_report_visuals(self):
        pages = self.bad["reports"][0]["pages"]
        self.assertEqual([p["displayName"] for p in pages], ["Overview", "Budget", "Old Draft"])
        self.assertTrue(pages[2]["hidden"])
        table = next(v for v in pages[0]["visuals"] if v["name"] == "customerTable")
        self.assertEqual(table["title"]["text"], "Customers")
        self.assertTrue(table["filters"][0]["hidden"])
        qty = next(v for v in pages[0]["visuals"] if v["name"] == "qtyByRegion")
        self.assertTrue(any(f["implicit"] for f in qty["fields"]))
        drill = self.good["reports"][0]["pages"][1]
        self.assertEqual(drill["type"], "drillthrough")

    def test_legacy_report_is_limited_with_warning(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            rep = Path(tmp) / "Old.Report"
            rep.mkdir()
            visual_conf = {"name": "v1", "singleVisual": {"visualType": "barChart", "prototypeQuery": {
                "From": [{"Name": "s", "Entity": "Sales"}],
                "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": "Amount"}}]}}}
            (rep / "report.json").write_text(json.dumps({"sections": [{
                "name": "ReportSection", "displayName": "Page 1",
                "visualContainers": [{"config": json.dumps(visual_conf)}]}]}), encoding="utf-8")
            inv = build_inventory(Path(tmp))
            r = inv["reports"][0]
            self.assertEqual(r["format"], "legacy")
            self.assertTrue(r["warnings"])
            self.assertEqual(r["pages"][0]["visuals"][0]["fields"][0]["table"], "Sales")

    def test_tmsl_model_gets_warning(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            m = Path(tmp) / "X.SemanticModel"
            m.mkdir()
            (m / "model.bim").write_text("{}", encoding="utf-8")
            inv = build_inventory(Path(tmp))
            self.assertEqual(inv["models"][0]["format"], "tmsl")
            self.assertTrue(inv["models"][0]["warnings"])

    def test_cli_writes_file_and_exit_code_when_nothing_found(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out = Path(tmp) / "inv.json"
            self.assertEqual(main([str(helpers.GOOD), "-o", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertEqual(main([tmp, "-o", str(Path(tmp) / "x.json")]), 2)


if __name__ == "__main__":
    unittest.main()
