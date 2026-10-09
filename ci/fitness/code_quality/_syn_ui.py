"""Shared scanning for the syn-ui data-layer fitness functions (ADR-074).

TypeScript, JavaScript and Svelte sources are tokenized by a small state
machine, not matched with comment regexes, so a string can never hide code
from the comment stripper (``" /* "; fetch(x); " */ "``) and a comment can
never hide a string. It knows strings, template literals (``${}`` nests),
comments and regex literals; that is all the checks need.

A ``.svelte`` file is scanned per region: ``<script>`` blocks are JavaScript,
``<style>`` blocks have only ``/* */`` comments, and markup has only
``<!-- -->`` comments. Markup is otherwise left as text, so ``{fetch(x)}`` in
markup is still seen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SYN_UI_APP = ROOT / "apps" / "syn-ui"
SYN_UI_PACKAGES = ROOT / "packages" / "syn-ui"
DATA = SYN_UI_PACKAGES / "data"

#: Source files the checks read.
SOURCE_SUFFIXES = frozenset({".ts", ".js", ".mjs", ".svelte"})
#: Build output and installed packages are never first-party source.
SKIP_DIRS = frozenset({"node_modules", "dist", ".dist", ".results", ".report", ".svelte-kit"})


@dataclass(frozen=True)
class Token:
    """A non-code span. ``kind``: str | tmpl | tmplpart | comment | regex.

    ``value`` is the literal's text without quotes (escapes kept). For ``tmpl``
    (a whole template literal) it is the static text with ``\\x00`` where each
    ``${}`` was, and ``static`` says there were none.
    """

    kind: str
    start: int
    end: int
    value: str = ""
    static: bool = True


_REGEX_AFTER_WORDS = frozenset(
    {
        "return",
        "typeof",
        "case",
        "do",
        "else",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "yield",
        "await",
    }
)
_REGEX_AFTER_CHARS = frozenset("(,=:[!&|?{};+-*%<>~^")


class _Lexer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens: list[Token] = []

    def code(self, i: int, end: int, *, until_brace: bool = False) -> int:
        """Scan code from ``i``; with ``until_brace`` stop at the ``}`` closing a ``${``."""
        text = self.text
        depth = 0
        while i < end:
            c = text[i]
            if c in "'\"":
                i = self._string(i, end)
            elif c == "`":
                i = self._template(i, end)
            elif text.startswith("//", i):
                j = text.find("\n", i)
                j = end if j < 0 or j > end else j
                self.tokens.append(Token("comment", i, j))
                i = j
            elif text.startswith("/*", i):
                j = text.find("*/", i + 2)
                j = end if j < 0 else min(j + 2, end)
                self.tokens.append(Token("comment", i, j))
                i = j
            elif c == "/" and self._regex_allowed(i):
                i = self._regex(i, end)
            elif c == "{":
                depth += 1
                i += 1
            elif c == "}":
                if until_brace and depth == 0:
                    return i
                depth -= 1
                i += 1
            else:
                i += 1
        return i

    def _string(self, i: int, end: int) -> int:
        quote = self.text[i]
        j = i + 1
        while j < end and self.text[j] != quote and self.text[j] != "\n":
            j += 2 if self.text[j] == "\\" else 1
        self.tokens.append(Token("str", i, min(j + 1, end), self.text[i + 1 : j]))
        return min(j + 1, end)

    def _template(self, i: int, end: int) -> int:
        text = self.text
        j = i + 1
        part = j
        static: list[str] = []
        subs = False
        while j < end and text[j] != "`":
            if text[j] == "\\":
                j += 2
                continue
            if text.startswith("${", j):
                self.tokens.append(Token("tmplpart", part, j))
                static.append(text[part:j] + "\x00")
                subs = True
                j = self.code(j + 2, end, until_brace=True) + 1
                part = j
                continue
            j += 1
        self.tokens.append(Token("tmplpart", part, min(j, end)))
        static.append(text[part : min(j, end)])
        self.tokens.append(Token("tmpl", i, min(j + 1, end), "".join(static), not subs))
        return min(j + 1, end)

    def _regex_allowed(self, i: int) -> bool:
        j = i - 1
        while j >= 0 and self.text[j] in " \t\r\n":
            j -= 1
        if j < 0:
            return True
        prev = self.text[j]
        if prev in _REGEX_AFTER_CHARS:
            return True
        m = re.search(r"[A-Za-z_$][\w$]*$", self.text[max(0, j - 12) : j + 1])
        return bool(m and m.group(0) in _REGEX_AFTER_WORDS)

    def _regex(self, i: int, end: int) -> int:
        j = i + 1
        in_class = False
        while j < end and self.text[j] != "\n":
            c = self.text[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                j += 1
                while j < end and (self.text[j].isalnum() or self.text[j] == "_"):
                    j += 1
                self.tokens.append(Token("regex", i, j, self.text[i:j]))
                return j
            j += 1
        return i + 1  # not a regex after all: a lone `/`


_SVELTE_BLOCK = re.compile(r"<(script|style)\b[^>]*>(.*?)</\1\s*>", re.DOTALL | re.IGNORECASE)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def tokens(text: str, *, svelte: bool = False) -> list[Token]:
    """Every string, template, comment and regex in ``text``, in source order."""
    lexer = _Lexer(text)
    if not svelte:
        lexer.code(0, len(text))
        return sorted(lexer.tokens, key=lambda t: t.start)
    pos = 0
    for block in _SVELTE_BLOCK.finditer(text):
        _markup_comments(lexer, text, pos, block.start())
        start, end = block.start(2), block.end(2)
        if block.group(1).lower() == "script":
            lexer.code(start, end)
        else:
            lexer.tokens += [
                Token("comment", m.start(), m.end())
                for m in _CSS_COMMENT.finditer(text, start, end)
            ]
        pos = block.end()
    _markup_comments(lexer, text, pos, len(text))
    return sorted(lexer.tokens, key=lambda t: t.start)


def _markup_comments(lexer: _Lexer, text: str, start: int, end: int) -> None:
    lexer.tokens += [
        Token("comment", m.start(), m.end()) for m in _HTML_COMMENT.finditer(text, start, end)
    ]


def is_svelte(path: str | Path) -> bool:
    return str(path).endswith(".svelte")


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    out = list(text)
    for start, end in spans:
        for k in range(start, end):
            if out[k] != "\n":
                out[k] = " "
    return "".join(out)


def strip_comments(text: str, *, svelte: bool = False) -> str:
    """Blank comments (strings kept), keeping offsets and line numbers stable."""
    return _blank(
        text, [(t.start, t.end) for t in tokens(text, svelte=svelte) if t.kind == "comment"]
    )


def code_only(text: str, *, svelte: bool = False) -> str:
    """Blank comments and the insides of strings, templates and regexes (quotes kept)."""
    spans: list[tuple[int, int]] = []
    for t in tokens(text, svelte=svelte):
        if t.kind == "comment":
            spans.append((t.start, t.end))
        elif t.kind in ("str", "regex"):
            spans.append((t.start + 1, t.end - 1))
        elif t.kind == "tmplpart":
            spans.append((t.start, t.end))
    return _blank(text, spans)


def source_files(root: Path) -> list[Path]:
    """Every TS/JS/Svelte file under ``root``, skipping build output and dependencies."""
    if not root.exists():
        return []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in SOURCE_SUFFIXES
        and not SKIP_DIRS.intersection(p.relative_to(root).parts)
    )


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


# ---------------------------------------------------------------------------
# Module specifiers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleRef:
    """One import / export-from / dynamic import / require.

    ``spec`` is the module string, or None when a dynamic import's argument is
    not a literal. ``names`` are the imported (or re-exported) original names;
    ``namespace`` marks ``import * as`` / ``export *``; ``reexport`` marks
    ``export ... from``; ``type_only`` marks ``import type`` / ``export type``.
    """

    line: int
    spec: str | None
    names: tuple[str, ...] = ()
    namespace: bool = False
    reexport: bool = False
    type_only: bool = False
    dynamic: bool = False


def _literal_at(toks: dict[int, Token], code: str, i: int) -> tuple[Token | None, int]:
    """The static string literal starting at ``i`` (after whitespace), if any."""
    while i < len(code) and code[i].isspace():
        i += 1
    t = toks.get(i)
    if t and (t.kind == "str" or (t.kind == "tmpl" and t.static)):
        return t, t.end
    return None, i


def _names(clause: str) -> tuple[str, ...]:
    """`{ a, b as c, type d }` -> ('a', 'b', 'd')."""
    inner = clause[clause.find("{") + 1 : clause.rfind("}")] if "{" in clause else ""
    out = []
    for part in inner.split(","):
        words = part.replace("type ", " ").split()
        if words:
            out.append(words[0])
    return tuple(out)


#: `import x, { a } from 's'`, `export * from 's'`, `import type {..} from`, `import 's'`. The clause
#: holds only names, braces, commas and `*`, and never another import/export keyword.
_STATIC = re.compile(
    r"(?<![\w$.])(import|export)\b(\s+type\b)?((?:(?!\b(?:import|export)\b)[\w$\s{},*])*?)\bfrom\s*(?=['\"`])"
    r"|(?<![\w$.])import\s*(?=['\"`])"
)
_DYNAMIC = re.compile(r"(?<![\w$.])(import|require)\s*\(")


def module_refs(text: str, *, svelte: bool = False) -> list[ModuleRef]:
    """Every module reference in ``text``; strings and comments cannot fake or hide one."""
    toks = {t.start: t for t in tokens(text, svelte=svelte) if t.kind in ("str", "tmpl")}
    code = code_only(text, svelte=svelte)
    out: list[ModuleRef] = []
    for m in _STATIC.finditer(code):
        lit, _ = _literal_at(toks, code, m.end())
        if not lit:
            continue
        clause = m.group(3) or ""
        out.append(
            ModuleRef(
                line_of(code, m.start()),
                lit.value,
                names=_names(clause),
                namespace="*" in clause,
                reexport=m.group(1) == "export",
                type_only=bool(m.group(2)),
            )
        )
    for m in _DYNAMIC.finditer(code):
        lit, after = _literal_at(toks, code, m.end())
        rest = code[after:].lstrip()[:1]
        # `import('a' + x)` is not a literal import: only `import('a')` / `import('a', opts)` resolve.
        spec = lit.value if lit is not None and rest in (")", ",") else None
        out.append(ModuleRef(line_of(code, m.start()), spec, dynamic=True))
    return sorted(out, key=lambda r: r.line)


def local_exports(text: str, *, svelte: bool = False) -> set[str]:
    """Names in `export { a, b as c }` lists that have no `from` (local bindings re-exported)."""
    code = code_only(text, svelte=svelte)
    return {
        name
        for m in re.finditer(r"(?<![\w$.])export\s+(?:type\s+)?(\{[^}]*\})(?!\s*from\b)", code)
        for name in _names(m.group(1))
    }


_RESOLVE_SUFFIXES = ("", ".ts", ".js", ".mjs", ".svelte", "/index.ts", "/index.js")


def resolve_relative(importer: Path, spec: str) -> Path | None:
    """The file a relative specifier names (``./x``, ``../x.svelte``, ``./x.js`` for ``x.ts``)."""
    if not spec.startswith("."):
        return None
    base = (importer.parent / spec).resolve()
    candidates = [Path(f"{base}{s}") for s in _RESOLVE_SUFFIXES]
    if base.suffix == ".js":
        candidates.append(base.with_suffix(".ts"))
    return next((c for c in candidates if c.is_file()), None)
