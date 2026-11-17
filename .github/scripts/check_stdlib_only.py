#!/usr/bin/env python3
"""Fail if any skill script imports a module outside the Python standard library.

Local sibling modules (other .py files in the same scripts/ folder) are allowed.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "skills")
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    problems: list[str] = []
    files = sorted(root.rglob("*.py"))
    for f in files:
        local = {p.stem for p in f.parent.glob("*.py")}
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module]
            else:
                continue
            for m in mods:
                top = m.split(".")[0]
                if top not in stdlib and top not in local:
                    problems.append(f"{f}:{node.lineno}: non-stdlib import '{m}'")
    for p in problems:
        print(p)
    print(f"Scanned {len(files)} file(s): {'FAIL' if problems else 'OK, stdlib only'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
