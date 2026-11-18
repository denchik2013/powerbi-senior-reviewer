#!/usr/bin/env python3
"""Regenerate the PBIR report folders (and project shells) of the test fixtures.

The TMDL semantic models are hand-written; the reports are generated here so the ~30
visual.json files stay consistent. Output is deterministic and committed to git.

    python3 tests/fixtures/build_report_fixtures.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json"


def lit(value) -> dict:
    if isinstance(value, bool):
        v = "true" if value else "false"
    elif isinstance(value, str):
        v = "'" + value.replace("'", "''") + "'"
    else:
        v = str(value)
    return {"expr": {"Literal": {"Value": v}}}


def col(table: str, name: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def mea(table: str, name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def agg(table: str, name: str, fn: int = 0) -> dict:
    return {"Aggregation": {"Expression": col(table, name), "Function": fn}}


def proj(field: dict) -> dict:
    inner = field.get("Column") or field.get("Measure") or field["Aggregation"]["Expression"]["Column"]
    ent = inner["Expression"]["SourceRef"]["Entity"]
    ref = f"{ent}.{inner['Property']}"
    if "Aggregation" in field:
        ref = f"Sum({ref})"
    return {"field": field, "queryRef": ref, "nativeQueryRef": inner["Property"]}


def visual(name: str, vtype: str, roles: dict[str, list[dict]], *, x=0, y=0, w=300, h=200,
           title: str | None = None, show_title: bool | None = None, alt: str | None = None,
           filters: list[dict] | None = None, links: list[str] | None = None) -> dict:
    v: dict = {
        "$schema": VC_SCHEMA,
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "height": h, "width": w, "tabOrder": 0},
        "visual": {"visualType": vtype},
    }
    if roles:
        v["visual"]["query"] = {"queryState": {r: {"projections": [proj(f) for f in fs]} for r, fs in roles.items()}}
    vco: dict = {}
    title_props = {}
    if show_title is not None:
        title_props["show"] = lit(show_title)
    if title is not None:
        title_props["text"] = lit(title)
    if title_props:
        vco["title"] = [{"properties": title_props}]
    if alt is not None:
        vco["general"] = [{"properties": {"altText": lit(alt)}}]
    if links:
        vco["visualLink"] = [{"properties": {"show": lit(True), "type": lit("PageNavigation"),
                                             "navigationSection": lit(links[0])}}]
    if vco:
        v["visual"]["visualContainerObjects"] = vco
    if filters:
        v["filterConfig"] = {"filters": filters}
    return v


def cat_filter(name: str, table: str, column: str, values: list[str], hidden: bool = False) -> dict:
    f = {
        "name": name,
        "field": col(table, column),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}}],
                "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values]}}}],
        },
    }
    if hidden:
        f["isHiddenInViewMode"] = True
    return f


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_project(name: str, pages: list[tuple[dict, list[dict]]], bookmarks: list[dict] | None = None,
                  gitignore: bool = True) -> None:
    proj_dir = HERE / name
    report = proj_dir / f"{name}.Report"
    if report.exists():
        shutil.rmtree(report)
    write(proj_dir / f"{name}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{name}.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    write(proj_dir / f"{name}.SemanticModel" / "definition.pbism", {"version": "4.2", "settings": {}})
    write(report / "definition.pbir", {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}})
    d = report / "definition"
    write(d / "version.json", {"version": "2.0.0"})
    write(d / "report.json", {
        "themeCollection": {"baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.59", "type": "SharedResources"}},
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True},
    })
    write(d / "pages" / "pages.json", {"pageOrder": [p["name"] for p, _ in pages], "activePageName": pages[0][0]["name"]})
    for page, visuals in pages:
        write(d / "pages" / page["name"] / "page.json", {"$schema": PAGE_SCHEMA, **page})
        for v in visuals:
            write(d / "pages" / page["name"] / "visuals" / v["name"] / "visual.json", v)
    for b in bookmarks or []:
        write(d / "bookmarks" / f"{b['name']}.bookmark.json", b)
    if gitignore:
        (proj_dir / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")


# ----------------------------------------------------------------------------- BadModel
def bad() -> None:
    S, C, P, D, ST, B = "Sales", "Customer", "Product", "Date", "dim_store", "FactBudget"
    overview = {"name": "ReportSection1", "displayName": "Overview", "displayOption": "FitToPage",
                "height": 720, "width": 1280}
    slicers = [
        visual(f"slicer{i}", "slicer", {"Values": [col(t, c)]}, x=10 + i * 150, y=10, w=140, h=60)
        for i, (t, c) in enumerate([(C, "Region"), (C, "Segment"), (P, "Category"), (P, "Color"),
                                    (D, "Year"), (D, "Month"), (ST, "Store Name")])
    ]
    cards = [
        visual(f"card{i}", "card", {"Values": [mea(t, m)]}, x=10 + i * 200, y=80, w=190, h=90)
        for i, (t, m) in enumerate([(S, "Total Sales"), (S, "Total Revenue"), (S, "Margin %"),
                                    (C, "Customer Count"), (S, "avg_price")])
    ]
    charts = [
        visual("barByCategory", "clusteredBarChart", {"Category": [col(P, "Category")], "Y": [mea(S, "Total Sales")]},
               x=10, y=180, w=400, h=250),
        visual("lineByMonth", "lineChart", {"Category": [col(D, "Month")], "Y": [mea(S, "Total Sales")]},
               x=420, y=180, w=400, h=250, show_title=False),
        visual("pieByProduct", "pieChart", {"Category": [col(P, "Product Name")], "Y": [mea(S, "Total Sales")]},
               x=830, y=180, w=400, h=250, title="Sales by product"),
        visual("customerTable", "tableEx", {"Values": [col(C, "Customer Name"), col(C, "Email"), col(C, "Phone"),
                                                       col(S, "OrderDateTime"), mea(S, "Total Sales")]},
               x=10, y=440, w=600, h=270, title="Customers",
               filters=[cat_filter("hiddenSegmentFilter", C, "Segment", ["Enterprise"], hidden=True)]),
        visual("qtyByRegion", "clusteredColumnChart", {"Category": [col(C, "Region")], "Y": [agg(S, "Quantity")]},
               x=620, y=440, w=600, h=270),
    ]
    header = visual("headerText", "textbox", {}, x=1100, y=10, w=170, h=60)
    budget = {"name": "ReportSection2", "displayName": "Budget", "displayOption": "FitToPage",
              "height": 720, "width": 1280}
    budget_visuals = [
        visual("budgetCard", "card", {"Values": [mea(B, "Budget Amount")]}, x=10, y=10, w=200, h=90,
               alt="Total budget for the selected filters"),
        visual("salesAmountCard", "card", {"Values": [mea(S, "Sales Amount")]}, x=220, y=10, w=200, h=90,
               alt="Total sales amount"),
        visual("bvaCard", "card", {"Values": [mea(B, "Budget vs Actual")]}, x=430, y=10, w=200, h=90,
               alt="Sales minus budget"),
        visual("budgetByProduct", "tableEx", {"Values": [col(P, "Product Name"), mea(B, "Budget Amount"),
                                                         mea(S, "Total Sales")]},
               x=10, y=110, w=620, h=300, title="Budget vs sales by product", alt="Budget and sales per product"),
        visual("kpiByYear", "tableEx", {"Values": [col(D, "Year"), mea(S, "Bulk Sales"), mea(S, "Avg Order Value"),
                                                   mea(S, "Sales 2023"), mea(S, "Contoso Sales"),
                                                   mea(S, "Sales % of Total"), mea(S, "Sales Growth %")]},
               x=640, y=110, w=620, h=300, title="KPIs by year", alt="Sales KPIs per year"),
    ]
    draft = {"name": "ReportSection3", "displayName": "Old Draft", "displayOption": "FitToPage",
             "height": 720, "width": 1280, "visibility": "HiddenInViewMode"}
    draft_visuals = [visual("draftCard", "card", {"Values": [mea(S, "Total Sales")]}, alt="Total sales")]
    write_project("BadModel", [(overview, slicers + cards + charts + [header]), (budget, budget_visuals),
                               (draft, draft_visuals)], gitignore=False)


# ----------------------------------------------------------------------------- GoodModel
def good() -> None:
    M, C, P, D = "_Measures", "Customer", "Product", "Date"
    overview = {"name": "a1f0c2d3e4b5a6978899", "displayName": "Sales Overview", "displayOption": "FitToPage",
                "height": 720, "width": 1280}
    visuals = [
        visual("slicerYear", "slicer", {"Values": [col(D, "Year")]}, x=10, y=10, w=200, h=60),
        visual("slicerRegion", "slicer", {"Values": [col(C, "Region")]}, x=220, y=10, w=200, h=60),
        visual("cardSales", "card", {"Values": [mea(M, "Sales Amount")]}, x=10, y=80, w=300, h=100,
               title="Net sales", alt="Net sales for the selected year and region"),
        visual("cardMargin", "card", {"Values": [mea(M, "Margin %")]}, x=320, y=80, w=300, h=100,
               title="Gross margin %", alt="Gross margin as a percentage of net sales"),
        visual("cardYoY", "card", {"Values": [mea(M, "Sales YoY %")]}, x=630, y=80, w=300, h=100,
               title="Growth vs last year", alt="Year-over-year growth of net sales"),
        visual("lineTrend", "lineChart", {"Category": [col(D, "Month")], "Y": [mea(M, "Sales Amount"), mea(M, "Sales PY")]},
               x=10, y=190, w=620, h=260, title="Net sales by month, this year vs last year",
               alt="Line chart comparing monthly net sales with the same month last year"),
        visual("barCategory", "clusteredBarChart", {"Category": [col(P, "Category")], "Y": [mea(M, "Sales Amount")]},
               x=640, y=190, w=620, h=260, title="Net sales by product category",
               alt="Bar chart of net sales per product category, largest first"),
        visual("tableProducts", "tableEx", {"Values": [col(P, "Product Name"), mea(M, "Sales Amount"),
                                                       mea(M, "Total Cost"), mea(M, "Margin")]},
               x=10, y=460, w=1250, h=250, title="Product profitability",
               alt="Table of net sales, cost and margin per product"),
    ]
    detail = {"name": "b2e1d3c4f5a6b7c8d9e0", "displayName": "Customer Detail", "displayOption": "FitToPage",
              "height": 720, "width": 1280, "visibility": "HiddenInViewMode",
              "pageBinding": {"name": "c3d4e5f6a7b8c9d0e1f2", "type": "Drillthrough",
                              "parameters": [{"name": "p1", "boundFilter": "f1", "fieldExpr": col(C, "Customer Name")}]}}
    detail_visuals = [
        visual("customerTable", "tableEx", {"Values": [col(C, "Customer Name"), col(C, "Region"), col(C, "Segment"),
                                                       mea(M, "Sales Amount"), mea(M, "Order Lines"),
                                                       mea(M, "Margin %")]},
               x=10, y=10, w=1250, h=500, title="Customer detail",
               alt="Region, segment, sales and margin for the selected customer"),
    ]
    write_project("GoodModel", [(overview, visuals), (detail, detail_visuals)])


if __name__ == "__main__":
    bad()
    good()
    print("fixtures regenerated")
