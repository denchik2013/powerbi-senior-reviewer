"""Name lookups over an inventory model and DAX reference resolution (case-insensitive, like DAX)."""
from __future__ import annotations

from dataclasses import dataclass

import dax_lexer as dax


def k(name: str | None) -> str:
    return (name or "").casefold()


@dataclass
class DaxSource:
    """One piece of DAX in the model, with where it lives."""
    kind: str          # measure | calcColumn | calcTable | calcItem | rls | formatString
    owner: str         # object key, e.g. "measure:Sales[Total Sales]"
    table: str         # home table (row context for unqualified [col] in calc columns)
    expression: str
    file: str
    line: int          # file line of expression line 0


class ModelIndex:
    def __init__(self, model: dict):
        self.model = model
        self.tables = {k(t["name"]): t for t in model["tables"]}
        self.columns: dict[tuple[str, str], dict] = {}
        self.measures: dict[str, dict] = {}
        for t in model["tables"]:
            for c in t["columns"]:
                self.columns[(k(t["name"]), k(c["name"]))] = c
            for m in t["measures"]:
                self.measures[k(m["name"])] = m
        self._fact_tables: set[str] | None = None

    # ------------------------------------------------------------------ lookups
    def table(self, name: str) -> dict | None:
        return self.tables.get(k(name))

    def column(self, table: str, name: str) -> dict | None:
        return self.columns.get((k(table), k(name)))

    def measure(self, name: str) -> dict | None:
        return self.measures.get(k(name))

    def real_tables(self) -> list[dict]:
        return [t for t in self.model["tables"] if not t["isAutoDateTable"]]

    def fact_tables(self) -> set[str]:
        """Tables on the many side of at least one relationship and never on the one side."""
        if self._fact_tables is None:
            many, one = set(), set()
            for r in self.model["relationships"]:
                if r["toTable"].startswith(("LocalDateTable_", "DateTableTemplate_")):
                    continue
                if r["fromCardinality"] == "many":
                    many.add(k(r["fromTable"]))
                if r["toCardinality"] == "one":
                    one.add(k(r["toTable"]))
            self._fact_tables = many - one
        return self._fact_tables

    def relationship_columns(self) -> dict[tuple[str, str], list[dict]]:
        out: dict[tuple[str, str], list[dict]] = {}
        for r in self.model["relationships"]:
            out.setdefault((k(r["fromTable"]), k(r["fromColumn"])), []).append(r)
            out.setdefault((k(r["toTable"]), k(r["toColumn"])), []).append(r)
        return out

    # ------------------------------------------------------------------ DAX
    def dax_sources(self) -> list[DaxSource]:
        out: list[DaxSource] = []
        for t in self.model["tables"]:
            if t["isAutoDateTable"]:
                continue
            for m in t["measures"]:
                owner = f"measure:{t['name']}[{m['name']}]"
                out.append(DaxSource("measure", owner, t["name"], m["expression"], m["file"], m["exprLine"] or m["line"]))
                if m.get("formatStringExpression"):
                    out.append(DaxSource("formatString", owner, t["name"], m["formatStringExpression"], m["file"], m["line"]))
            for c in t["columns"]:
                if c["isCalculated"] and c["expression"]:
                    out.append(DaxSource("calcColumn", f"column:{t['name']}[{c['name']}]", t["name"], c["expression"],
                                         c["file"], c["exprLine"] or c["line"]))
            for p in t["partitions"]:
                if p["type"] == "calculated" and p["expression"]:
                    out.append(DaxSource("calcTable", f"table:{t['name']}", t["name"], p["expression"],
                                         p["file"], p["exprLine"] or p["line"]))
            for ci in t["calculationItems"]:
                out.append(DaxSource("calcItem", f"calcItem:{t['name']}/{ci['name']}", t["name"],
                                     ci["expression"] or "", ci["file"], ci["exprLine"] or ci["line"]))
        for role in self.model["roles"]:
            for tp in role["tablePermissions"]:
                if tp["expression"]:
                    out.append(DaxSource("rls", f"role:{role['name']}", tp["table"], tp["expression"],
                                         role["file"], tp["exprLine"] or tp["line"]))
        return out

    def references(self, src: DaxSource) -> list[tuple[str, str, str, int]]:
        """Resolve references in one DAX source -> [(kind, table, name, file_line)].

        kind is "column", "measure" or "table". Unresolvable names are skipped.
        """
        out = []
        var_names = dax.strip_var_names(src.expression)
        tokens = dax.tokenize(src.expression)
        for i, t in enumerate(tokens):
            line = src.line + t.line
            if t.type == "colref":
                col = self.column(t.table, t.column)
                if col:
                    out.append(("column", col["table"], col["name"], line))
                else:
                    m = self.measure(t.column)
                    if m:
                        out.append(("measure", m["table"], m["name"], line))
            elif t.type == "bracket":
                m = self.measure(t.column)
                if m:
                    out.append(("measure", m["table"], m["name"], line))
                elif src.kind == "calcColumn" or src.kind == "rls":
                    col = self.column(src.table, t.column)
                    if col:
                        out.append(("column", col["table"], col["name"], line))
            elif t.type in ("qtable", "ident"):
                nxt = tokens[i + 1] if i + 1 < len(tokens) else None
                if t.type == "ident" and (nxt is not None and nxt.type == "lparen"):
                    continue
                if t.type == "ident" and k(t.value) in var_names:
                    continue
                tbl = self.table(t.table)
                if tbl:
                    out.append(("table", tbl["name"], tbl["name"], line))
        return out

    def is_table_token(self, node) -> bool:
        """True if a DAX tree node is a bare reference to a model table."""
        return isinstance(node, dax.Token) and node.type in ("qtable", "ident") and self.table(node.table) is not None
