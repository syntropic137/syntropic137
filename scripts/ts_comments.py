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
literals (multi-line, with nested ``${...}`` expressions), regex literals and
both comment forms. Whether a ``/`` opens a regex is decided by the previous
token: an operand (identifier, literal, ``)``, ``]``, ``}``, postfix ``++`` or
``--``) means division, except the ``)`` closing an ``if``/``for``/``while``/
``with`` condition and a keyword such as ``return``. With ``jsx=True`` (a
``.tsx`` file) a ``<`` where an operand is expected opens a JSX element, whose
text is neither code nor comment: ``https://x`` or ``Don't`` there is prose.

Every misreading it can make errs towards keeping text, never towards blanking
code: only comment characters are ever replaced.
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

#: Keywords whose parenthesised condition is followed by a statement, so the
#: ``)`` closing it is not an operand and a ``/`` after it opens a regex.
_CONDITION_KEYWORDS: Final = frozenset({"if", "for", "while", "with"})


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char in "_$"


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


class _Scanner:
    """One pass over ``source``, blanking comments in ``out`` as it finds them."""

    def __init__(self, source: str, *, jsx: bool) -> None:
        self.source = source
        self.out = list(source)
        self.jsx = jsx
        self.i = 0

    def _comment(self) -> bool:
        """Blank a comment starting at ``i``, if one does; whether it did."""
        source, i = self.source, self.i
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = len(source) if end == -1 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = len(source) if end == -1 else end + 2
        else:
            return False
        for k in range(i, end):
            if self.out[k] != "\n":
                self.out[k] = " "
        self.i = end
        return True

    def code(self, *, nested: bool) -> None:
        """Scan code to the end, or when ``nested`` past the ``}`` that closes it."""
        source = self.source
        depth = 0
        # Per open ``(``: whether it holds an if/for/while/with condition.
        conditions: list[bool] = []
        operand_expected = True
        word = ""
        while self.i < len(source):
            char = source[self.i]
            if char.isspace() or self._comment():
                self.i += char.isspace()
                continue
            previous_word, word = word, ""
            if _is_word_char(char):
                end = self.i
                while end < len(source) and _is_word_char(source[end]):
                    end += 1
                word = source[self.i : end]
                operand_expected = word in _REGEX_AFTER_KEYWORDS
                self.i = end
                continue
            if source.startswith(("++", "--"), self.i):
                # Postfix ends an operand, prefix still awaits one: no change.
                self.i += 2
                continue
            if char in "'\"":
                self.i = _string_end(source, self.i)
                operand_expected = False
                continue
            if char == "`":
                self._template()
                operand_expected = False
                continue
            if char == "/" and operand_expected:
                self.i = _regex_end(source, self.i) or self.i + 1
                operand_expected = False
                continue
            if char == "<" and operand_expected and self._jsx_starts():
                self._element()
                operand_expected = False
                continue
            self.i += 1
            if char == "(":
                conditions.append(previous_word in _CONDITION_KEYWORDS)
                operand_expected = True
            elif char == ")":
                operand_expected = conditions.pop() if conditions else False
            elif char == "]":
                operand_expected = False
            elif char == "{":
                depth += 1
                operand_expected = True
            elif char == "}":
                if nested and depth == 0:
                    return
                depth = max(depth - 1, 0)
                operand_expected = False
            else:
                operand_expected = True

    def _template(self) -> None:
        """Scan a template literal from its opening backtick."""
        source = self.source
        self.i += 1
        while self.i < len(source):
            char = source[self.i]
            if char == "\\":
                self.i += 2
            elif char == "`":
                self.i += 1
                return
            elif source.startswith("${", self.i):
                self.i += 2
                self.code(nested=True)
            else:
                self.i += 1

    def _jsx_starts(self) -> bool:
        """Whether the ``<`` at ``i`` opens a JSX element, not a generic ``<T,>``."""
        if not self.jsx:
            return False
        source, end = self.source, self.i + 1
        if source.startswith(">", end):
            return True
        if end >= len(source) or not (source[end].isalpha() or source[end] in "_$"):
            return False
        while end < len(source) and (_is_word_char(source[end]) or source[end] in ".-:"):
            end += 1
        rest = source[end:].lstrip(" \t")
        return not rest.startswith(",") and not rest.startswith("extends ")

    def _tag(self) -> bool:
        """Scan a JSX tag from just after its ``<``; whether it closed itself."""
        source = self.source
        while self.i < len(source):
            char = source[self.i]
            if self._comment():
                continue
            if char in "'\"":
                self.i = _string_end(source, self.i)
            elif char == "{":
                self.i += 1
                self.code(nested=True)
            elif source.startswith("/>", self.i):
                self.i += 2
                return True
            elif char == ">":
                self.i += 1
                return False
            else:
                self.i += 1
        return True

    def _element(self) -> None:
        """Scan a JSX element from its ``<``; its text is prose and kept as is."""
        source = self.source
        self.i += 1
        open_elements = 0 if self._tag() else 1
        while open_elements and self.i < len(source):
            char = source[self.i]
            if char == "{":
                self.i += 1
                self.code(nested=True)
            elif source.startswith("</", self.i):
                self.i += 2
                self._tag()
                open_elements -= 1
            elif char == "<":
                self.i += 1
                open_elements += 0 if self._tag() else 1
            else:
                self.i += 1


def blank_ts_comments(source: str, *, jsx: bool = False) -> str:
    """Return ``source`` with comment text replaced by spaces, newlines kept.

    Pass ``jsx=True`` for a ``.tsx`` file, so element text is read as prose.
    """
    scanner = _Scanner(source, jsx=jsx)
    scanner.code(nested=False)
    return "".join(scanner.out)
