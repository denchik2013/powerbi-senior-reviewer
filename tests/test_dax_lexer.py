import unittest

import helpers  # noqa: F401
import dax_lexer as dax


class DaxLexerTests(unittest.TestCase):
    def test_colref_merging_and_strings(self):
        toks = dax.tokenize("CALCULATE([M], 'Dim Date'[Year] = 2023, Sales[Name] = \"a\"\"b\")")
        colrefs = [(t.table, t.column) for t in toks if t.type == "colref"]
        self.assertEqual(colrefs, [("Dim Date", "Year"), ("Sales", "Name")])
        self.assertIn('"a""b"', [t.value for t in toks if t.type == "string"])
        self.assertEqual([t.column for t in toks if t.type == "bracket"], ["M"])

    def test_return_bracket_not_merged(self):
        toks = dax.tokenize("VAR x = 1 RETURN [Total]")
        self.assertEqual([t.type for t in toks][-1], "bracket")

    def test_comments_and_strings_are_ignored_for_calls(self):
        tree = dax.parse('// IFERROR(x)\n/* FILTER(Sales, 1) */ "IFERROR(" & SUM(T[A])')
        self.assertEqual([c.name for c in dax.calls(tree)], ["SUM"])

    def test_line_numbers(self):
        toks = dax.tokenize("SUM(\n  T[A]\n) / 2")
        self.assertEqual(next(t for t in toks if t.type == "colref").line, 1)
        self.assertEqual(next(t for t in toks if t.value == "/").line, 2)

    def test_call_tree_arguments(self):
        tree = dax.parse("CALCULATE([M], FILTER(Sales, Sales[Q] > 10), ALL(Product))")
        calc = dax.calls(tree, "CALCULATE")[0]
        self.assertEqual(len(calc.args), 3)
        self.assertEqual(calc.args[1][0].name, "FILTER")
        self.assertEqual(calc.args[1][0].args[0][0].value, "Sales")
        self.assertEqual(calc.args[2][0].name, "ALL")

    def test_braces_and_nested_parens(self):
        tree = dax.parse("T[C] IN { \"a\", \"b\" } && ((1 + 2) * 3) > 0")
        groups = [n for n in dax.walk(tree) if isinstance(n, dax.Group)]
        self.assertEqual({g.kind for g in groups}, {"brace", "paren"})

    def test_var_names(self):
        self.assertEqual(dax.strip_var_names("VAR Sales = 1 var x2 = 2 RETURN Sales"), {"sales", "x2"})


if __name__ == "__main__":
    unittest.main()
