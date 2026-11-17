#!/usr/bin/env python3
"""Work out which Power BI objects a git change touches, for PR-mode reviews.

Usage:
    python3 diff_scope.py <base> [<head>] [--repo DIR] [--path SUBDIR] [-o scope.json]

<base>   branch / commit the PR targets (e.g. origin/main). The merge-base with head is used,
         so only the PR's own changes count.
<head>   branch / commit under review. Omit to use the working tree (uncommitted changes included).

Output (JSON):
    objects.added / modified / removed   object keys such as "measure:Sales[Total Sales]"
    impacted                             objects that depend on a changed object (measures that
                                         reference it, visuals that show it, ...), transitively
    brokenReferences                     DAX / visuals still pointing at removed objects
    changedLines                         per file, the changed line ranges on the head side
    scopeKeys                            added + modified objects (+ their pages); pass the file to
                                         static_checks.py --scope to keep only PR-relevant findings

Reads git with plain `git` subprocess calls (diff, merge-base, archive). Never writes to the repo.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_index import ModelIndex, k  # noqa: E402
from pbip_inventory import build_inventory, write_json  # noqa: E402

MAX_DEPTH = 6


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: Path, binary: bool = False):
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def extract_tree(repo: Path, rev: str, subpath: str, dest: Path) -> bool:
    """Write the files of <rev>:<subpath> under dest. Returns False if the path does not exist at rev."""
    try:
        data = git(["archive", "--format=tar", rev, "--", subpath], repo, binary=True)
    except GitError:
        return False
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # Python < 3.12: archive comes from our own repo; still refuse unsafe paths
            members = [m for m in tar.getmembers()
                       if not (m.name.startswith(("/", "..")) or "/../" in m.name or m.issym() or m.islnk())]
            tar.extractall(dest, members=members)
    return True


# ------------------------------------------------------------------------- object map
def _read(root: Path, rel: str, cache: dict[str, list[str]]) -> list[str]:
    if rel not in cache:
        try:
            cache[rel] = (root / rel).read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            cache[rel] = []
    return cache[rel]


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def object_map(inv: dict, root: Path) -> dict[str, dict]:
    """key -> {fp, file, line}. fp is a hash of the object's own source text."""
    cache: dict[str, list[str]] = {}
    out: dict[str, dict] = {}

    def span_text(file: str, span: list[int], exclude: list[list[int]] | None = None) -> str:
        lines = _read(root, file, cache)
        skip = set()
        for s in exclude or []:
            skip.update(range(s[0], s[1] + 1))
        kept = (lines[i - 1].rstrip() for i in range(span[0], min(span[1], len(lines)) + 1) if i not in skip)
        return "\n".join(ln for ln in kept if ln.strip())  # blank lines are layout, not content

    def put(key: str, file: str, line: int, text: str) -> None:
        out[key] = {"fp": _digest(text), "file": file, "line": line}

    for m in inv["models"]:
        st = m["settings"]
        if st.get("file"):
            text = "\n".join(ln for ln in _read(root, st["file"], cache) if not ln.startswith("ref "))
            put("model:settings", st["file"], st["line"] or 1, text)
        for t in m["tables"]:
            children = [c["span"] for c in t["columns"]] + [x["span"] for x in t["measures"]] + \
                       [p["span"] for p in t["partitions"]] + [h["span"] for h in t["hierarchies"]] + \
                       [ci["span"] for ci in t["calculationItems"]]
            put(f"table:{t['name']}", t["file"], t["line"], span_text(t["file"], t["span"], children))
            for c in t["columns"]:
                put(f"column:{t['name']}[{c['name']}]", c["file"], c["line"], span_text(c["file"], c["span"]))
            for x in t["measures"]:
                put(f"measure:{t['name']}[{x['name']}]", x["file"], x["line"], span_text(x["file"], x["span"]))
            for p in t["partitions"]:
                put(f"partition:{t['name']}/{p['name']}", p["file"], p["line"], span_text(p["file"], p["span"]))
            for h in t["hierarchies"]:
                put(f"hierarchy:{t['name']}/{h['name']}", h["file"], h["line"], span_text(h["file"], h["span"]))
            for ci in t["calculationItems"]:
                put(f"calcItem:{t['name']}/{ci['name']}", ci["file"], ci["line"], span_text(ci["file"], ci["span"]))
        for r in m["relationships"]:
            put(f"relationship:{r['name']}", r["file"], r["line"], span_text(r["file"], r["span"]))
        for r in m["roles"]:
            put(f"role:{r['name']}", r["file"], r["line"], span_text(r["file"], r["span"]))
        for e in m["expressions"]:
            put(f"expression:{e['name']}", e["file"], e["line"], span_text(e["file"], e["span"]))
    for rep in inv["reports"]:
        if rep.get("settingsFile"):
            put(f"report:{rep['name']}", rep["settingsFile"], 1, "\n".join(_read(root, rep["settingsFile"], cache)))
        for p in rep["pages"]:
            put(f"page:{p['name']}", p["file"], p["line"], "\n".join(_read(root, p["file"], cache)))
            for v in p["visuals"]:
                put(f"visual:{p['name']}/{v['name']}", v["file"], v["line"], "\n".join(_read(root, v["file"], cache)))
        for b in rep["bookmarks"]:
            put(f"bookmark:{b['name']}", b["file"], 1, "\n".join(_read(root, b["file"], cache)))
    return out


# ------------------------------------------------------------------------- dependency graph
def dependents_graph(inv: dict) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(dependents, dependencies): key -> keys that use it / keys it uses."""
    dependents: dict[str, set[str]] = {}
    dependencies: dict[str, set[str]] = {}

    def link(used: str, by: str) -> None:
        if used != by:
            dependents.setdefault(used, set()).add(by)
            dependencies.setdefault(by, set()).add(used)

    for m in inv["models"]:
        idx = ModelIndex(m)
        for src in idx.dax_sources():
            for kind, table, name, _ in idx.references(src):
                if kind == "table":
                    link(f"table:{table}", src.owner)
                else:
                    link(f"{kind}:{table}[{name}]", src.owner)
        for r in m["relationships"]:
            link(f"column:{r['fromTable']}[{r['fromColumn']}]", f"relationship:{r['name']}")
            link(f"column:{r['toTable']}[{r['toColumn']}]", f"relationship:{r['name']}")
        for t in m["tables"]:
            for p in t["partitions"]:
                link(f"partition:{t['name']}/{p['name']}", f"table:{t['name']}")
            for c in t["columns"]:
                link(f"table:{t['name']}", f"column:{t['name']}[{c['name']}]")
                if c.get("sortByColumn"):
                    link(f"column:{t['name']}[{c['sortByColumn']}]", f"column:{t['name']}[{c['name']}]")
        for e in m["expressions"]:  # M parameters / shared queries used by partitions
            pat = re.compile(r"(?<![\w.#])" + re.escape(e["name"]) + r"(?![\w.])|#\"" + re.escape(e["name"]) + '"')
            for t in m["tables"]:
                for p in t["partitions"]:
                    if p["type"] == "m" and p["expression"] and pat.search(p["expression"]):
                        link(f"expression:{e['name']}", f"partition:{t['name']}/{p['name']}")
        for rep in inv["reports"]:
            if rep.get("model") != m["name"]:
                continue
            for page in rep["pages"]:
                for v in page["visuals"]:
                    vkey = f"visual:{page['name']}/{v['name']}"
                    link(vkey, f"page:{page['name']}")
                    for f in v["fields"] + [x for flt in v["filters"] for x in flt["fields"]]:
                        key = _field_key(idx, f)
                        if key:
                            link(key, vkey)
    return dependents, dependencies


def _field_key(idx: ModelIndex, f: dict) -> str | None:
    if f.get("kind") == "measure" or (f.get("kind") == "column" and not idx.column(f["table"], f["name"])
                                      and idx.measure(f["name"])):
        m = idx.measure(f["name"])
        return f"measure:{m['table']}[{m['name']}]" if m else f"measure:{f['table']}[{f['name']}]"
    if f.get("kind") == "column":
        c = idx.column(f["table"], f["name"])
        return f"column:{c['table']}[{c['name']}]" if c else f"column:{f['table']}[{f['name']}]"
    if f.get("kind") == "hierarchy":
        return f"hierarchy:{f['table']}/{f['name']}"
    return None


def broken_references(head_inv: dict, removed: set[str]) -> list[dict]:
    out = []
    removed_names = {}
    for key in removed:
        m = re.match(r"(measure|column):(.+)\[(.+)\]$", key)
        if m:
            removed_names.setdefault(k(m.group(3)), key)
    for m in head_inv["models"]:
        idx = ModelIndex(m)
        import dax_lexer as dax  # local import keeps module import cheap
        for src in idx.dax_sources():
            for t in dax.tokenize(src.expression):
                if t.type in ("bracket", "colref") and k(t.column) in removed_names:
                    resolved = idx.measure(t.column) or (t.table and idx.column(t.table, t.column))
                    if not resolved:
                        out.append({"by": src.owner, "missing": removed_names[k(t.column)], "file": src.file,
                                    "line": src.line + t.line, "text": t.value})
        for rep in head_inv["reports"]:
            if rep.get("model") != m["name"]:
                continue
            for page in rep["pages"]:
                for v in page["visuals"]:
                    for f in v["fields"]:
                        if f.get("kind") in ("column", "measure") and not idx.column(f["table"], f["name"]) \
                                and not idx.measure(f["name"]):
                            out.append({"by": f"visual:{page['name']}/{v['name']}",
                                        "missing": f"{f['kind']}:{f['table']}[{f['name']}]",
                                        "file": v["file"], "line": v["line"], "text": f"{f['table']}.{f['name']}"})
    return out


# ------------------------------------------------------------------------- git diff
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed_lines(repo: Path, base: str, head: str | None, path: str) -> tuple[list[dict], dict[str, list[list[int]]]]:
    rev_args = [base] + ([head] if head else [])
    files = []
    for line in git(["diff", "--name-status", "-M", *rev_args, "--", path], repo).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append({"status": parts[0][0], "path": parts[-1], "oldPath": parts[1] if len(parts) == 3 else None})
    hunks: dict[str, list[list[int]]] = {}
    current = None
    for line in git(["diff", "-U0", "-M", "--no-color", *rev_args, "--", path], repo).splitlines():
        if line.startswith("+++ "):
            current = None if line[4:] == "/dev/null" else line[6:] if line.startswith("+++ b/") else line[4:]
        elif current and (m := HUNK.match(line)):
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            hunks.setdefault(current, []).append([start, start + max(count, 1) - 1])
    return files, hunks


# ------------------------------------------------------------------------- main
def build_scope(repo: Path, base: str, head: str | None = None, subpath: str = ".") -> dict:
    top = Path(git(["rev-parse", "--show-toplevel"], repo).strip())
    head_rev = head or "HEAD"
    merge_base = git(["merge-base", base, head_rev], top).strip()
    sub = subpath.strip("/") or "."
    with tempfile.TemporaryDirectory(prefix="pbi-scope-", ignore_cleanup_errors=True) as tmp:
        base_root = Path(tmp) / "base"
        base_root.mkdir()
        if extract_tree(top, merge_base, sub, base_root):
            base_inv = build_inventory(base_root / sub, root=base_root)
        else:
            base_inv = {"models": [], "reports": []}
        base_map = object_map(base_inv, base_root)
        if head:
            head_root = Path(tmp) / "head"
            head_root.mkdir()
            extract_tree(top, head, sub, head_root)
        else:
            head_root = top
        head_inv = build_inventory(head_root / sub, root=head_root)
        head_map = object_map(head_inv, head_root)
    added = sorted(set(head_map) - set(base_map))
    removed = sorted(set(base_map) - set(head_map))
    modified = sorted(key for key in set(head_map) & set(base_map) if head_map[key]["fp"] != base_map[key]["fp"])
    dependents, dependencies = dependents_graph(head_inv)
    changed = set(added) | set(modified)
    impacted: set[str] = set()
    frontier = set(changed) | set(removed)
    for _ in range(MAX_DEPTH):
        nxt = set()
        for key in frontier:
            nxt |= dependents.get(key, set())
        nxt -= changed | impacted
        if not nxt:
            break
        impacted |= nxt
        frontier = nxt
    context = set()
    for key in changed:
        context |= dependencies.get(key, set())
    context -= changed | impacted
    files, hunks = changed_lines(top, merge_base, head, sub)
    # Findings are limited to what the PR itself added or changed ("comment on new problems, not
    # old ones"). Impacted objects are listed separately as context for the reviewer's judgment.
    scope_keys = set(changed)
    scope_keys |= {"page:" + key.split(":", 1)[1].split("/", 1)[0] for key in scope_keys if key.startswith("visual:")}
    locate = lambda key: {"key": key, **{f: head_map.get(key, base_map.get(key, {})).get(f) for f in ("file", "line")}}  # noqa: E731
    return {
        "schema_version": 1,
        "base": base,
        "head": head or "WORKTREE",
        "mergeBase": merge_base,
        "path": sub,
        "changedFiles": files,
        "changedLines": hunks,
        "objects": {"added": [locate(x) for x in added], "modified": [locate(x) for x in modified],
                    "removed": [locate(x) for x in removed]},
        "impacted": [locate(x) for x in sorted(impacted)],
        "context": sorted(context),
        "brokenReferences": broken_references(head_inv, set(removed)),
        "scopeKeys": sorted(scope_keys),
        "summary": {"added": len(added), "modified": len(modified), "removed": len(removed),
                    "impacted": len(impacted), "changedFiles": len(files)},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("head", nargs="?")
    ap.add_argument("--repo", default=".", help="any folder inside the git repository (default: .)")
    ap.add_argument("--path", default=".", help="limit to this sub-folder of the repository")
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    try:
        scope = build_scope(Path(args.repo), args.base, args.head, args.path)
    except GitError as exc:
        print(f"diff_scope: {exc}", file=sys.stderr)
        return 2
    write_json(scope, args.output)
    if args.output:
        s = scope["summary"]
        print(f"scope: {s['changedFiles']} file(s), {s['added']} added, {s['modified']} modified, "
              f"{s['removed']} removed, {s['impacted']} impacted object(s) -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
