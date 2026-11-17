"""Tiny DAX lexer + call-tree builder (stdlib only).

Not a full DAX parser. It is enough to answer questions such as "is FILTER over a whole
table used as a CALCULATE argument?" or "which columns and measures does this expression
reference?" without regex false positives inside strings and comments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|--[^\n]*|/\*.*?\*/)
  | (?P<string>"(?:[^"]|"")*")
  | (?P<qtable>'(?:[^']|'')*')
  | (?P<bracket>\[(?:[^\]]|\]\])*\])
  | (?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<ident>[A-Za-z_][\w.]*)
  | (?P<op>:=|<=|>=|<>|==|&&|\|\||[-+*/^&=<>!])
  | (?P<lparen>\()
  | (?P<rparen>\))
  | (?P<lbrace>\{)
  | (?P<rbrace>\})
  | (?P<comma>,)
  | (?P<other>.)
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass
class Token:
    type: str          # string|qtable|bracket|number|ident|op|lparen|rparen|lbrace|rbrace|comma|colref|other
    value: str         # raw text (for colref: the whole 'T'[C])
    line: int          # 0-based line inside the expression
    table: str | None = None   # for qtable / ident / colref
    column: str | None = None  # for bracket / colref (bracket: the name inside [])


@dataclass
class Call:
    name: str
    line: int
    args: list[list["Node"]] = field(default_factory=list)


@dataclass
class Group:            # ( ... ) or { ... }
    kind: str           # "paren" | "brace"
    line: int
    items: list["Node"] = field(default_factory=list)


Node = "Token | Call | Group"


def tokenize(expr: str) -> list[Token]:
    raw: list[tuple[str, str, int, int]] = []
    line = 0
    for m in _TOKEN_RE.finditer(expr or ""):
        kind = m.lastgroup or "other"
        text = m.group()
        if kind not in ("ws", "comment"):
            raw.append((kind, text, line, m.start()))
        line += text.count("\n")
    tokens: list[Token] = []
    i = 0
    while i < len(raw):
        kind, text, ln, start = raw[i]
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        if kind in ("qtable", "ident") and nxt and nxt[0] == "bracket" and nxt[3] == start + len(text):
            table = text[1:-1].replace("''", "'") if kind == "qtable" else text
            tokens.append(Token("colref", text + nxt[1], ln, table=table, column=_bracket_name(nxt[1])))
            i += 2
            continue
        if kind == "qtable":
            tokens.append(Token("qtable", text, ln, table=text[1:-1].replace("''", "'")))
        elif kind == "bracket":
            tokens.append(Token("bracket", text, ln, column=_bracket_name(text)))
        elif kind == "ident":
            tokens.append(Token("ident", text, ln, table=text))
        else:
            tokens.append(Token(kind, text, ln))
        i += 1
    return tokens


def _bracket_name(text: str) -> str:
    return text[1:-1].replace("]]", "]")


def build_tree(tokens: list[Token]) -> list[Node]:
    pos = 0

    def seq(stop: set[str]) -> list:
        nonlocal pos
        items: list = []
        while pos < len(tokens):
            t = tokens[pos]
            if t.type in stop:
                return items
            if t.type == "ident" and pos + 1 < len(tokens) and tokens[pos + 1].type == "lparen":
                call = Call(name=t.value.upper(), line=t.line)
                pos += 2
                cur: list = []
                while pos < len(tokens):
                    cur.extend(seq({"comma", "rparen"}))
                    if pos >= len(tokens):
                        break
                    if tokens[pos].type == "comma":
                        call.args.append(cur)
                        cur = []
                        pos += 1
                        continue
                    pos += 1  # rparen
                    break
                if cur or call.args:
                    call.args.append(cur)
                items.append(call)
                continue
            if t.type in ("lparen", "lbrace"):
                closing = "rparen" if t.type == "lparen" else "rbrace"
                grp = Group("paren" if t.type == "lparen" else "brace", t.line)
                pos += 1
                grp.items = seq({closing})
                pos += 1
                items.append(grp)
                continue
            if t.type in ("rparen", "rbrace"):
                pos += 1  # unbalanced; skip
                continue
            items.append(t)
            pos += 1
        return items

    out: list = []
    while pos < len(tokens):
        out.extend(seq(set()))
    return out


def walk(nodes) -> "iter":
    """Yield every Call, Group and Token in the tree (pre-order)."""
    stack = list(reversed(list(nodes)))
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, Call):
            for arg in reversed(n.args):
                stack.extend(reversed(arg))
        elif isinstance(n, Group):
            stack.extend(reversed(n.items))


def calls(nodes, *names: str) -> list[Call]:
    wanted = {n.upper() for n in names}
    return [n for n in walk(nodes) if isinstance(n, Call) and (not wanted or n.name in wanted)]


def parse(expr: str) -> list[Node]:
    return build_tree(tokenize(expr))


def strip_var_names(expr: str) -> set[str]:
    """Names declared with VAR (case-insensitive) so they are not mistaken for tables."""
    return {m.group(1).lower() for m in re.finditer(r"(?i)\bVAR\s+([A-Za-z_]\w*)", expr or "")}
