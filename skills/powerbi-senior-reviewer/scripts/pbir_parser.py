"""PBIR (Power BI enhanced report format) reader, plus limited legacy report.json support."""
from __future__ import annotations

import json
from pathlib import Path

DECORATIVE_VISUALS = {
    "shape", "basicShape", "image", "textbox", "actionButton", "pageNavigator",
    "bookmarkNavigator", "group",
}
SLICER_VISUALS = {"slicer", "advancedSlicerVisual", "listSlicer", "textSlicer", "buttonSlicer"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_line(path: Path, needle: str, default: int = 1) -> int:
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if needle in line:
                return i
    except OSError:
        pass
    return default


def literal(prop) -> object:
    """Decode {"expr": {"Literal": {"Value": "'text'"}}} into a Python value."""
    try:
        value = prop["expr"]["Literal"]["Value"]
    except (KeyError, TypeError):
        return None
    if not isinstance(value, str):
        return value
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if value in ("true", "false"):
        return value == "true"
    return value


def _container_prop(visual: dict, obj: str, prop: str):
    for source in (visual.get("visualContainerObjects") or {}, visual.get("objects") or {}):
        for entry in source.get(obj, []) or []:
            props = entry.get("properties") or {}
            if prop in props:
                return literal(props[prop])
    return None


def _entity(expr, aliases: dict[str, str]) -> str | None:
    if not isinstance(expr, dict):
        return None
    src = expr.get("SourceRef")
    if isinstance(src, dict):
        if "Entity" in src:
            return src["Entity"]
        if "Source" in src:
            return aliases.get(src["Source"], src["Source"])
    return None


def collect_fields(obj, role: str, out: list[dict], aliases: dict[str, str] | None = None,
                   implicit: bool = False) -> None:
    """Recursively collect column / measure / hierarchy-level references from a PBIR JSON fragment."""
    aliases = aliases or {}
    if isinstance(obj, list):
        for v in obj:
            collect_fields(v, role, out, aliases, implicit)
        return
    if not isinstance(obj, dict):
        return
    for key, kind in (("Column", "column"), ("Measure", "measure")):
        v = obj.get(key)
        if isinstance(v, dict) and "Property" in v:
            ent = _entity(v.get("Expression"), aliases)
            if ent:
                out.append({"table": ent, "name": v["Property"], "kind": kind, "role": role,
                            "implicit": implicit and kind == "column"})
    agg = obj.get("Aggregation")
    if isinstance(agg, dict):
        collect_fields(agg.get("Expression"), role, out, aliases, implicit=True)
        return
    hl = obj.get("HierarchyLevel")
    if isinstance(hl, dict):
        hier = (hl.get("Expression") or {}).get("Hierarchy") or {}
        hexpr = hier.get("Expression") or {}
        pvs = hexpr.get("PropertyVariationSource")
        if isinstance(pvs, dict):  # auto date/time hierarchy on a date column
            ent = _entity(pvs.get("Expression"), aliases)
            if ent:
                out.append({"table": ent, "name": pvs.get("Property"), "kind": "column", "role": role,
                            "implicit": False, "autoDateHierarchy": True})
        else:
            ent = _entity(hexpr, aliases)
            if ent:
                out.append({"table": ent, "name": hier.get("Hierarchy"), "kind": "hierarchy",
                            "level": hl.get("Level"), "role": role, "implicit": False})
        return
    for k, v in obj.items():
        if k in ("Column", "Measure"):
            continue
        collect_fields(v, role, out, aliases, implicit)


def _filters(container: dict, path: Path, rel: str) -> list[dict]:
    out = []
    for f in ((container.get("filterConfig") or {}).get("filters") or []):
        fields: list[dict] = []
        collect_fields(f.get("field"), "filter", fields)
        collect_fields(f.get("filter"), "filter", fields)
        out.append({
            "name": f.get("name"),
            "type": f.get("type"),
            "fields": fields,
            "hidden": bool(f.get("isHiddenInViewMode")),
            "locked": bool(f.get("isLockedInViewMode")),
            "hasCondition": f.get("filter") is not None,
            "file": rel,
            "line": find_line(path, f'"{f.get("name")}"') if f.get("name") else 1,
        })
    return out


def parse_pbir_report(report_dir: Path, root: Path) -> dict:
    definition = report_dir / "definition"
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    report: dict = {"format": "pbir", "warnings": [], "pages": [], "bookmarks": [], "filters": [], "theme": {}}
    report_json = definition / "report.json"
    if report_json.exists():
        data = read_json(report_json)
        theme = data.get("themeCollection") or {}
        report["theme"] = {
            "base": (theme.get("baseTheme") or {}).get("name"),
            "custom": (theme.get("customTheme") or {}).get("name"),
        }
        report["filters"] = _filters(data, report_json, rel(report_json))
        report["settingsFile"] = rel(report_json)

    pages_dir = definition / "pages"
    order: list[str] = []
    pages_meta = pages_dir / "pages.json"
    if pages_meta.exists():
        order = read_json(pages_meta).get("pageOrder") or []
    page_dirs = {p.name: p for p in pages_dir.iterdir() if p.is_dir()} if pages_dir.exists() else {}
    names = [n for n in order if n in page_dirs] + sorted(n for n in page_dirs if n not in order)

    for page_name in names:
        pdir = page_dirs[page_name]
        pfile = pdir / "page.json"
        pdata = read_json(pfile) if pfile.exists() else {}
        binding = pdata.get("pageBinding") or {}
        ptype = (binding.get("type") or pdata.get("type") or "default")
        page = {
            "name": pdata.get("name", page_name),
            "displayName": pdata.get("displayName", page_name),
            "file": rel(pfile) if pfile.exists() else rel(pdir),
            "line": find_line(pfile, '"displayName"') if pfile.exists() else 1,
            "hidden": pdata.get("visibility") == "HiddenInViewMode",
            "type": str(ptype).lower(),
            "filters": _filters(pdata, pfile, rel(pfile)) if pfile.exists() else [],
            "visuals": [],
        }
        vroot = pdir / "visuals"
        if vroot.exists():
            for vdir in sorted(p for p in vroot.iterdir() if p.is_dir()):
                vfile = vdir / "visual.json"
                if vfile.exists():
                    page["visuals"].append(_parse_visual(vfile, rel(vfile), page["name"]))
        report["pages"].append(page)

    bdir = definition / "bookmarks"
    if bdir.exists():
        for bfile in sorted(bdir.glob("*.bookmark.json")):
            b = read_json(bfile)
            report["bookmarks"].append({
                "name": b.get("name"), "displayName": b.get("displayName"),
                "targetPage": (b.get("explorationState") or {}).get("activeSection"),
                "file": rel(bfile), "line": 1,
            })
    return report


def _parse_visual(vfile: Path, rel: str, page: str) -> dict:
    data = read_json(vfile)
    vis = data.get("visual") or {}
    is_group = "visualGroup" in data
    vtype = "group" if is_group else vis.get("visualType", "unknown")
    fields: list[dict] = []
    query_state = ((vis.get("query") or {}).get("queryState") or {})
    for role, bucket in query_state.items():
        for proj in (bucket or {}).get("projections", []) or []:
            collect_fields(proj.get("field"), role, fields)
    collect_fields((vis.get("query") or {}).get("sortDefinition"), "sort", fields)
    collect_fields(vis.get("objects"), "format", fields)
    collect_fields(vis.get("visualContainerObjects"), "format", fields)
    title_show = _container_prop(vis, "title", "show")
    title_text = _container_prop(vis, "title", "text")
    alt = _container_prop(vis, "general", "altText")
    return {
        "name": data.get("name", vfile.parent.name),
        "page": page,
        "type": vtype,
        "isGroup": is_group,
        "isHidden": bool(data.get("isHidden")),
        "file": rel,
        "line": find_line(vfile, '"visualType"') if not is_group else 1,
        "fields": fields,
        "title": {"show": title_show, "text": title_text,
                  "line": find_line(vfile, '"title"', 0) or None},
        "altText": alt if isinstance(alt, str) and alt.strip() else None,
        "filters": _filters(data, vfile, rel),
        "position": data.get("position") or {},
        "links": _links(vis),
    }


def _links(vis: dict) -> list[str]:
    """Page names a button / navigator points to (PageNavigation actions)."""
    out = []
    for entry in (vis.get("visualContainerObjects") or {}).get("visualLink", []) or []:
        props = entry.get("properties") or {}
        target = literal(props.get("navigationSection")) if "navigationSection" in props else None
        if isinstance(target, str):
            out.append(target)
    return out


def parse_legacy_report(report_dir: Path, root: Path) -> dict:
    """Best-effort read of the legacy single-file report.json format."""
    path = report_dir / "report.json"
    relp = path.relative_to(root).as_posix()
    report = {"format": "legacy", "pages": [], "bookmarks": [], "filters": [], "theme": {},
              "warnings": ["Legacy report.json format: report checks are limited (no line-level "
                           "precision, partial field extraction). Save as PBIR (enhanced report "
                           "format) for a full review."]}
    data = read_json(path)
    for sec in data.get("sections", []):
        page = {"name": sec.get("name"), "displayName": sec.get("displayName"), "file": relp,
                "line": find_line(path, f'"{sec.get("displayName")}"'), "hidden": False,
                "type": "default", "filters": [], "visuals": []}
        try:
            sconf = json.loads(sec.get("config") or "{}")
            page["hidden"] = sconf.get("visibility") == 1
        except json.JSONDecodeError:
            pass
        for i, vc in enumerate(sec.get("visualContainers", [])):
            try:
                conf = json.loads(vc.get("config") or "{}")
            except json.JSONDecodeError:
                conf = {}
            sv = conf.get("singleVisual") or {}
            aliases = {f.get("Name"): f.get("Entity") for f in
                       ((sv.get("prototypeQuery") or {}).get("From") or [])}
            fields: list[dict] = []
            collect_fields((sv.get("prototypeQuery") or {}).get("Select"), "field", fields, aliases)
            vco = sv.get("vcObjects") or {}
            title = vco.get("title", [{}])[0].get("properties", {}) if vco.get("title") else {}
            alt = None
            if vco.get("general"):
                alt = literal(vco["general"][0].get("properties", {}).get("altText"))
            page["visuals"].append({
                "name": conf.get("name", f"visual{i}"), "page": page["name"],
                "type": "group" if "singleVisualGroup" in conf else sv.get("visualType", "unknown"),
                "isGroup": "singleVisualGroup" in conf, "isHidden": False,
                "file": relp, "line": page["line"], "fields": fields,
                "title": {"show": literal(title.get("show")), "text": literal(title.get("text")), "line": None},
                "altText": alt if isinstance(alt, str) and alt.strip() else None,
                "filters": [], "position": {}, "links": [],
            })
        report["pages"].append(page)
    return report
