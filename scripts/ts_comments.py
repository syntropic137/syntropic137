"""Blank the comments out of TypeScript source, keeping every position (#1631).

A literal scanner that reads raw lines also reads prose: a backticked
``sessionId`` in a ``//`` comment looks exactly like one in code. This module
answers the one question such a scanner needs: which characters are comment.

``blank_ts_comments`` returns the source with every comment character replaced
by a space and every newline kept, so line and column numbers are unchanged
and a per-line scanner can run on the result as it did on the original. String,
template and regex literals are code and are left intact, including a ``//``
or ``/*`` inside them.

The tokenizer is deliberately small. It knows strings (with escapes), template
literals (multi-line, with nested ``${...}`` expressions), regex literals (by
the usual previous-token rule, including ``[...]`` classes) and both comment
forms. It does not parse JSX: in JSX text a ``//`` is blanked as a comment,
which a TypeScript scanner of code literals can afford.
"""

from __future__ import annotations

from typing import Final

#: Keywords after which a ``/`` starts a regex rather than dividing.
_REGEX_AFTER_KEYWORDS: Final = frozenset(
    {
        "return",
        "typeof",
        "instanceof",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "case",
        "do",
        "else",
        "yield",
        "await",
    }
)

#: A ``/`` after one of these ends an operand, so it divides.
_OPERAND_END: Final = frozenset(")]}'\"`")


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char in "_$"


def _starts_regex(out: list[str], slash: int) -> bool:
    """Whether the ``/`` at ``slash`` opens a regex, judged by the previous token."""
    j = slash - 1
    while j >= 0 and out[j].isspace():
        j -= 1
    if j < 0:
        return True
    if out[j] in _OPERAND_END:
        return False
    if not _is_word_char(out[j]):
        return True
    end = j + 1
    while j >= 0 and _is_word_char(out[j]):
        j -= 1
    return "".join(out[j + 1 : end]) in _REGEX_AFTER_KEYWORDS


def _regex_end(source: str, slash: int) -> int | None:
    """Index just past the regex opened at ``slash``, or None if it is not one."""
    i, in_class = slash + 1, False
    while i < len(source):
        char = source[i]
        if char == "\n":
            return None
        if char == "\\":
            i += 2
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return i + 1
        i += 1
    return None


def _string_end(source: str, quote: int) -> int:
    """Index just past the ``'`` or ``"`` string opened at ``quote``.

    An unterminated string stops at the newline, as the language does, so one
    stray apostrophe cannot swallow the rest of the file.
    """
    i = quote + 1
    while i < len(source):
        char = source[i]
        if char == "\\":
            i += 2
            continue
        if char == source[quote]:
            return i + 1
        if char == "\n":
            return i
        i += 1
    return i


def _template_end(source: str, start: int) -> tuple[int, bool]:
    """Scan template text from ``start``: (index past it, whether ``${`` opened)."""
    i = start
    while i < len(source):
        char = source[i]
        if char == "\\":
            i += 2
            continue
        if char == "`":
            return i + 1, False
        if source.startswith("${", i):
            return i + 2, True
        i += 1
    return i, False


def _blank(out: list[str], start: int, end: int) -> None:
    for k in range(start, end):
        if out[k] != "\n":
            out[k] = " "


def blank_ts_comments(source: str) -> str:
    """Return ``source`` with comment text replaced by spaces, newlines kept."""
    out = list(source)
    # Brace depth inside each enclosing template ``${...}``; at 0 a ``}`` closes it.
    expressions: list[int] = []
    i = 0
    while i < len(source):
        char = source[i]
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = len(source) if end == -1 else end
            _blank(out, i, end)
            i = end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = len(source) if end == -1 else end + 2
            _blank(out, i, end)
            i = end
        elif char in "'\"":
            i = _string_end(source, i)
        elif char == "`" or (char == "}" and expressions and expressions[-1] == 0):
            if char == "}":
                expressions.pop()
            i, opened = _template_end(source, i + 1)
            if opened:
                expressions.append(0)
        elif char == "/" and _starts_regex(out, i):
            i = _regex_end(source, i) or i + 1
        else:
            if expressions and char == "{":
                expressions[-1] += 1
            elif expressions and char == "}":
                expressions[-1] -= 1
            i += 1
    return "".join(out)
