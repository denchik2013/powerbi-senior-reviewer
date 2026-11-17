#!/usr/bin/env python3
"""Build an inventory of a Power BI project (PBIP): TMDL semantic model + PBIR report.

Usage:
    python3 pbip_inventory.py <path> [-o inventory.json]

<path> may be a folder containing *.pbip files, a *.SemanticModel or *.Report folder, or any
parent folder (searched recursively). Every object carries `file` (relative to <path>) and
`line` so a reviewer can cite exact locations. Standard library only; no network access.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pbir_parser import parse_legacy_report, parse_pbir_report, read_json  # noqa: E402
from tmdl_parser import Node, parse_column_ref, parse_tmdl  # noqa: E402

SCHEMA_VERSION = 1
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pbi", "out"}


# ---------------------------------------------------------------------------- discovery
def discover(search: Path) -> tuple[list[Path], list[Path]]:
    search = search.resolve()
    if search.is_file() and search.suffix.lower() == ".pbip":
        search = search.parent
    models, reports = [], []

    def visit(d: Path) -> None:
        if d.name.endswith(".SemanticModel") or d.name.endswith(".Dataset"):
            models.append(d)
            return
        if d.name.endswith(".Report"):
            reports.append(d)
            return
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir() and p.name not in SKIP_DIRS)
        except OSError:
            return
        for c in children:
            visit(c)

    visit(search)
    return models, reports


# ---------------------------------------------------------------------------- model
def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() == "true"


def _span(n: Node) -> list[int]:
    return [n.line, n.end_line]


def build_model(model_dir: Path, root: Path) -> dict:
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    definition = model_dir / "definition"
    model: dict = {
        "name": model_dir.name.rsplit(".", 1)[0],
        "path": rel(model_dir),
        "format": "tmdl",
        "warnings": [],
        "settings": {},
        "tables": [],
        "relationships": [],
        "roles": [],
        "expressions": [],
        "perspectives": [],
    }
    if not definition.is_dir():
        if (model_dir / "model.bim").exists():
            model["format"] = "tmsl"
            model["warnings"].append("model.bim (TMSL JSON) found: v0.1 reviews TMDL only. In Power BI "
                                     "Desktop enable 'Store semantic model using TMDL format' and re-save.")
        else:
            model["warnings"].append("No definition/ folder with TMDL files found.")
        return model

    for f in sorted(definition.rglob("*.tmdl")):
        frel = rel(f)
        try:
            nodes = parse_tmdl(f.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # keep going; report the file
            model["warnings"].append(f"{frel}: could not parse TMDL ({exc})")
            continue
        # Power BI writes model-level annotations at indent 0 after the `model` block.
        model_node = next((n for n in nodes if n.kind.lower() == "model"), None)
        if model_node is not None:
            model_node.children.extend(n for n in nodes if n.kind.lower() == "annotation")
        for n in nodes:
            k = n.kind.lower()
            if k == "model":
                model["settings"] = _model_settings(n, frel)
            elif k == "table":
                model["tables"].append(_table(n, frel))
            elif k == "relationship":
                model["relationships"].append(_relationship(n, frel))
            elif k == "role":
                model["roles"].append(_role(n, frel))
            elif k == "expression":
                model["expressions"].append(_expression(n, frel))
            elif k == "perspective":
                model["perspectives"].append({"name": n.name, "file": frel, "line": n.line})
    model["tables"].sort(key=lambda t: t["name"].lower())
    if not model["settings"]:
        model["settings"] = {"file": None, "line": None, "autoDateTime": None,
                             "discourageImplicitMeasures": False, "annotations": {}}
    if any(t["isAutoDateTable"] for t in model["tables"]):
        model["settings"]["autoDateTime"] = True
    return model


def _model_settings(n: Node, frel: str) -> dict:
    ann = n.annotations()
    ti = ann.get("__PBI_TimeIntelligenceEnabled")
    return {
        "name": n.name,
        "file": frel,
        "line": n.line,
        "culture": n.prop("culture"),
        "discourageImplicitMeasures": n.flag("discourageImplicitMeasures"),
        "autoDateTime": None if ti is None else ti.strip() == "1",
        "autoDateTimeLine": next((c.line for c in n.objects("annotation")
                                  if c.name == "__PBI_TimeIntelligenceEnabled"), None),
        "annotations": ann,
        "span": _span(n),
    }


def _table(n: Node, frel: str) -> dict:
    partitions = []
    for p in n.objects("partition"):
        src = p.child_expr("source")
        ptype = (p.expression or "").strip().lower()
        partitions.append({
            "name": p.name,
            "type": ptype,                          # m | calculated | entity | policyRange ...
            "mode": (p.prop("mode") or "import"),
            "expression": src.expression if src else None,
            "exprLine": src.expr_line if src else None,
            "file": frel,
            "line": p.line,
            "span": _span(p),
        })
    is_calc_group = any(c.kind == "calculationGroup" for c in n.children)
    calc_items = []
    for cg in (c for c in n.children if c.kind == "calculationGroup"):
        for item in cg.objects("calculationItem"):
            fsd = item.child_expr("formatStringDefinition")
            calc_items.append({"name": item.name, "expression": item.expression, "exprLine": item.expr_line,
                               "formatStringExpression": fsd.expression if fsd else None,
                               "file": frel, "line": item.line, "span": _span(item)})
    modes = {p["mode"].lower() for p in partitions}
    types = {p["type"] for p in partitions}
    if is_calc_group:
        kind = "calculationGroup"
    elif "calculated" in types:
        kind = "calculated"
    elif "entity" in types or "directlake" in modes:
        kind = "directLake"
    elif "directquery" in modes:
        kind = "directQuery"
    elif "dual" in modes:
        kind = "dual"
    elif partitions:
        kind = "import"
    else:
        kind = "unknown"
    ann = n.annotations()
    name = n.name or ""
    columns = [_column(c, name, frel) for c in n.objects("column")]
    table = {
        "name": name,
        "file": frel,
        "line": n.line,
        "span": _span(n),
        "description": n.description,
        "kind": kind,
        "isHidden": n.flag("isHidden"),
        "isPrivate": n.flag("isPrivate"),
        "dataCategory": n.prop("dataCategory"),
        "isAutoDateTable": name.startswith(("LocalDateTable_", "DateTableTemplate_"))
                           or _bool(ann.get("__PBI_LocalDateTable")),
        "isFieldParameter": any(c.get("isFieldParameter") for c in columns),
        "columns": columns,
        "measures": [_measure(m, name, frel) for m in n.objects("measure")],
        "hierarchies": [{
            "name": h.name, "file": frel, "line": h.line, "span": _span(h),
            "isHidden": h.flag("isHidden"),
            "levels": [{"name": lv.name, "column": lv.prop("column"), "line": lv.line} for lv in h.objects("level")],
        } for h in n.objects("hierarchy")],
        "partitions": partitions,
        "calculationItems": calc_items,
        "annotations": ann,
    }
    table["columnCount"] = len(table["columns"])
    return table


def _column(c: Node, table: str, frel: str) -> dict:
    return {
        "name": c.name,
        "table": table,
        "file": frel,
        "line": c.line,
        "span": _span(c),
        "dataType": (c.prop("dataType") or "").lower() or None,
        "isCalculated": c.expression is not None,
        "expression": c.expression,
        "exprLine": c.expr_line,
        "isHidden": c.flag("isHidden"),
        "isKey": c.flag("isKey"),
        "summarizeBy": (c.prop("summarizeBy") or "").lower() or None,
        "sortByColumn": c.prop("sortByColumn"),
        "dataCategory": c.prop("dataCategory"),
        "formatString": c.prop("formatString"),
        "displayFolder": c.prop("displayFolder"),
        "sourceColumn": c.prop("sourceColumn"),
        "description": c.description,
        "isFieldParameter": any(x.kind == "extendedProperty" and x.name == "ParameterMetadata"
                                for x in c.children),
    }


def _measure(m: Node, table: str, frel: str) -> dict:
    fsd = m.child_expr("formatStringDefinition")
    return {
        "name": m.name,
        "table": table,
        "file": frel,
        "line": m.line,
        "span": _span(m),
        "expression": m.expression or "",
        "exprLine": m.expr_line,
        "formatString": m.prop("formatString"),
        "formatStringExpression": fsd.expression if fsd else None,
        "displayFolder": m.prop("displayFolder"),
        "description": m.description,
        "isHidden": m.flag("isHidden"),
    }


def _relationship(n: Node, frel: str) -> dict:
    ft, fc = parse_column_ref(n.prop("fromColumn") or "")
    tt, tc = parse_column_ref(n.prop("toColumn") or "")
    return {
        "name": n.name,
        "file": frel,
        "line": n.line,
        "span": _span(n),
        "fromTable": ft, "fromColumn": fc,
        "toTable": tt, "toColumn": tc,
        "fromCardinality": (n.prop("fromCardinality") or "many").lower(),
        "toCardinality": (n.prop("toCardinality") or "one").lower(),
        "crossFilteringBehavior": (n.prop("crossFilteringBehavior") or "oneDirection"),
        "securityFilteringBehavior": n.prop("securityFilteringBehavior"),
        "isActive": (n.prop("isActive") or "true").strip().lower() != "false",
    }


def _role(n: Node, frel: str) -> dict:
    tps, cps = [], []
    for tp in n.objects("tablePermission"):
        tps.append({"table": tp.name, "expression": tp.expression, "exprLine": tp.expr_line,
                    "metadataPermission": tp.prop("metadataPermission"), "line": tp.line, "span": _span(tp)})
        for cp in tp.objects("columnPermission"):
            cps.append({"table": tp.name, "column": cp.name,
                        "permission": (cp.expression or cp.prop("metadataPermission") or "").strip(),
                        "line": cp.line})
    return {
        "name": n.name,
        "file": frel,
        "line": n.line,
        "span": _span(n),
        "modelPermission": n.prop("modelPermission"),
        "tablePermissions": tps,
        "columnPermissions": cps,
        "members": [m.name for m in n.objects("member")],
    }


def _expression(n: Node, frel: str) -> dict:
    text = n.expression or ""
    return {
        "name": n.name,
        "file": frel,
        "line": n.line,
        "span": _span(n),
        "expression": text,
        "exprLine": n.expr_line,
        "isParameter": "IsParameterQuery=true" in text.replace(" ", ""),
        "queryGroup": n.prop("queryGroup"),
    }


# ---------------------------------------------------------------------------- report
def build_report(report_dir: Path, root: Path, models: list[dict]) -> dict:
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    if (report_dir / "definition").is_dir():
        report = parse_pbir_report(report_dir, root)
    elif (report_dir / "report.json").exists():
        report = parse_legacy_report(report_dir, root)
    else:
        report = {"format": "unknown", "pages": [], "bookmarks": [], "filters": [], "theme": {},
                  "warnings": ["No definition/ folder or report.json found in report."]}
    report["name"] = report_dir.name.rsplit(".", 1)[0]
    report["path"] = rel(report_dir)
    report["model"] = None
    pbir = report_dir / "definition.pbir"
    if pbir.exists():
        try:
            ref = read_json(pbir).get("datasetReference") or {}
        except (ValueError, OSError):
            ref = {}
        by_path = (ref.get("byPath") or {}).get("path")
        if by_path:
            target = (report_dir / by_path).resolve()
            for m in models:
                if (root / m["path"]).resolve() == target:
                    report["model"] = m["name"]
        elif ref.get("byConnection"):
            report["warnings"].append("Report uses a live connection (byConnection); its model is not in "
                                      "this project, so field usage cannot be linked.")
    if report["model"] is None and len(models) == 1 and not pbir.exists():
        report["model"] = models[0]["name"]
    return report


# ---------------------------------------------------------------------------- main
def build_inventory(path: Path, root: Path | None = None) -> dict:
    path = Path(path).resolve()
    if root is None:
        root = path.parent if path.is_file() else path
        if path.name.endswith((".SemanticModel", ".Report", ".Dataset")):
            root = path.parent
    root = Path(root).resolve()
    model_dirs, report_dirs = discover(path)
    models = [build_model(d, root) for d in model_dirs]
    reports = [build_report(d, root, models) for d in report_dirs]
    if not model_dirs and not report_dirs:
        warnings = [f"No *.SemanticModel or *.Report folder found under {path}"]
    else:
        warnings = []
    return {
        "schema_version": SCHEMA_VERSION,
        "root": root.as_posix(),
        "models": models,
        "reports": reports,
        "warnings": warnings,
        "stats": {
            "models": len(models),
            "reports": len(reports),
            "tables": sum(len(m["tables"]) for m in models),
            "columns": sum(len(t["columns"]) for m in models for t in m["tables"]),
            "measures": sum(len(t["measures"]) for m in models for t in m["tables"]),
            "relationships": sum(len(m["relationships"]) for m in models),
            "pages": sum(len(r["pages"]) for r in reports),
            "visuals": sum(len(p["visuals"]) for r in reports for p in r["pages"]),
        },
    }


def write_json(data, out: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="PBIP project folder, *.SemanticModel / *.Report folder, or a parent folder")
    ap.add_argument("-o", "--output", help="write JSON here instead of stdout")
    args = ap.parse_args(argv)
    inv = build_inventory(Path(args.path))
    write_json(inv, args.output)
    if args.output:
        s = inv["stats"]
        print(f"inventory: {s['models']} model(s), {s['tables']} tables, {s['measures']} measures, "
              f"{s['relationships']} relationships, {s['reports']} report(s), {s['pages']} pages, "
              f"{s['visuals']} visuals -> {args.output}", file=sys.stderr)
    return 0 if (inv["models"] or inv["reports"]) else 2


if __name__ == "__main__":
    sys.exit(main())
