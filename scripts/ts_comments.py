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
token: an operand (identifier, literal, ``)``, ``]``, the ``}`` of an object,
postfix ``++``, ``--`` or non-null ``!``) means division, except the ``)``
closing an ``if``/``for``/``while``/``with`` condition, the ``}`` closing a
block or body, and a keyword such as ``return``. A word after ``.`` or ``?.`` is
a property name, never a keyword: ``obj.if(x) / 2`` divides. With ``jsx=True``
(a ``.tsx`` file) a ``<`` where an operand is expected opens a JSX element,
whose text is neither code nor comment: ``https://x`` or ``Don't`` there is
prose, unless the name is followed (across whitespace and comments) by what
makes it a generic parameter list.

Only comment characters are ever replaced, but a misread ``/`` can still blank
code: a regex read as division leaves its ``//`` or ``/*`` to be taken as a
comment. Each rule above closes one such misreading on valid source; the
tokenizer is not a parser, and syntax it does not know can still fool it.
"""

from __future__ import annotations

import re
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

#: Keywords after which a ``{`` opens a block, although a ``/`` after them
#: would open a regex: every other keyword in ``_REGEX_AFTER_KEYWORDS`` is
#: followed by an expression, where ``{`` is an object.
_BLOCK_AFTER_KEYWORDS: Final = frozenset({"do", "else"})

#: What follows the name in ``<T``, once whitespace and comments are skipped,
#: when it is a generic type parameter list, not a JSX tag: ``<T,>`` or
#: ``<T = U>``. ``<T extends U>`` is matched separately, since ``extends`` must
#: be followed by trivia to be a word on its own.
_GENERIC_AFTER_NAME: Final = re.compile(r"[,=]")


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char in "_$"


def _opens_block(previous: str) -> bool:
    """Whether a ``{`` after the token ``previous`` opens a block, not an object.

    A block follows a statement boundary, a ``)`` (a function, method, ``if`` or
    ``switch`` body), an ``=>``, or a declaration's name (``class X {``). An
    object follows an operator or an expression keyword (``return {``).
    """
    if previous in {"", ")", ";", "{", "}", "=>"}:
        return True
    if _is_word_char(previous[0]):
        return previous not in _REGEX_AFTER_KEYWORDS or previous in _BLOCK_AFTER_KEYWORDS
    return False


def _skip_trivia(source: str, i: int) -> int:
    """Index of the first character at or after ``i`` that is not whitespace or comment."""
    while i < len(source):
        if source[i].isspace():
            i += 1
        elif source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end == -1 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = len(source) if end == -1 else end + 2
        else:
            break
    return i


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
        # Per open ``{``: whether it opens a block, whose ``}`` ends no operand.
        blocks: list[bool] = []
        # Per open ``(``: whether it holds an if/for/while/with condition.
        conditions: list[bool] = []
        operand_expected = True
        word = ""
        # Whether the previous token was ``.``, so a word now is a property name.
        after_dot = False
        # The previous token: a word, a punctuator, or ``'`` for any literal.
        previous = ""
        while self.i < len(source):
            char = source[self.i]
            if char.isspace() or self._comment():
                self.i += char.isspace()
                continue
            previous_word, word = word, ""
            previous_token = previous
            member, after_dot = after_dot, False
            if _is_word_char(char):
                end = self.i
                while end < len(source) and _is_word_char(source[end]):
                    end += 1
                # A property is an operand whatever it is called: ``obj.return``.
                word = "" if member else source[self.i : end]
                previous = source[self.i : end]
                operand_expected = word in _REGEX_AFTER_KEYWORDS
                self.i = end
                continue
            if source.startswith(("++", "--"), self.i):
                # Postfix ends an operand, prefix still awaits one: no change.
                previous = source[self.i : self.i + 2]
                self.i += 2
                continue
            if char == "!" and not operand_expected and not source.startswith("!=", self.i):
                # A non-null assertion ``n!`` ends an operand, as postfix ``++`` does.
                previous = char
                self.i += 1
                continue
            if source.startswith("=>", self.i):
                previous = "=>"
                self.i += 2
                operand_expected = True
                continue
            previous = char
            if char in "'\"":
                self.i = _string_end(source, self.i)
                previous = "'"
                operand_expected = False
                continue
            if char == "`":
                self._template()
                previous = "'"
                operand_expected = False
                continue
            if char == "/" and operand_expected:
                self.i = _regex_end(source, self.i) or self.i + 1
                previous = "'"
                operand_expected = False
                continue
            if char == "<" and operand_expected and self._jsx_starts():
                self._element()
                previous = "'"
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
            elif char == ".":
                after_dot = True
                operand_expected = True
            elif char == "{":
                blocks.append(_opens_block(previous_token))
                operand_expected = True
            elif char == "}":
                if nested and not blocks:
                    return
                # After a block a statement starts, so a ``/`` opens a regex.
                operand_expected = blocks.pop() if blocks else False
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
        after = _skip_trivia(source, end)
        if _GENERIC_AFTER_NAME.match(source, after):
            return False
        if not source.startswith("extends", after):
            return True
        return _skip_trivia(source, after + len("extends")) == after + len("extends")

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
