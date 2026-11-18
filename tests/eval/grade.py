"""Grade one review run against tests/expected-issues.md (stdlib only).

Usage:
    python tests/eval/grade.py <run-dir> --fixture bad|good [--expected tests/expected-issues.md] [--json]

<run-dir> is the folder the review ran in: it contains `out/findings.json` (static), `out/judgment.json` (reviewer;
optional) and `out/REVIEW.md`. Paths inside findings are resolved against <run-dir>.

Reports: recall (all / static / judgment) for BadModel, kept findings (= false positives) for GoodModel, citation
validity (cited file exists and line is inside it), whether REVIEW.md exists, and whether the fixture was modified
(`git status` in <run-dir>, if it is a git repo).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_EXPECTED = HERE.parent / "expected-issues.md"
ROW = re.compile(r"^\|\s*(B\d+)\s*\|\s*([SJ])\s*\|\s*((?:[^|\\]|\\.)+?)\s*\|\s*`((?:[^`\\]|\\.)*)`\s*\|")


def load_expected(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            ids = {x.strip() for x in m.group(3).replace("\\|", "|").split("|")}
            anchor = m.group(4).replace("\\|", "|")
            rows.append({"id": m.group(1), "kind": m.group(2), "rules": ids, "anchor": anchor})
    return rows


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("findings", [])
    return [f for f in data if isinstance(f, dict)]


def kept_findings(out: Path) -> tuple[list[dict], list[dict], int]:
    static = _load(out / "findings.json")
    judgment = _load(out / "judgment.json")
    dropped = [j for j in judgment if j.get("dropped")]
    own = [j for j in judgment if not j.get("dropped")]

    def is_dropped(f: dict) -> bool:
        for d in dropped:
            if d.get("id") != f.get("id"):
                continue
            if not d.get("object") and not d.get("file"):
                return True
            if d.get("object") and d.get("object") == f.get("object"):
                return True
            if d.get("file") and Path(str(d["file"])).name == Path(str(f.get("file", ""))).name \
                    and str(d.get("line")) == str(f.get("line")):
                return True
        return False

    kept_static = [f for f in static if not is_dropped(f)]
    return kept_static, own, len(static) - len(kept_static)


def haystack(f: dict) -> str:
    return " ".join(str(f.get(k, "")) for k in ("object", "file", "title", "evidence", "message"))


def rule_ids(f: dict) -> set[str]:
    """The finding's id plus rule ids it explicitly cites in title/message (a merged finding: "per CUS009 …")."""
    cited = re.findall(r"\b(?:MOD|DAX|PQ|RPT|SEC|GOV|PR|CUS)\d{3}\b", f"{f.get('title', '')} {f.get('message', '')}")
    return {str(f.get("id"))} | set(cited)


def matches(f: dict, exp: dict) -> bool:
    return bool(rule_ids(f) & exp["rules"]) and re.search(exp["anchor"], haystack(f), re.I) is not None


def citation_ok(f: dict, root: Path) -> bool:
    file, line = f.get("file"), f.get("line")
    if not file or not isinstance(line, int):
        return False
    p = (root / file) if not Path(file).is_absolute() else Path(file)
    if not p.is_file():
        # tolerate paths relative to the project folder (that is how the scripts report them)
        hits = [h for h in root.rglob(Path(file).name) if h.as_posix().endswith("/" + file.replace("\\", "/"))]
        if len(hits) != 1:
            return False
        p = hits[0]
    n = len(p.read_text(encoding="utf-8-sig", errors="replace").splitlines())
    return 1 <= line <= n


def fixture_modified(root: Path) -> bool | None:
    if not (root / ".git").exists():
        return None
    r = subprocess.run(["git", "status", "--porcelain", "--", ".", ":!out"], cwd=root,
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def grade(root: Path, fixture: str, expected_path: Path = DEFAULT_EXPECTED) -> dict:
    out = root / "out"
    static, own, n_dropped = kept_findings(out)
    allf = static + own
    result = {
        "run": str(root),
        "fixture": fixture,
        "reviewWritten": (out / "REVIEW.md").exists(),
        "staticFindings": len(static) + n_dropped,
        "staticDropped": n_dropped,
        "judgmentFindings": len(own),
        "keptFindings": len(allf),
        "citationsValid": sum(citation_ok(f, root) for f in allf),
        "fixtureModified": fixture_modified(root),
    }
    if fixture == "good":
        result["falsePositives"] = [f"{f.get('id')} {f.get('object', '')} {f.get('file', '')}:{f.get('line', '')}"
                                    for f in allf]
        return result
    expected = load_expected(expected_path)
    found, missed = [], []
    for e in expected:
        (found if any(matches(f, e) for f in allf) else missed).append(e)
    unmatched = [f for f in allf if not any(matches(f, e) for e in expected)]

    def rate(kind: str | None) -> str:
        tot = [e for e in expected if kind is None or e["kind"] == kind]
        hit = [e for e in found if kind is None or e["kind"] == kind]
        return f"{len(hit)}/{len(tot)} = {100 * len(hit) / len(tot):.0f}%"

    result.update({
        "recall": rate(None), "recallStatic": rate("S"), "recallJudgment": rate("J"),
        "missed": [f"{e['id']} ({'/'.join(sorted(e['rules']))})" for e in missed],
        "extraFindings": [f"{f.get('id')} {f.get('object', '')}" for f in unmatched],
    })
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--fixture", choices=("bad", "good"), required=True)
    ap.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = grade(a.run_dir.resolve(), a.fixture, a.expected)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        for k, v in res.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
