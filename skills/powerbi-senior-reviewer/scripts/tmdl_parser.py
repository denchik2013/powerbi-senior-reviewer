"""Minimal, dependency-free TMDL parser.

TMDL (Tabular Model Definition Language) is indentation based:

    table Sales                                  <- object declaration (indent 0)
        measure 'Total Sales' =                  <- child object with expression (indent 1)
                SUMX(Sales, Sales[Qty])          <- expression continuation (indent >= 3 = decl + 2)
            formatString: #,0                    <- property (indent 2 = decl + 1)
            isHidden                             <- flag property

Supported: tab or 4-space indentation, ``` fenced multi-line expressions, /// descriptions,
quoted names with '' escapes, `ref` declarations, property expressions such as `source =`.
Every node records its 1-based declaration line and the last line it spans.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PROP_RE = re.compile(r"^([A-Za-z_]\w*)\s*:\s?(.*)$")
PROP_EXPR_RE = re.compile(r"^([A-Za-z_]\w*)\s*=\s*(.*)$")


@dataclass
class Node:
    kind: str                      # declaration keyword ("table", "measure", ...), property key, or flag name
    name: str | None               # object name (None for properties / flags)
    line: int                      # 1-based line of the declaration
    indent: int
    style: str = "decl"            # decl | prop | flag | propexpr
    value: str | None = None       # property value
    expression: str | None = None  # expression text (dedented); line 0 of it sits at expr_line
    expr_line: int | None = None
    end_line: int = 0
    description: str | None = None
    children: list["Node"] = field(default_factory=list)

    # ---- convenience accessors -------------------------------------------------
    def prop(self, key: str, default: str | None = None) -> str | None:
        key_l = key.lower()
        for c in self.children:
            if c.style == "prop" and c.kind.lower() == key_l:
                return c.value
        return default

    def flag(self, key: str) -> bool:
        key_l = key.lower()
        for c in self.children:
            if c.kind.lower() == key_l:
                if c.style == "flag":
                    return True
                if c.style == "prop":
                    return (c.value or "").strip().lower() == "true"
        return False

    def child_expr(self, key: str) -> "Node | None":
        key_l = key.lower()
        for c in self.children:
            if c.style == "propexpr" and c.kind.lower() == key_l:
                return c
        return None

    def objects(self, kind: str) -> list["Node"]:
        kind_l = kind.lower()
        return [c for c in self.children if c.style == "decl" and c.kind.lower() == kind_l]

    def annotations(self) -> dict[str, str]:
        return {c.name or "": (c.expression or "").strip() for c in self.objects("annotation")}


def unquote_name(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('""', '"')
    return text


def _split_name(rest: str) -> tuple[str, str]:
    """Split "'My Name' = expr" into ("My Name", "= expr"). Handles '' escapes."""
    rest = rest.lstrip()
    if rest.startswith("'"):
        i = 1
        while i < len(rest):
            if rest[i] == "'":
                if i + 1 < len(rest) and rest[i + 1] == "'":
                    i += 2
                    continue
                return rest[1:i].replace("''", "'"), rest[i + 1:]
            i += 1
        return rest[1:].replace("''", "'"), ""
    m = re.match(r"([^\s=]+)(.*)$", rest)
    if not m:
        return "", rest
    return m.group(1), m.group(2)


def parse_column_ref(ref: str) -> tuple[str, str]:
    """Parse a relationship column reference such as Sales.'Order Date' or 'Dim Date'.Date."""
    ref = ref.strip()
    if ref.startswith("'"):
        table, rest = _split_name(ref)
    else:  # unquoted table names cannot contain dots
        table, _, tail = ref.partition(".")
        rest = "." + tail if tail else ""
    if rest.startswith("."):
        col = rest[1:].strip()
        return table, unquote_name(col)
    return table, ""


def _indent_of(raw: str) -> int:
    tabs = len(raw) - len(raw.lstrip("\t"))
    if tabs:
        return tabs
    spaces = len(raw) - len(raw.lstrip(" "))
    return spaces // 4


def _strip_indent(raw: str, levels: int) -> str:
    """Remove up to `levels` indentation units (tabs, or 4 spaces each)."""
    out = raw
    for _ in range(levels):
        if out.startswith("\t"):
            out = out[1:]
        elif out.startswith("    "):
            out = out[4:]
        else:
            break
    return out


class TmdlParser:
    def __init__(self, text: str):
        self.lines = text.splitlines()
        self.pos = 0

    def parse(self) -> list[Node]:
        return self._block(0)

    # ---------------------------------------------------------------------------
    def _block(self, min_indent: int) -> list[Node]:
        nodes: list[Node] = []
        desc: list[str] = []
        while self.pos < len(self.lines):
            raw = self.lines[self.pos]
            if not raw.strip():
                self.pos += 1
                continue
            ind = _indent_of(raw)
            if ind < min_indent:
                break
            content = raw.strip()
            if content.startswith("///"):
                desc.append(content[3:].strip())
                self.pos += 1
                continue
            node = self._parse_line(content, ind, self.pos + 1)
            node.description = "\n".join(desc) if desc else None
            desc = []
            self.pos += 1
            node.end_line = node.line
            if node.expression is not None:
                self._read_expression(node)
            node.children = self._block(ind + 1)
            for c in node.children:
                node.end_line = max(node.end_line, c.end_line)
            nodes.append(node)
        return nodes

    def _parse_line(self, content: str, ind: int, lineno: int) -> Node:
        m = PROP_RE.match(content)
        if m:
            return Node(kind=m.group(1), name=None, line=lineno, indent=ind, style="prop",
                        value=unquote_name(m.group(2)) if m.group(2).strip()[:1] in "'\"" else m.group(2).strip())
        m = PROP_EXPR_RE.match(content)
        if m:
            return Node(kind=m.group(1), name=None, line=lineno, indent=ind, style="propexpr",
                        expression=m.group(2), expr_line=lineno)
        parts = content.split(None, 1)
        if len(parts) == 1:
            return Node(kind=parts[0], name=None, line=lineno, indent=ind, style="flag")
        keyword, rest = parts
        if keyword == "ref":
            sub = rest.split(None, 1)
            keyword = "ref " + sub[0]
            rest = sub[1] if len(sub) > 1 else ""
        name, tail = _split_name(rest)
        tail = tail.strip()
        expr = tail[1:].lstrip() if tail.startswith("=") else None
        return Node(kind=keyword, name=name, line=lineno, indent=ind, style="decl",
                    expression=expr, expr_line=lineno if expr is not None else None)

    def _read_expression(self, node: Node) -> None:
        first = node.expression or ""
        if first.startswith("```"):
            inline = first[3:]
            if inline.rstrip().endswith("```") and inline.strip() != "":
                node.expression = inline.rstrip()[:-3].strip()
                return
            body: list[str] = []
            start = self.pos + 1
            while self.pos < len(self.lines):
                raw = self.lines[self.pos]
                self.pos += 1
                if raw.strip().startswith("```"):
                    node.end_line = self.pos
                    break
                body.append(raw)
            node.expression = _dedent(body)
            node.expr_line = start
            return
        collected: list[str] = [first] if first else []
        expr_line = node.line if first else None
        pending_blank = 0
        last_used = self.pos
        while self.pos < len(self.lines):
            raw = self.lines[self.pos]
            if not raw.strip():
                pending_blank += 1
                self.pos += 1
                continue
            if _indent_of(raw) < node.indent + 2:
                break
            if expr_line is None:
                expr_line = self.pos + 1
                pending_blank = 0  # leading blanks are not part of the expression
            collected.extend([""] * pending_blank)
            pending_blank = 0
            collected.append(_strip_indent(raw, node.indent + 2).rstrip())
            self.pos += 1
            last_used = self.pos
        self.pos = last_used if last_used > node.line else node.line
        node.expression = "\n".join(collected)
        node.expr_line = expr_line or node.line
        node.end_line = max(node.line, last_used)


def _dedent(lines: list[str]) -> str:
    non_blank = [ln for ln in lines if ln.strip()]
    if not non_blank:
        return ""
    common = min(_indent_of(ln) for ln in non_blank)
    return "\n".join(_strip_indent(ln, common).rstrip() for ln in lines).strip("\n")


def parse_tmdl(text: str) -> list[Node]:
    return TmdlParser(text).parse()
