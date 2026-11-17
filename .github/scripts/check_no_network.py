#!/usr/bin/env python3
"""Fail if any skill script contains networking code.

Scans every *.py file under skills/ with the ast module and rejects:
  * imports of networking / remote-execution modules
  * string literals that look like URLs or network CLI invocations
Runs on the Python standard library only.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

FORBIDDEN_MODULES = {
    "socket", "ssl", "http", "urllib", "urllib2", "urllib3", "ftplib", "smtplib",
    "poplib", "imaplib", "nntplib", "telnetlib", "xmlrpc", "socketserver",
    "asyncio", "webbrowser", "requests", "httpx", "aiohttp", "websocket",
    "websockets", "paramiko", "pycurl", "grpc",
}
FORBIDDEN_STRINGS = re.compile(
    r"(https?://|ftp://|\bcurl\b|\bwget\b|Invoke-WebRequest|Invoke-RestMethod|\bnc\b\s)",
    re.IGNORECASE,
)


def scan(path: Path) -> list[str]:
    problems: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "__import__":
            names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        for name in names:
            if name.split(".")[0] in FORBIDDEN_MODULES:
                problems.append(f"{path}:{node.lineno}: forbidden import '{name}'")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Docstrings may mention the words; only flag non-docstring literals.
            if FORBIDDEN_STRINGS.search(node.value) and not _is_docstring(node, tree):
                problems.append(f"{path}:{node.lineno}: network-looking string {node.value[:60]!r}")
    return problems


def _is_docstring(node: ast.AST, tree: ast.AST) -> bool:
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(parent, "body", [])
            if body and isinstance(body[0], ast.Expr) and body[0].value is node:
                return True
    return False


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "skills")
    files = sorted(root.rglob("*.py"))
    problems = [p for f in files for p in scan(f)]
    for p in problems:
        print(p)
    print(f"Scanned {len(files)} file(s): {'FAIL' if problems else 'OK, no network code'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
