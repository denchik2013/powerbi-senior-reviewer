#!/usr/bin/env python3
"""Deterministic best-practice checks for a Power BI project (PBIP) -> findings.json.

Usage:
    python3 static_checks.py <path> [-o findings.json] [--scope scope.json]
                             [--disable RULE[,RULE...]] [--list-rules]

Each finding: id, severity, category, object, file, line, message, evidence, fix.
--scope takes the JSON written by diff_scope.py and keeps only findings on changed or
impacted objects (PR mode). Standard library only; no network access. Never modifies files.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dax_lexer as dax  # noqa: E402
from field_usage import compute_usage  # noqa: E402
from model_index import ModelIndex, k  # noqa: E402
from pbip_inventory import build_inventory, write_json  # noqa: E402
from pbir_parser import DECORATIVE_VISUALS, SLICER_VISUALS  # noqa: E402

SEVERITIES = ["critical", "high", "medium", "low", "nit"]
SEVERITY_WEIGHT = {"critical": 25, "high": 10, "medium": 4, "low": 1.5, "nit": 0.5}
CATEGORY_WEIGHT = {"Model": 0.25, "DAX": 0.25, "Power Query": 0.10, "Report": 0.15,
                   "Security": 0.15, "Governance": 0.10}

# id: (category, default severity, title)
RULES: dict[str, tuple[str, str, str]] = {
    "MOD001": ("Model", "high", "Bi-directional cross-filtering"),
    "MOD002": ("Model", "medium", "Many-to-many relationship"),
    "MOD003": ("Model", "high", "Auto date/time is enabled"),
    "MOD004": ("Model", "medium", "No table is marked as date table"),
    "MOD005": ("Model", "medium", "Relationship on text columns"),
    "MOD006": ("Model", "medium", "Relationship key columns are visible"),
    "MOD007": ("Model", "low", "Numeric ID/attribute column summarizes by default"),
    "MOD008": ("Model", "medium", "High-cardinality column (datetime with time / GUID)"),
    "MOD009": ("Model", "medium", "Row-level calculated column that belongs in Power Query"),
    "MOD010": ("Model", "low", "Unused columns"),
    "MOD011": ("Model", "low", "Money stored as Double instead of Fixed Decimal"),
    "MOD012": ("Model", "medium", "Inactive relationship never activated with USERELATIONSHIP"),
    "DAX001": ("DAX", "high", "FILTER over a whole table as CALCULATE filter"),
    "DAX002": ("DAX", "medium", "Division with / instead of DIVIDE"),
    "DAX003": ("DAX", "medium", "IFERROR / ISERROR"),
    "DAX004": ("DAX", "low", "Measures without format string"),
    "DAX005": ("DAX", "low", "Report measures without description"),
    "DAX006": ("DAX", "medium", "Nested iterators over a fact table"),
    "DAX007": ("DAX", "medium", "Hard-coded literals in measure filters"),
    "DAX008": ("DAX", "nit", "ALL used as CALCULATE modifier (prefer REMOVEFILTERS)"),
    "DAX009": ("DAX", "medium", "Implicit measures"),
    "DAX010": ("DAX", "nit", "Unused measures"),
    "PQ001": ("Power Query", "medium", "Hard-coded path / server instead of a parameter"),
    "PQ002": ("Power Query", "critical", "Credentials or secrets in M code"),
    "PQ003": ("Power Query", "low", "Table.Buffer"),
    "PQ004": ("Power Query", "low", "Repeated change-type steps"),
    "RPT001": ("Report", "medium", "Too many visuals on a page"),
    "RPT002": ("Report", "low", "Visuals without alt text"),
    "RPT003": ("Report", "low", "Visuals without a meaningful title"),
    "RPT004": ("Report", "low", "Hidden page that nothing navigates to"),
    "RPT005": ("Report", "medium", "Too many slicers on a page"),
    "RPT006": ("Report", "medium", "Hidden visual-level filter"),
    "SEC001": ("Security", "high", "Sensitive columns without RLS / OLS"),
    "SEC002": ("Security", "high", "RLS with hard-coded user identity"),
    "SEC003": ("Security", "low", "RLS uses USERNAME() instead of USERPRINCIPALNAME()"),
    "GOV001": ("Governance", "medium", "Power BI local cache/settings not git-ignored"),
    "GOV002": ("Governance", "low", "Measures not organised (no measure table / display folders)"),
    "GOV003": ("Governance", "low", "Inconsistent naming conventions"),
}

KEY_NAME = re.compile(r"(?:Key|ID|Id|SK|FK|PK)$|(?i:[_\s](?:key|id|sk|fk|pk)$|^(?:id|key)$)")
CALENDAR_ATTR = re.compile(r"(?i)(year|quarter|month|week|weekday)(\s?(number|no|num))?$")
MONEY_NAME = re.compile(r"(?i)amount|price|cost|revenue|sales|margin|profit|tax|discount|salary|fee|payment|balance|budget")
SENSITIVE = re.compile(r"(?i)e[-_ ]?mail|salary|wage|iban|\bssn\b|social.?security|passport|phone|mobile|"
                       r"date.?of.?birth|\bdob\b|birth.?date|credit.?card|card.?number|national.?id|tax.?id")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TIME_INTEL = {"DATESYTD", "DATESMTD", "DATESQTD", "TOTALYTD", "TOTALMTD", "TOTALQTD", "SAMEPERIODLASTYEAR",
              "DATEADD", "PARALLELPERIOD", "PREVIOUSYEAR", "PREVIOUSMONTH", "PREVIOUSQUARTER", "PREVIOUSDAY",
              "NEXTYEAR", "NEXTMONTH", "NEXTQUARTER", "NEXTDAY", "DATESINPERIOD", "DATESBETWEEN",
              "OPENINGBALANCEYEAR", "CLOSINGBALANCEYEAR", "STARTOFYEAR", "ENDOFYEAR", "STARTOFMONTH", "ENDOFMONTH"}
ITERATORS = {"SUMX", "AVERAGEX", "MINX", "MAXX", "COUNTX", "COUNTAX", "PRODUCTX", "CONCATENATEX", "RANKX",
             "FILTER", "ADDCOLUMNS", "GENERATE", "MEDIANX", "PERCENTILEX.INC", "PERCENTILEX.EXC"}
NOT_ROW_LEVEL = {"RELATED", "RELATEDTABLE", "LOOKUPVALUE", "CALCULATE", "CALCULATETABLE", "EARLIER", "EARLIEST",
                 "FILTER", "ALL", "ALLEXCEPT", "ALLSELECTED", "ALLNOBLANKROW", "VALUES", "DISTINCT", "SUM", "SUMX",
                 "AVERAGE", "AVERAGEX", "MIN", "MINX", "MAX", "MAXX", "COUNT", "COUNTX", "COUNTROWS", "COUNTA",
                 "COUNTAX", "COUNTBLANK", "DISTINCTCOUNT", "RANKX", "TOPN", "PATH", "PATHITEM", "PATHCONTAINS",
                 "PATHLENGTH", "USERELATIONSHIP", "SELECTEDVALUE", "CONCATENATEX", "SUMMARIZE", "ADDCOLUMNS",
                 "GENERATE", "CROSSJOIN", "USERPRINCIPALNAME", "USERNAME", "NOW", "TODAY", "UTCNOW", "RAND",
                 "RANDBETWEEN", "MAXA", "MINA", "AVERAGEA", "PRODUCT", "PRODUCTX", "MEDIAN", "MEDIANX"}
M_CONNECTORS = re.compile(
    r"\b(Sql\.Databases?|Oracle\.Database|PostgreSQL\.Database|MySQL\.Database|Snowflake\.Databases|"
    r"Odbc\.DataSource|Odbc\.Query|OleDb\.DataSource|AnalysisServices\.Databases?|Web\.Contents|"
    r"SharePoint\.(?:Files|Contents|Tables)|Folder\.(?:Files|Contents)|File\.Contents|AzureStorage\.\w+|"
    r"Databricks\.\w+|Teradata\.Database|DB2\.Database|OData\.Feed|AmazonRedshift\.Database|"
    r"GoogleBigQuery\.Database|Lakehouse\.Contents)\s*\(\s*\"")
M_SECRET = re.compile(r"(?i)\b(password|pwd|passwd|api[_-]?key|apikey|access[_-]?token|client[_-]?secret|"
                      r"secret|accountkey|sharedaccesssignature|sig)\s*=\s*[^;\"\s,\]]+|\bbearer\s+[A-Za-z0-9\-_.=]{8,}")
M_MASK = re.compile(r"(//[^\n]*|/\*.*?\*/)", re.S)
NO_TITLE_NEEDED = DECORATIVE_VISUALS | SLICER_VISUALS | {"card", "cardVisual", "multiRowCard", "kpi", "unknown"}


class Checker:
    def __init__(self, inventory: dict, disabled: set[str] | None = None):
        self.inv = inventory
        self.root = Path(inventory["root"])
        self.disabled = disabled or set()
        self.findings: list[dict] = []
        self._lines: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ helpers
    def src_line(self, file: str | None, line: int | None) -> str:
        if not file or not line:
            return ""
        if file not in self._lines:
            try:
                self._lines[file] = (self.root / file).read_text(encoding="utf-8-sig").splitlines()
            except OSError:
                self._lines[file] = []
        lines = self._lines[file]
        return lines[line - 1].strip() if 0 < line <= len(lines) else ""

    def add(self, rule: str, *, obj: str, obj_type: str, key: str, file: str | None, line: int | None,
            message: str, fix: str, evidence: str | list[str] | None = None, severity: str | None = None,
            keys: list[str] | None = None) -> None:
        if rule in self.disabled:
            return
        category, default_sev, title = RULES[rule]
        if evidence is None:
            evidence = self.src_line(file, line)
        self.findings.append({
            "id": rule, "title": title, "category": category, "severity": severity or default_sev,
            "object": obj, "objectType": obj_type, "objectKey": key, "objectKeys": keys or [key],
            "file": file, "line": line, "message": message, "evidence": evidence, "fix": fix,
        })

    # ------------------------------------------------------------------ run
    def run(self) -> list[dict]:
        for model in self.inv["models"]:
            if model["format"] != "tmdl":
                continue
            idx = ModelIndex(model)
            usage = compute_usage(model, self.inv)
            self.model_rules(model, idx, usage)
            self.dax_rules(model, idx, usage)
            self.pq_rules(model)
            self.security_rules(model, idx)
            self.governance_model_rules(model, idx)
        for report in self.inv["reports"]:
            self.report_rules(report)
        self.gitignore_rules()
        order = {s: i for i, s in enumerate(SEVERITIES)}
        self.findings.sort(key=lambda f: (order[f["severity"]], f["id"], f["file"] or "", f["line"] or 0))
        return self.findings

    # ================================================================== MODEL
    def model_rules(self, model: dict, idx: ModelIndex, usage: dict) -> None:
        rel_cols = idx.relationship_columns()
        for r in model["relationships"]:
            if r["toTable"].startswith(("LocalDateTable_", "DateTableTemplate_")):
                continue
            obj = f"{r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]"
            key = f"relationship:{r['name']}"
            m2m = r["fromCardinality"] == "many" and r["toCardinality"] == "many"
            if r["crossFilteringBehavior"].lower() == "bothdirections":
                sev = "medium" if m2m else ("low" if r["fromCardinality"] == r["toCardinality"] == "one" else "high")
                self.add("MOD001", obj=obj, obj_type="relationship", key=key, file=r["file"],
                         line=self._prop_line(r, "crossFilteringBehavior"), severity=sev,
                         message=f"Relationship {obj} filters in both directions. This creates ambiguous filter "
                                 "paths, slows queries and can leak data past RLS.",
                         fix="Set crossFilteringBehavior to oneDirection; where a measure really needs the reverse "
                             "filter use CALCULATE([Measure], CROSSFILTER(<from>, <to>, Both)).")
            if m2m:
                self.add("MOD002", obj=obj, obj_type="relationship", key=key, file=r["file"], line=r["line"],
                         message=f"{obj} is many-to-many. Totals can silently differ from the sum of rows and the "
                                 "grain mismatch is hidden from report authors.",
                         fix="Model a proper dimension (one row per key) between the two tables, or a bridge table "
                             "with two one-to-many relationships.")
            fc, tc = idx.column(r["fromTable"], r["fromColumn"]), idx.column(r["toTable"], r["toColumn"])
            if fc and tc and fc["dataType"] == "string" and tc["dataType"] == "string":
                self.add("MOD005", obj=obj, obj_type="relationship", key=key, file=r["file"], line=r["line"],
                         message=f"{obj} joins on text columns. Text keys compress worse and join slower than "
                                 "integer surrogate keys.",
                         fix="Add an integer surrogate key in the source or Power Query and relate on it; keep the "
                             "code as a visible attribute.")
            if not r["isActive"] and not self._userelationship_used(idx, r):
                self.add("MOD012", obj=obj, obj_type="relationship", key=key, file=r["file"],
                         line=self._prop_line(r, "isActive"),
                         message=f"Inactive relationship {obj} is not activated by any USERELATIONSHIP in the model, "
                                 "so it has no effect.",
                         fix=f"Use it in a measure: CALCULATE([Measure], USERELATIONSHIP({_ref(r['fromTable'], r['fromColumn'])}, "
                             f"{_ref(r['toTable'], r['toColumn'])})), or delete it.")

        st = model["settings"]
        if st.get("autoDateTime"):
            auto = [t["name"] for t in model["tables"] if t["isAutoDateTable"]]
            self.add("MOD003", obj="Model", obj_type="model", key="model:settings", file=st.get("file"),
                     line=st.get("autoDateTimeLine") or st.get("line"),
                     message=f"Auto date/time is on: Power BI builds a hidden date table for every date column "
                             f"({len(auto)} found). They bloat the model and give inconsistent time intelligence.",
                     fix="File > Options > Current file > Data load > uncheck Auto date/time "
                         "(annotation __PBI_TimeIntelligenceEnabled = 0), and use one marked Date table.")

        real = idx.real_tables()
        has_dates = any(c["dataType"] == "datetime" for t in real for c in t["columns"])
        marked = [t for t in real if (t.get("dataCategory") or "").lower() == "time"]
        if has_dates and not marked:
            ti_hits = [(s, c) for s in idx.dax_sources() for c in dax.calls(dax.parse(s.expression), *TIME_INTEL)]
            date_like = next((t for t in real if "date" in k(t["name"]) or "calendar" in k(t["name"])), None)
            target = date_like or real[0]
            self.add("MOD004", obj=target["name"], obj_type="table", key=f"table:{target['name']}",
                     file=target["file"], line=target["line"], severity="high" if ti_hits else "medium",
                     message="No table is marked as a date table." + (
                         f" {len(ti_hits)} time-intelligence call(s) (e.g. {ti_hits[0][1].name} in "
                         f"{ti_hits[0][0].owner.split(':', 1)[1]}) depend on a contiguous, marked calendar."
                         if ti_hits else ""),
                     fix=f"Mark '{target['name']}' as date table (Table tools > Mark as date table) so TMDL gets "
                         "`dataCategory: Time` and the date column `isKey`.")

        for t in real:
            if t["kind"] in ("calculationGroup",) or t["isFieldParameter"]:
                continue
            tvis = not t["isHidden"]
            many_side, one_side = [], []
            for c in t["columns"]:
                rels = rel_cols.get((k(t["name"]), k(c["name"])), [])
                rels = [r for r in rels if not r["toTable"].startswith(("LocalDateTable_", "DateTableTemplate_"))]
                if not rels or c["isHidden"] or not tvis:
                    continue
                is_many = any(k(r["fromTable"]) == k(t["name"]) and k(r["fromColumn"]) == k(c["name"])
                              and r["fromCardinality"] == "many" for r in rels)
                if is_many:
                    many_side.append(c)
                elif c["dataType"] != "datetime":
                    one_side.append(c)
            for cols, sev, side in ((many_side, "medium", "many (fact) side"), (one_side, "low", "one (dimension) side")):
                if cols:
                    self.add("MOD006", obj=t["name"], obj_type="table", key=f"table:{t['name']}",
                             keys=[f"column:{t['name']}[{c['name']}]" for c in cols],
                             file=cols[0]["file"], line=cols[0]["line"], severity=sev,
                             evidence=[f"{c['file']}:{c['line']}  {t['name']}[{c['name']}]" for c in cols],
                             message=f"Relationship key column(s) on the {side} are visible: "
                                     f"{', '.join(c['name'] for c in cols)}. Users pick them by mistake "
                                     "instead of the dimension attribute, and sliced fact keys filter incorrectly.",
                             fix="Add `isHidden` to each key column (keep the dimension attribute visible).")

        summ = []
        for t in real:
            for c in t["columns"]:
                if c["dataType"] not in ("int64", "decimal", "double") or (c["summarizeBy"] or "sum") == "none":
                    continue
                in_rel = (k(t["name"]), k(c["name"])) in rel_cols
                if in_rel or KEY_NAME.search(c["name"]) or CALENDAR_ATTR.search(c["name"]):
                    summ.append(c)
        if summ:
            self.add("MOD007", obj=model["name"], obj_type="model", key=f"column:{summ[0]['table']}[{summ[0]['name']}]",
                     keys=[f"column:{c['table']}[{c['name']}]" for c in summ], file=summ[0]["file"],
                     line=self._col_prop_line(summ[0], "summarizeBy"),
                     evidence=[f"{c['file']}:{self._col_prop_line(c, 'summarizeBy')}  {c['table']}[{c['name']}] "
                               f"summarizeBy: {c['summarizeBy'] or '(default = sum)'}" for c in summ],
                     message=f"{len(summ)} numeric key / calendar column(s) aggregate by default, so dragging them "
                             "into a visual shows a meaningless SUM (e.g. a total of years or product keys).",
                     fix="Set `summarizeBy: none` on these columns.")

        for t in real:
            if t["kind"] == "calculated":
                continue
            for c in t["columns"]:
                fs = (c["formatString"] or "").lower()
                reason = None
                if c["dataType"] == "datetime" and (fs == "general date" or re.search(r"h{1,2}:|:mm|\btt\b", fs)):
                    reason = f"datetime with a time part (formatString: {c['formatString']})"
                elif c["dataType"] == "datetime" and not fs and re.search(r"(?i)datetime|timestamp|created|modified|updated|_at$", c["name"]):
                    reason = "datetime column whose name suggests a time stamp"
                elif c["dataType"] == "string" and re.search(r"(?i)guid|uuid", c["name"]):
                    reason = "GUID text column"
                if reason:
                    in_rel = (k(t["name"]), k(c["name"])) in rel_cols
                    self.add("MOD008", obj=f"{t['name']}[{c['name']}]", obj_type="column",
                             key=f"column:{t['name']}[{c['name']}]", file=c["file"], line=c["line"],
                             severity="high" if in_rel else "medium",
                             message=f"{t['name']}[{c['name']}] is a {reason}. Near-unique values defeat VertiPaq "
                                     "compression and often dominate model size.",
                             fix="Split date and time into two columns (date + time rounded to the needed grain) in "
                                 "Power Query, or remove the GUID if no report needs it.")

        for t in real:
            if t["kind"] in ("calculated", "calculationGroup"):
                continue
            for c in t["columns"]:
                if not c["isCalculated"] or not c["expression"]:
                    continue
                if self._is_row_level(idx, t["name"], c["expression"]):
                    self.add("MOD009", obj=f"{t['name']}[{c['name']}]", obj_type="column",
                             key=f"column:{t['name']}[{c['name']}]", file=c["file"], line=c["line"],
                             message=f"Calculated column {t['name']}[{c['name']}] only uses columns of its own row. "
                                     "Computing it in DAX skips query folding and compresses worse than a source column.",
                             fix="Add it as a custom column in Power Query (or in the source view), e.g. "
                                 f"Table.AddColumn(prev, \"{c['name']}\", each ..., type number).")

        if usage["reportCoverage"] == "linked" and usage["unusedColumns"]:
            cols = usage["unusedColumns"]
            self.add("MOD010", obj=model["name"], obj_type="model", key=f"column:{cols[0]['table']}[{cols[0]['name']}]",
                     keys=[f"column:{c['table']}[{c['name']}]" for c in cols], file=cols[0]["file"],
                     line=cols[0]["line"],
                     evidence=[f"{c['file']}:{c['line']}  {c['table']}[{c['name']}]" for c in cols],
                     message=f"{len(cols)} column(s) are not used by any visual, filter, measure, relationship, RLS "
                             "rule, sort or hierarchy in this repository. Each one costs memory and refresh time.",
                     fix="Remove them in Power Query (Table.SelectColumns) after confirming no other report on this "
                         "model uses them.")

        money = [c for t in real for c in t["columns"] if c["dataType"] == "double" and MONEY_NAME.search(c["name"])]
        if money:
            self.add("MOD011", obj=model["name"], obj_type="model", key=f"column:{money[0]['table']}[{money[0]['name']}]",
                     keys=[f"column:{c['table']}[{c['name']}]" for c in money], file=money[0]["file"],
                     line=self._col_prop_line(money[0], "dataType"),
                     evidence=[f"{c['file']}:{self._col_prop_line(c, 'dataType')}  {c['table']}[{c['name']}] "
                               "dataType: double" for c in money],
                     message=f"{len(money)} currency-like column(s) use Double (floating point). Sums can drift by "
                             "fractions of a cent and Double compresses worse than Fixed Decimal.",
                     fix="Change the type to Fixed decimal number (Currency.Type in Power Query; `dataType: decimal`).")

    def _userelationship_used(self, idx: ModelIndex, r: dict) -> bool:
        pair = {(k(r["fromTable"]), k(r["fromColumn"])), (k(r["toTable"]), k(r["toColumn"]))}
        for src in idx.dax_sources():
            for call in dax.calls(dax.parse(src.expression), "USERELATIONSHIP"):
                refs = {(k(t.table), k(t.column)) for arg in call.args for t in arg
                        if isinstance(t, dax.Token) and t.type == "colref"}
                if refs == pair:
                    return True
        return False

    def _is_row_level(self, idx: ModelIndex, table: str, expr: str) -> bool:
        tree = dax.parse(expr)
        if any(c.name in NOT_ROW_LEVEL for c in dax.calls(tree)):
            return False
        for t in dax.walk(tree):
            if not isinstance(t, dax.Token):
                continue
            if t.type == "colref" and k(t.table) != k(table):
                return False
            if t.type == "bracket" and idx.measure(t.column):
                return False
            if t.type == "colref" and idx.measure(t.column) and not idx.column(t.table, t.column):
                return False
            if t.type in ("qtable",) and idx.table(t.table):
                return False
        return True

    def _prop_line(self, obj: dict, prop: str) -> int:
        start, end = obj.get("span") or [obj["line"], obj["line"]]
        for ln in range(start, end + 1):
            if self.src_line(obj["file"], ln).startswith(prop):
                return ln
        return obj["line"]

    def _col_prop_line(self, col: dict, prop: str) -> int:
        return self._prop_line(col, prop)

    # ================================================================== DAX
    def dax_rules(self, model: dict, idx: ModelIndex, usage: dict) -> None:
        facts = idx.fact_tables() or {k(t["name"]) for t in idx.real_tables()
                                       if re.search(r"(?i)fact|sales|orders|transactions", t["name"])}
        for src in idx.dax_sources():
            if src.kind not in ("measure", "calcItem", "calcColumn"):
                continue
            obj = src.owner.split(":", 1)[1]
            tokens = dax.tokenize(src.expression)
            tree = dax.build_tree(tokens)
            # DAX002 division operator
            if src.kind in ("measure", "calcItem"):
                divs = [t for i, t in enumerate(tokens) if t.type == "op" and t.value == "/"
                        and not (i + 1 < len(tokens) and tokens[i + 1].type == "number")]
                if divs:
                    line = src.line + divs[0].line
                    self.add("DAX002", obj=obj, obj_type=src.kind, key=src.owner, file=src.file, line=line,
                             message=f"{obj} divides with `/` ({len(divs)}x). A zero or blank denominator returns "
                                     "an error or infinity instead of BLANK.",
                             fix="Use DIVIDE(<numerator>, <denominator>) (optionally with an alternate result).")
            # DAX003 IFERROR / ISERROR
            errs = dax.calls(tree, "IFERROR", "ISERROR")
            if errs:
                self.add("DAX003", obj=obj, obj_type=src.kind, key=src.owner, file=src.file,
                         line=src.line + errs[0].line,
                         message=f"{obj} uses {errs[0].name}. Error trapping forces the slower formula engine and "
                                 "hides real data problems.",
                         fix="Prevent the error instead: DIVIDE for division, IF(ISBLANK(...)) / COALESCE for blanks, "
                             "or fix the data upstream.")
            if src.kind == "calcColumn":
                continue
            # DAX001 FILTER(<table>) inside CALCULATE
            for call in dax.calls(tree, "CALCULATE", "CALCULATETABLE"):
                for arg in call.args[1:]:
                    if len(arg) == 1 and isinstance(arg[0], dax.Call) and arg[0].name == "FILTER" and arg[0].args:
                        first = arg[0].args[0]
                        if len(first) == 1 and idx.is_table_token(first[0]):
                            tname = idx.table(first[0].table)["name"]
                            self.add("DAX001", obj=obj, obj_type=src.kind, key=src.owner, file=src.file,
                                     line=src.line + arg[0].line,
                                     message=f"{obj} passes FILTER({tname}, ...) to {call.name}. Filtering the whole "
                                             "table materialises every row (including expanded related columns) and "
                                             "changes semantics versus a column filter.",
                                     fix=f"Filter the column instead: {call.name}(<expr>, KEEPFILTERS(<column> <op> <value>)) "
                                         f"or FILTER(VALUES({tname}[Column]), ...) when a measure is the condition.")
            # DAX006 nested iterators over fact tables
            nested = self._nested_iterator(tree, idx, facts)
            if nested:
                outer, inner, fact = nested
                self.add("DAX006", obj=obj, obj_type=src.kind, key=src.owner, file=src.file,
                         line=src.line + inner.line,
                         message=f"{obj} nests {inner.name} inside {outer.name} over fact table {fact}. The inner "
                                 "iterator runs once per outer row: cost grows with rows squared.",
                         fix="Iterate the dimension or a pre-grouped table instead, e.g. "
                             "SUMX(VALUES(Sales[OrderID]), CALCULATE(...)), or precompute the line value.")
            # DAX007 hard-coded literals
            lits = self._hardcoded_literals(tokens)
            if lits and src.kind == "measure":
                self.add("DAX007", obj=obj, obj_type=src.kind, key=src.owner, file=src.file,
                         line=src.line + lits[0].line,
                         message=f"{obj} hard-codes {', '.join(t.value for t in lits[:3])}. The measure silently goes "
                                 "stale (next year, renamed customer) and duplicates what a slicer should do.",
                         fix="Drive it from the filter context (slicer, relative date logic such as "
                             "MAX('Date'[Year])) or a parameter / mapping table.")
            # DAX008 ALL as modifier
            for call in dax.calls(tree, "CALCULATE", "CALCULATETABLE"):
                hits = [a[0] for a in call.args[1:] if len(a) == 1 and isinstance(a[0], dax.Call) and a[0].name == "ALL"]
                if hits:
                    self.add("DAX008", obj=obj, obj_type=src.kind, key=src.owner, file=src.file,
                             line=src.line + hits[0].line,
                             message=f"{obj} uses ALL(...) as a {call.name} modifier. REMOVEFILTERS says the same "
                                     "thing and makes the intent obvious.",
                             fix="Replace ALL(...) with REMOVEFILTERS(...) inside CALCULATE.")
                    break

        visible_measures = [m for t in idx.real_tables() for m in t["measures"] if not m["isHidden"]]
        no_fmt = [m for m in visible_measures if not m["formatString"] and not m["formatStringExpression"]]
        if no_fmt:
            self.add("DAX004", obj=model["name"], obj_type="model",
                     key=f"measure:{no_fmt[0]['table']}[{no_fmt[0]['name']}]",
                     keys=[f"measure:{m['table']}[{m['name']}]" for m in no_fmt],
                     file=no_fmt[0]["file"], line=no_fmt[0]["line"],
                     evidence=[f"{m['file']}:{m['line']}  [{m['name']}]" for m in no_fmt],
                     message=f"{len(no_fmt)} visible measure(s) have no format string, so every visual shows raw "
                             "numbers and each report author formats them differently.",
                     fix="Add `formatString:` (e.g. `#,0`, `0.0%`, `\\$#,0.00`) to each measure.")
        used_in_report = {(k(u["table"]), k(u["name"])) for u in usage["measures"]
                          if any(b.startswith("visual") for b in u["usedBy"])}
        no_desc = [m for m in visible_measures if not m["description"] and (k(m["table"]), k(m["name"])) in used_in_report]
        if no_desc:
            self.add("DAX005", obj=model["name"], obj_type="model",
                     key=f"measure:{no_desc[0]['table']}[{no_desc[0]['name']}]",
                     keys=[f"measure:{m['table']}[{m['name']}]" for m in no_desc],
                     file=no_desc[0]["file"], line=no_desc[0]["line"],
                     evidence=[f"{m['file']}:{m['line']}  [{m['name']}]" for m in no_desc],
                     message=f"{len(no_desc)} measure(s) shown in the report have no description. Users see no "
                             "tooltip in the field list, and Copilot / Q&A have nothing to go on.",
                     fix="Add a `/// one-line business definition` above each measure.")

        implicit = []
        for rep in self.inv["reports"]:
            if rep.get("model") != model["name"]:
                continue
            for page in rep["pages"]:
                for v in page["visuals"]:
                    for f in v["fields"]:
                        if f.get("implicit"):
                            implicit.append((v, f))
        st = model["settings"]
        if implicit:
            v0 = implicit[0][0]
            self.add("DAX009", obj=model["name"], obj_type="model", key="model:settings",
                     keys=["model:settings"] + [f"visual:{v['page']}/{v['name']}" for v, _ in implicit],
                     file=v0["file"], line=v0["line"],
                     evidence=[f"{v['file']}  {v['type']} aggregates {f['table']}[{f['name']}] implicitly"
                               for v, f in implicit],
                     message=f"{len(implicit)} visual field(s) aggregate raw columns (implicit measures). They "
                             "bypass your measure logic and formatting, and break when calculation groups are added."
                             + ("" if st.get("discourageImplicitMeasures") else
                                " The model does not set discourageImplicitMeasures."),
                     fix="Create explicit measures (e.g. [Quantity] = SUM(Sales[Quantity])), use them in the visuals, "
                         "and add `discourageImplicitMeasures` to model.tmdl.")

        if usage["reportCoverage"] == "linked" and usage["unusedMeasures"]:
            ms = usage["unusedMeasures"]
            self.add("DAX010", obj=model["name"], obj_type="model", key=f"measure:{ms[0]['table']}[{ms[0]['name']}]",
                     keys=[f"measure:{m['table']}[{m['name']}]" for m in ms], file=ms[0]["file"], line=ms[0]["line"],
                     evidence=[f"{m['file']}:{m['line']}  [{m['name']}]" for m in ms],
                     message=f"{len(ms)} measure(s) are not used by any visual or other measure in this repository.",
                     fix="Delete them, or move work-in-progress measures to a hidden 'Dev' display folder.")

    def _iter_table(self, call: dax.Call, idx: ModelIndex) -> str | None:
        if not call.args or len(call.args[0]) != 1:
            return None
        node = call.args[0][0]
        if idx.is_table_token(node):
            return idx.table(node.table)["name"]
        if isinstance(node, dax.Call) and node.name in ("FILTER", "CALCULATETABLE", "RELATEDTABLE", "KEEPFILTERS"):
            return self._iter_table(node, idx)
        return None

    def _nested_iterator(self, tree, idx: ModelIndex, facts: set[str]):
        for outer in dax.calls(tree, *ITERATORS):
            otab = self._iter_table(outer, idx)
            for arg in outer.args[1:]:
                for inner in dax.calls(arg, *ITERATORS):
                    itab = self._iter_table(inner, idx)
                    for tab in (otab, itab):
                        if tab and k(tab) in facts:
                            return outer, inner, tab
        return None

    @staticmethod
    def _hardcoded_literals(tokens: list[dax.Token]) -> list[dax.Token]:
        hits = []
        for i, t in enumerate(tokens):
            if t.type == "number" and re.fullmatch(r"(19[9]\d|20\d\d|2100)", t.value):
                prev = tokens[i - 1] if i else None
                if prev is not None and (prev.type == "op" or prev.type in ("comma", "lparen")):
                    hits.append(t)
            elif t.type == "string" and t.value != '""':
                prev = tokens[i - 1] if i else None
                prev2 = tokens[i - 2] if i > 1 else None
                nxt = tokens[i + 1] if i + 1 < len(tokens) else None
                nxt2 = tokens[i + 2] if i + 2 < len(tokens) else None
                if prev and prev.type == "op" and prev.value in ("=", "==", "<>") and prev2 and prev2.type == "colref":
                    hits.append(t)
                elif nxt and nxt.type == "op" and nxt.value in ("=", "==", "<>") and nxt2 and nxt2.type == "colref":
                    hits.append(t)
        return hits

    # ================================================================== POWER QUERY
    def pq_rules(self, model: dict) -> None:
        queries = []
        for t in model["tables"]:
            if t["isAutoDateTable"]:
                continue
            for p in t["partitions"]:
                if p["type"] == "m" and p["expression"]:
                    queries.append((f"partition:{t['name']}/{p['name']}", f"{t['name']} (partition {p['name']})",
                                    p["expression"], p["file"], p["exprLine"] or p["line"], False))
        for e in model["expressions"]:
            queries.append((f"expression:{e['name']}", f"expression {e['name']}", e["expression"], e["file"],
                            e["exprLine"] or e["line"], e["isParameter"]))
        for key, obj, text, file, line0, is_param in queries:
            masked = M_MASK.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), text)
            secret_lines = set()
            for m in M_SECRET.finditer(masked):
                ln = line0 + masked.count("\n", 0, m.start())
                secret_lines.add(ln)
                self.add("PQ002", obj=obj, obj_type="query", key=key, file=file, line=ln,
                         evidence=_mask_secret(self.src_line(file, ln)),
                         message=f"{obj} contains what looks like a credential ({m.group(1) or 'bearer token'}). "
                                 "Anyone with the PBIP/PBIX or repo access can read it, and it stays in git history.",
                         fix="Remove it from M, store credentials in the Power BI data source settings / gateway, and "
                             "rotate the secret now: it is already in git history.")
            if is_param:
                continue
            literals = []
            for m in M_CONNECTORS.finditer(masked):
                ln = line0 + masked.count("\n", 0, m.start())
                if ln not in secret_lines:
                    literals.append((ln, m.group(1)))
            for m in re.finditer(r'(?<!#)"((?:[A-Za-z]:\\|\\\\)[^"]*)"', masked):
                ln = line0 + masked.count("\n", 0, m.start())
                if ln not in secret_lines and all(ln != x for x, _ in literals):
                    literals.append((ln, "path"))
            if literals:
                ln, fn = literals[0]
                self.add("PQ001", obj=obj, obj_type="query", key=key, file=file, line=ln,
                         evidence=[f"{file}:{x}  {self.src_line(file, x)}" for x, _ in literals],
                         message=f"{obj} hard-codes the source location in {fn}(...). Moving between dev/test/prod or "
                                 "another machine means editing M by hand.",
                         fix="Create text parameters (e.g. ServerName, DatabaseName, SourceFolder) and reference "
                             "them: Sql.Database(ServerName, DatabaseName). Deployment pipelines can then swap them.")
            buf = [m for m in re.finditer(r"\bTable\.Buffer\s*\(", masked)]
            if buf:
                ln = line0 + masked.count("\n", 0, buf[0].start())
                self.add("PQ003", obj=obj, obj_type="query", key=key, file=file, line=ln,
                         message=f"{obj} uses Table.Buffer. It stops query folding for every later step and holds the "
                                 "whole table in memory; it only helps when the same table is read repeatedly.",
                         fix="Remove Table.Buffer unless a later step iterates the table many times (List.Generate, "
                             "repeated lookups). Push filters and column selection before it.")
            ct = list(re.finditer(r"\bTable\.TransformColumnTypes\s*\(", masked))
            if len(ct) >= 2:
                ln = line0 + masked.count("\n", 0, ct[1].start())
                self.add("PQ004", obj=obj, obj_type="query", key=key, file=file, line=ln,
                         evidence=[f"{file}:{line0 + masked.count(chr(10), 0, c.start())}  "
                                   f"{self.src_line(file, line0 + masked.count(chr(10), 0, c.start()))}" for c in ct],
                         message=f"{obj} changes column types {len(ct)} times. Repeated auto-generated type steps "
                                 "add work and hide which type is final.",
                         fix="Keep a single Table.TransformColumnTypes step with every column's final type, ideally "
                             "right after the source is read.")

    # ================================================================== SECURITY
    def security_rules(self, model: dict, idx: ModelIndex) -> None:
        roles = model["roles"]
        covered_tables = {k(tp["table"]) for r in roles for tp in r["tablePermissions"]}
        covered_cols = {(k(cp["table"]), k(cp["column"])) for r in roles for cp in r["columnPermissions"]}
        sensitive = [c for t in idx.real_tables() for c in t["columns"] if SENSITIVE.search(c["name"])]
        exposed = [c for c in sensitive if not roles or
                   (k(c["table"]) not in covered_tables and (k(c["table"]), k(c["name"])) not in covered_cols)]
        if exposed:
            self.add("SEC001", obj=model["name"], obj_type="model",
                     key=f"column:{exposed[0]['table']}[{exposed[0]['name']}]",
                     keys=[f"column:{c['table']}[{c['name']}]" for c in exposed], file=exposed[0]["file"],
                     line=exposed[0]["line"], severity="high" if not roles else "medium",
                     evidence=[f"{c['file']}:{c['line']}  {c['table']}[{c['name']}]" for c in exposed],
                     message=(f"{len(exposed)} column(s) look like personal or sensitive data "
                              f"({', '.join(c['table'] + '[' + c['name'] + ']' for c in exposed[:4])}) and "
                              + ("the model has no roles at all." if not roles else
                                 "no role filters their table or hides them with object-level security.")),
                     fix="Remove the columns if reports do not need them; otherwise add OLS "
                         "(`columnPermission <Column> = none` in the role) or RLS on the table.")
        for r in roles:
            for tp in r["tablePermissions"]:
                expr = tp["expression"] or ""
                for t in dax.tokenize(expr):
                    if t.type == "string" and EMAIL.search(t.value):
                        self.add("SEC002", obj=f"role {r['name']} / {tp['table']}", obj_type="role",
                                 key=f"role:{r['name']}", file=r["file"], line=(tp["exprLine"] or tp["line"]) + t.line,
                                 message=f"Role '{r['name']}' filters {tp['table']} by a hard-coded e-mail {t.value}. "
                                         "Every new user or leaver needs a model change and redeploy.",
                                 fix="Use a mapping table (UserPrincipalName -> allowed key) and filter with "
                                     "[UserPrincipalName] = USERPRINCIPALNAME().")
                        break
                if any(c.name == "USERNAME" for c in dax.calls(dax.parse(expr))):
                    self.add("SEC003", obj=f"role {r['name']} / {tp['table']}", obj_type="role",
                             key=f"role:{r['name']}", file=r["file"], line=tp["exprLine"] or tp["line"],
                             message="USERNAME() returns DOMAIN\\user in Desktop/on-premises but UPN in the service, "
                                     "so the rule behaves differently across environments.",
                             fix="Use USERPRINCIPALNAME().")

    # ================================================================== GOVERNANCE
    def governance_model_rules(self, model: dict, idx: ModelIndex) -> None:
        real = idx.real_tables()
        visible = [m for t in real for m in t["measures"] if not m["isHidden"]]
        measure_tables = [t for t in real if t["measures"] and all(c["isHidden"] for c in t["columns"])]
        no_folder = [m for m in visible if not m["displayFolder"]]
        if len(visible) >= 6 and not measure_tables and len(no_folder) >= len(visible) / 2:
            homes = sorted({m["table"] for m in visible})
            self.add("GOV002", obj=model["name"], obj_type="model", key="model:settings",
                     file=visible[0]["file"], line=visible[0]["line"],
                     evidence=[f"{len(visible)} visible measures across {len(homes)} table(s): {', '.join(homes)}; "
                               f"{len(no_folder)} without displayFolder"],
                     message="Measures are scattered over data tables without display folders, so users hunt for "
                             "KPIs in the field list and authors create duplicates.",
                     fix="Create a dedicated measure table (e.g. `_Measures`) and group measures with `displayFolder:`.")
        styles: dict[str, list[str]] = {}
        for t in real:
            if t["isHidden"]:
                continue
            for style in _name_styles(t["name"], is_table=True):
                styles.setdefault(style, []).append(f"table {t['name']}")
            for c in t["columns"]:
                if not c["isHidden"]:
                    for style in _name_styles(c["name"]):
                        styles.setdefault(style, []).append(f"{t['name']}[{c['name']}]")
            for m in t["measures"]:
                if not m["isHidden"]:
                    for style in _name_styles(m["name"]):
                        styles.setdefault(style, []).append(f"[{m['name']}]")
        if len(styles) >= 2:
            first = next(t for t in real if not t["isHidden"])
            self.add("GOV003", obj=model["name"], obj_type="model", key="model:settings",
                     file=first["file"], line=first["line"],
                     evidence=[f"{s}: {', '.join(v[:4])}{' ...' if len(v) > 4 else ''}" for s, v in sorted(styles.items())],
                     message=f"Visible names mix {len(styles)} styles ({', '.join(sorted(styles))}). Business users "
                             "read field names; inconsistent ones look unfinished and are hard to search.",
                     fix="Pick one convention for visible objects (usually 'Title Case With Spaces', no dim/fact "
                         "prefixes) and rename; hide technical columns instead of renaming them.")

    def gitignore_rules(self) -> None:
        targets = []
        for m in self.inv["models"]:
            targets += [(m["path"], f"{m['path']}/.pbi/cache.abf", "critical"),
                        (m["path"], f"{m['path']}/.pbi/localSettings.json", "low")]
        for r in self.inv["reports"]:
            targets.append((r["path"], f"{r['path']}/.pbi/localSettings.json", "low"))
        problems = []
        worst = "low"
        for owner, rel, tracked_sev in targets:
            ignored, tracked = _git_ignore_status(self.root, rel)
            if tracked:
                problems.append(f"{rel} is committed")
                if SEVERITIES.index(tracked_sev) < SEVERITIES.index(worst):
                    worst = tracked_sev
            elif not ignored:
                problems.append(f"{rel} is not ignored")
                if SEVERITIES.index("medium") < SEVERITIES.index(worst):
                    worst = "medium"
        if problems:
            self.add("GOV001", obj="repository", obj_type="repository", key="repo:gitignore", file=".gitignore",
                     line=None, severity=worst, evidence=problems,
                     message="Power BI Desktop writes a local data cache (.pbi/cache.abf, which contains imported "
                             "data) and per-user settings next to the project. They must never reach git.",
                     fix="Add to .gitignore:\n**/.pbi/localSettings.json\n**/.pbi/cache.abf\n"
                         "and if already committed: git rm --cached <file> (and purge history if cache.abf held "
                         "real data).")

    # ================================================================== REPORT
    def report_rules(self, report: dict) -> None:
        all_links = {ln for p in report["pages"] for v in p["visuals"] for ln in v["links"]}
        all_links |= {b["targetPage"] for b in report["bookmarks"] if b.get("targetPage")}
        report_text = self._report_text(report)
        for page in report["pages"]:
            pname = page["displayName"]
            pkey = f"page:{page['name']}"
            vis = [v for v in page["visuals"] if not v["isGroup"] and not v["isHidden"]]
            data_vis = [v for v in vis if v["type"] not in DECORATIVE_VISUALS]
            if len(data_vis) > 15:
                self.add("RPT001", obj=pname, obj_type="page", key=pkey, file=page["file"], line=page["line"],
                         evidence=f"{len(data_vis)} visuals (excluding shapes/text boxes): "
                                  + ", ".join(sorted({v['type'] for v in data_vis})),
                         message=f"Page '{pname}' has {len(data_vis)} visuals. Every visual is at least one query; "
                                 "the page renders slowly and the reader cannot tell what matters.",
                         fix="Keep ~6-10 visuals that answer one question; move detail to drill-through or tooltip "
                             "pages.")
            slicers = [v for v in vis if v["type"] in SLICER_VISUALS]
            if len(slicers) > 6:
                self.add("RPT005", obj=pname, obj_type="page", key=pkey, file=page["file"], line=page["line"],
                         evidence=f"{len(slicers)} slicers: " + ", ".join(
                             f"{f['table']}[{f['name']}]" for v in slicers for f in v["fields"][:1]),
                         message=f"Page '{pname}' has {len(slicers)} slicers. They crowd the canvas and each fires "
                                 "its own query on every interaction.",
                         fix="Move secondary filters into the filter pane or a collapsible slicer panel (bookmarks), "
                             "keep 3-5 key slicers.")
            no_alt = [v for v in data_vis if v["type"] not in SLICER_VISUALS and not v["altText"]]
            if no_alt:
                self.add("RPT002", obj=pname, obj_type="page", key=pkey,
                         keys=[pkey] + [f"visual:{page['name']}/{v['name']}" for v in no_alt],
                         file=no_alt[0]["file"], line=no_alt[0]["line"],
                         evidence=[f"{v['file']}  {v['type']}" for v in no_alt],
                         message=f"{len(no_alt)} visual(s) on '{pname}' have no alt text; screen-reader users get "
                                 "only the visual type.",
                         fix="Format visual > General > Alt text: one sentence on what the visual shows "
                             "(it can be a measure for dynamic text).")
            no_title = []
            for v in data_vis:
                if v["type"] in NO_TITLE_NEEDED:
                    continue
                if v["title"]["show"] is False:
                    no_title.append((v, "title hidden"))
                elif not v["title"]["text"]:
                    no_title.append((v, "auto-generated title"))
            if no_title:
                self.add("RPT003", obj=pname, obj_type="page", key=pkey,
                         keys=[pkey] + [f"visual:{page['name']}/{v['name']}" for v, _ in no_title],
                         file=no_title[0][0]["file"], line=no_title[0][0]["title"]["line"] or no_title[0][0]["line"],
                         evidence=[f"{v['file']}  {v['type']}: {why}" for v, why in no_title],
                         message=f"{len(no_title)} chart(s) on '{pname}' have no title or only the generated one "
                                 "(\"Sum of X by Y\"), which states the fields, not the insight.",
                         fix="Give each chart a title that states the question it answers, e.g. "
                             "'Net sales by month, this year vs last year'.")
            for v in vis:
                hidden = [f for f in v["filters"] if f["hidden"] and f["hasCondition"]]
                if hidden:
                    f0 = hidden[0]
                    self.add("RPT006", obj=f"{pname}/{v['name']}", obj_type="visual",
                             key=f"visual:{page['name']}/{v['name']}", file=v["file"], line=f0["line"],
                             evidence=[f"{v['file']}:{f['line']}  hidden filter on "
                                       + ", ".join(f"{x['table']}[{x['name']}]" for x in f['fields'][:1]) for f in hidden],
                             message=f"Visual {v['type']} on '{pname}' has {len(hidden)} hidden filter(s). Readers see "
                                     "numbers that do not match the rest of the page with no visible reason.",
                             fix="Make the filter visible in the filter pane, or state it in the visual title "
                                 "(e.g. 'Enterprise customers').")
            if page["hidden"] and page["type"] not in ("drillthrough", "tooltip"):
                referenced = page["name"] in all_links or self._mentioned(report_text, page)
                if not referenced:
                    self.add("RPT004", obj=pname, obj_type="page", key=pkey, file=page["file"], line=page["line"],
                             evidence=self.src_line(page["file"], self._find(page["file"], "visibility")),
                             message=f"Page '{pname}' is hidden and no button, bookmark or drill-through leads to it. "
                                     "It is dead weight that still gets deployed and maintained.",
                             fix="Delete the page, or wire it up (page navigation button / drill-through) if users "
                                 "need it.")

    def _find(self, file: str, needle: str) -> int | None:
        try:
            for i, line in enumerate((self.root / file).read_text(encoding="utf-8-sig").splitlines(), 1):
                if needle in line:
                    return i
        except OSError:
            pass
        return None

    def _report_text(self, report: dict) -> dict[str, str]:
        out = {}
        for page in report["pages"]:
            for v in page["visuals"]:
                try:
                    out[v["file"]] = (self.root / v["file"]).read_text(encoding="utf-8-sig")
                except OSError:
                    pass
        for b in report["bookmarks"]:
            try:
                out[b["file"]] = (self.root / b["file"]).read_text(encoding="utf-8-sig")
            except OSError:
                pass
        return out

    @staticmethod
    def _mentioned(texts: dict[str, str], page: dict) -> bool:
        own = page["file"].rsplit("/", 1)[0]
        needle = f'"{page["name"]}"'
        return any(needle in txt for f, txt in texts.items() if not f.startswith(own + "/"))


# ---------------------------------------------------------------------- module helpers
def _ref(table: str, column: str) -> str:
    t = f"'{table}'" if re.search(r"[^A-Za-z0-9_]", table) else table
    return f"{t}[{column}]"


def _mask_secret(line: str) -> str:
    return M_SECRET.sub(lambda m: (m.group(1) + "=***") if m.group(1) else "Bearer ***", line)


def _name_styles(name: str, is_table: bool = False) -> list[str]:
    n = name.lstrip("_#@ ")
    out = []
    if is_table and re.match(r"^(dim|fact|tbl|vw|lkp|d|f)(_|[A-Z])", n):
        out.append("dim/fact prefixes")
    if " " in n:
        out.append("Spaced Words")
    elif "_" in n:
        out.append("snake_case")
    elif re.match(r"^[a-z]+[A-Z]", n):
        out.append("camelCase")
    elif re.match(r"^[A-Z][a-z0-9]+[A-Z]", n):
        out.append("PascalCase")
    return out


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None


def _git_ignore_status(root: Path, rel: str) -> tuple[bool, bool]:
    """(ignored, tracked) for a path relative to root, using git when available."""
    target = (root / rel)
    start = target.parent
    while not start.exists() and start != start.parent:
        start = start.parent
    top = _git(["rev-parse", "--show-toplevel"], start)
    if top is not None and top.returncode == 0:
        top_dir = Path(top.stdout.strip())
        try:
            rel_top = target.resolve().relative_to(top_dir.resolve()).as_posix()
        except ValueError:
            rel_top = None
        if rel_top:
            ign = _git(["check-ignore", "-q", "--no-index", rel_top], top_dir)
            trk = _git(["ls-files", "--error-unmatch", rel_top], top_dir)
            return (ign is not None and ign.returncode == 0), (trk is not None and trk.returncode == 0)
    return _fallback_ignored(target, root), False


def _fallback_ignored(target: Path, stop: Path) -> bool:
    ignored = False
    dirs = []
    d = target.parent
    while True:
        dirs.append(d)
        if d == stop or d.parent == d:
            break
        d = d.parent
    for d in reversed(dirs):  # outer .gitignore first, inner ones override
        gi = d / ".gitignore"
        if not gi.exists():
            continue
        rel = target.relative_to(d).as_posix()
        for raw in gi.read_text(encoding="utf-8", errors="replace").splitlines():
            pat = raw.strip()
            if not pat or pat.startswith("#"):
                continue
            neg = pat.startswith("!")
            pat = pat[1:] if neg else pat
            if _gitignore_match(pat, rel):
                ignored = not neg
    return ignored


def _gitignore_match(pat: str, rel: str) -> bool:
    anchored = pat.startswith("/") or "/" in pat.strip("/").replace("**/", "")
    pat = pat.strip("/")
    if pat.startswith("**/"):
        pat, anchored = pat[3:], False
    pat = pat.replace("**", "*")
    parts = rel.split("/")
    for i in range(len(parts)):
        if anchored and i > 0:
            break
        for j in range(i + 1, len(parts) + 1):
            if fnmatch.fnmatchcase("/".join(parts[i:j]), pat):
                return True
    return False


def scores(findings: list[dict], inventory: dict) -> dict:
    has_report = bool(inventory["reports"])
    out = {}
    for cat in CATEGORY_WEIGHT:
        if cat == "Report" and not has_report:
            out[cat] = None
            continue
        penalty = sum(SEVERITY_WEIGHT[f["severity"]] for f in findings if f["category"] == cat)
        out[cat] = max(0, round(100 - penalty))
    present = {c: s for c, s in out.items() if s is not None}
    total_w = sum(CATEGORY_WEIGHT[c] for c in present)
    overall = round(sum(present[c] * CATEGORY_WEIGHT[c] for c in present) / total_w) if total_w else None
    if any(f["severity"] == "critical" for f in findings) and overall is not None:
        overall = min(overall, 60)  # a leaked secret or committed data cache caps the score
    return {"overall": overall, "byCategory": out,
            "formula": "category = 100 - sum(weights: critical 25, high 10, medium 4, low 1.5, nit 0.5); "
                       "overall = weighted mean (Model .25, DAX .25, Power Query .10, Report .15, Security .15, "
                       "Governance .10), capped at 60 if any critical finding."}


def run_checks(inventory: dict, disabled: set[str] | None = None, scope: dict | None = None) -> dict:
    findings = Checker(inventory, disabled).run()
    if scope is not None:
        keys = set(scope.get("scopeKeys", []))
        findings = [f for f in findings if keys.intersection(f["objectKeys"])]
    by_sev = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
    by_cat = {c: sum(1 for f in findings if f["category"] == c) for c in CATEGORY_WEIGHT}
    warnings = list(inventory.get("warnings", []))
    for m in inventory["models"]:
        warnings += [f"{m['name']}: {w}" for w in m["warnings"]]
    for r in inventory["reports"]:
        warnings += [f"{r['name']}: {w}" for w in r["warnings"]]
    return {
        "schema_version": 1,
        "tool": "static_checks",
        "mode": "pr" if scope is not None else "full",
        "summary": {"total": len(findings), "bySeverity": by_sev, "byCategory": by_cat},
        "scores": scores(findings, inventory),
        "warnings": warnings,
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="PBIP project folder")
    ap.add_argument("--inventory", help="reuse inventory.json from pbip_inventory.py")
    ap.add_argument("--scope", help="scope.json from diff_scope.py (PR mode)")
    ap.add_argument("--disable", default="", help="comma-separated rule ids to skip")
    ap.add_argument("--list-rules", action="store_true")
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    if args.list_rules:
        for rid, (cat, sev, title) in RULES.items():
            print(f"{rid:7} {sev:8} {cat:12} {title}")
        return 0
    if args.inventory:
        inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    elif args.path:
        inv = build_inventory(Path(args.path))
    else:
        ap.error("path or --inventory is required")
    scope = json.loads(Path(args.scope).read_text(encoding="utf-8")) if args.scope else None
    disabled = {r.strip().upper() for r in args.disable.split(",") if r.strip()}
    result = run_checks(inv, disabled, scope)
    write_json(result, args.output)
    if args.output:
        s = result["summary"]["bySeverity"]
        print(f"findings: {result['summary']['total']} ("
              + ", ".join(f"{v} {k_}" for k_, v in s.items() if v) + f"), health score {result['scores']['overall']}"
              f" -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
