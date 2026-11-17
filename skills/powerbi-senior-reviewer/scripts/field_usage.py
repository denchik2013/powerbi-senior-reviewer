#!/usr/bin/env python3
"""Find columns and measures that nothing uses: candidates for removal.

A column or measure counts as used if it is referenced by any of: report visuals (fields,
filters, sorting, conditional formatting), report/page filters, DAX (measures, calculated
columns and tables, calculation items, RLS), relationships, sort-by-column, hierarchies.

Usage:
    python3 field_usage.py <path> [-o usage.json] [--inventory inventory.json]

Only reports inside <path> are seen. Thin reports elsewhere that use the same model are
invisible to this script, so treat "unused" as "unused in this repository".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_index import ModelIndex, k  # noqa: E402
from pbip_inventory import build_inventory, write_json  # noqa: E402

MAX_USES_LISTED = 10


def reports_for(model: dict, inventory: dict) -> list[dict]:
    return [r for r in inventory["reports"] if r.get("model") == model["name"]]


def compute_usage(model: dict, inventory: dict) -> dict:
    idx = ModelIndex(model)
    uses: dict[tuple[str, str, str], list[str]] = {}

    def add(kind: str, table: str, name: str, by: str) -> None:
        uses.setdefault((kind, k(table), k(name)), []).append(by)

    # DAX everywhere in the model
    for src in idx.dax_sources():
        for kind, table, name, line in idx.references(src):
            if kind in ("column", "measure") and src.owner != f"{kind}:{table}[{name}]":
                add(kind, table, name, f"{src.kind} {src.owner.split(':', 1)[1]} ({src.file}:{line})")
    # Relationships
    for r in model["relationships"]:
        add("column", r["fromTable"], r["fromColumn"], f"relationship {r['name']}")
        add("column", r["toTable"], r["toColumn"], f"relationship {r['name']}")
    # Sort by, hierarchies, key
    for t in model["tables"]:
        for c in t["columns"]:
            if c.get("sortByColumn"):
                add("column", t["name"], c["sortByColumn"], f"sortByColumn of {t['name']}[{c['name']}]")
            if c.get("isKey"):
                add("column", t["name"], c["name"], "table key (isKey)")
        for h in t["hierarchies"]:
            for lv in h["levels"]:
                if lv.get("column"):
                    add("column", t["name"], lv["column"], f"hierarchy {t['name']}/{h['name']}")
    # Reports
    reports = reports_for(model, inventory)
    for rep in reports:
        for f in rep.get("filters", []):
            for fld in f["fields"]:
                _add_field(add, idx, fld, f"report filter ({f['file']})")
        for page in rep["pages"]:
            for f in page["filters"]:
                for fld in f["fields"]:
                    _add_field(add, idx, fld, f"page filter {page['displayName']}")
            for v in page["visuals"]:
                where = f"visual {page['displayName']}/{v['name']} ({v['type']})"
                for fld in v["fields"]:
                    _add_field(add, idx, fld, where)
                for f in v["filters"]:
                    for fld in f["fields"]:
                        _add_field(add, idx, fld, where + " filter")

    columns, measures, unused_columns, unused_measures = [], [], [], []
    for t in model["tables"]:
        if t["isAutoDateTable"] or t["kind"] == "calculationGroup" or t["isFieldParameter"]:
            continue
        measure_table = bool(t["measures"]) and all(c["isHidden"] for c in t["columns"]) and len(t["columns"]) <= 1
        for c in t["columns"]:
            if measure_table:
                continue
            by = uses.get(("column", k(t["name"]), k(c["name"])), [])
            row = {"table": t["name"], "name": c["name"], "file": c["file"], "line": c["line"],
                   "isHidden": c["isHidden"], "uses": len(by), "usedBy": by[:MAX_USES_LISTED]}
            columns.append(row)
            if not by:
                unused_columns.append(row)
        for m in t["measures"]:
            by = uses.get(("measure", k(t["name"]), k(m["name"])), [])
            row = {"table": t["name"], "name": m["name"], "file": m["file"], "line": m["line"],
                   "isHidden": m["isHidden"], "uses": len(by), "usedBy": by[:MAX_USES_LISTED]}
            measures.append(row)
            if not by:
                unused_measures.append(row)
    return {
        "model": model["name"],
        "reports": [r["name"] for r in reports],
        "reportCoverage": "linked" if reports else "none",
        "note": None if reports else ("No report in this folder uses this model, so visual usage is unknown. "
                                      "Unused lists only reflect DAX, relationships and model structure."),
        "unusedColumns": unused_columns,
        "unusedMeasures": unused_measures,
        "columns": columns,
        "measures": measures,
    }


def _add_field(add, idx: ModelIndex, fld: dict, where: str) -> None:
    kind = fld.get("kind")
    if kind == "hierarchy":
        t = idx.table(fld["table"])
        if t:
            for h in t["hierarchies"]:
                if k(h["name"]) == k(fld["name"]):
                    for lv in h["levels"]:
                        if fld.get("level") is None or k(lv["name"]) == k(fld.get("level")):
                            add("column", t["name"], lv["column"], where)
        return
    if kind == "column" and idx.column(fld["table"], fld["name"]) is None and idx.measure(fld["name"]):
        kind = "measure"
    if kind in ("column", "measure"):
        add(kind, fld["table"], fld["name"], where)


def build_usage(inventory: dict) -> dict:
    return {"schema_version": 1, "models": [compute_usage(m, inventory) for m in inventory["models"]]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="PBIP project folder (ignored if --inventory is given)")
    ap.add_argument("--inventory", help="reuse an inventory.json produced by pbip_inventory.py")
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    if args.inventory:
        inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    elif args.path:
        inv = build_inventory(Path(args.path))
    else:
        ap.error("path or --inventory is required")
    usage = build_usage(inv)
    write_json(usage, args.output)
    if args.output:
        for m in usage["models"]:
            print(f"usage[{m['model']}]: {len(m['unusedColumns'])} unused column(s), "
                  f"{len(m['unusedMeasures'])} unused measure(s), report coverage: {m['reportCoverage']}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
