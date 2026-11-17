import unittest

import helpers  # noqa: F401  (sets sys.path)
from tmdl_parser import parse_column_ref, parse_tmdl

SAMPLE = """/// Fact table
/// with two lines
table 'Sales ''Live'''
\tlineageTag: abc

\tmeasure 'Total Sales' = SUM(Sales[Amount])
\t\tformatString: #,0
\t\tdisplayFolder: KPIs\\Revenue

\tmeasure Ratio =
\t\t\tVAR x = [Total Sales]

\t\t\tRETURN
\t\t\t\tDIVIDE(x, 2)
\t\tformatString: 0.0%

\tmeasure Fenced = ```
\t\t\tCALCULATE(
\t\t\t    [Total Sales]
\t\t\t)
\t\t\t```
\t\tisHidden

\tcolumn Amount
\t\tdataType: decimal
\t\tisHidden
\t\tsummarizeBy: none

\tpartition Sales = m
\t\tmode: import
\t\tsource =
\t\t\t\tlet
\t\t\t\t    Source = 1
\t\t\t\tin
\t\t\t\t    Source

ref table Other
"""


class TmdlParserTests(unittest.TestCase):
    def setUp(self):
        self.nodes = parse_tmdl(SAMPLE)
        self.table = self.nodes[0]

    def test_quoted_name_and_description(self):
        self.assertEqual(self.table.kind, "table")
        self.assertEqual(self.table.name, "Sales 'Live'")
        self.assertEqual(self.table.description, "Fact table\nwith two lines")
        self.assertEqual(self.table.line, 3)

    def test_single_line_measure(self):
        m = self.table.objects("measure")[0]
        self.assertEqual((m.name, m.expression, m.line), ("Total Sales", "SUM(Sales[Amount])", 6))
        self.assertEqual(m.prop("formatString"), "#,0")
        self.assertEqual(m.prop("displayFolder"), "KPIs\\Revenue")

    def test_multiline_expression_keeps_inner_blank_line_and_line_mapping(self):
        m = self.table.objects("measure")[1]
        self.assertEqual(m.expr_line, 11)
        lines = m.expression.split("\n")
        self.assertEqual(lines[0], "VAR x = [Total Sales]")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[3], "\tDIVIDE(x, 2)")
        self.assertEqual(m.prop("formatString"), "0.0%")
        self.assertEqual(m.end_line, 15)

    def test_fenced_expression(self):
        m = self.table.objects("measure")[2]
        self.assertEqual(m.expression, "CALCULATE(\n    [Total Sales]\n)")
        self.assertEqual(m.expr_line, 18)
        self.assertTrue(m.flag("isHidden"))

    def test_column_flags_and_props(self):
        c = self.table.objects("column")[0]
        self.assertTrue(c.flag("isHidden"))
        self.assertEqual(c.prop("dataType"), "decimal")
        self.assertIsNone(c.expression)

    def test_partition_source_property_expression(self):
        p = self.table.objects("partition")[0]
        self.assertEqual(p.expression, "m")
        src = p.child_expr("source")
        self.assertTrue(src.expression.startswith("let\n    Source = 1"))
        self.assertEqual(src.expr_line, 32)
        self.assertEqual(p.end_line, 35)

    def test_ref_declaration(self):
        self.assertEqual((self.nodes[1].kind, self.nodes[1].name), ("ref table", "Other"))

    def test_space_indentation(self):
        nodes = parse_tmdl("table T\n    column C\n        dataType: string\n")
        self.assertEqual(nodes[0].objects("column")[0].prop("dataType"), "string")

    def test_crlf_line_endings(self):
        nodes = parse_tmdl("table T\r\n\tmeasure M = 1\r\n\t\tformatString: 0\r\n")
        self.assertEqual(nodes[0].objects("measure")[0].prop("formatString"), "0")

    def test_column_refs(self):
        self.assertEqual(parse_column_ref("Sales.CustomerKey"), ("Sales", "CustomerKey"))
        self.assertEqual(parse_column_ref("'Dim Date'.'Date Key'"), ("Dim Date", "Date Key"))
        self.assertEqual(parse_column_ref("Sales.'Order Date'"), ("Sales", "Order Date"))
        self.assertEqual(parse_column_ref("'LocalDateTable_1-2'.Date"), ("LocalDateTable_1-2", "Date"))


if __name__ == "__main__":
    unittest.main()
