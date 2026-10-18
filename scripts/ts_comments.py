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
block or a declaration's body, and a keyword such as ``return``. A ``{`` after
a label or ``case`` colon opens a block; the body of a ``function`` or
``class`` expression ends an operand (``function() {} / 2`` divides). A word after ``.`` or ``?.`` is
a property name, never a keyword: ``obj.if(x) / 2`` divides. With ``jsx=True``
(a ``.tsx`` file) a ``<`` where an operand is expected opens a JSX element,
whose text is neither code nor comment: ``https://x`` or ``Don't`` there is
prose, unless the name, after an optional ``const`` modifier, is followed
(across whitespace and comments) by what makes it a generic parameter list.

Only comment characters are ever replaced, but a misread ``/`` can still blank
code: a regex read as division leaves its ``//`` or ``/*`` to be taken as a
comment. Each rule above closes one such misreading on valid source; the
tokenizer is not a parser, and syntax it does not know can still fool it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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

#: Tokens after which, when an operand is expected, a statement starts. A
#: ``)`` or ``}`` expects an operand only when it closes a condition or a
#: block, and ``{`` only when it opens a block (checked separately).
_STATEMENT_AFTER: Final = frozenset({"", ";", ")", "}", "else", "do"})

#: Words that can only precede a declaration, so a ``function`` or ``class``
#: after one is declared, not an expression: ``export default function () {}``.
_DECLARATION_MODIFIERS: Final = frozenset({"export", "default", "declare", "abstract"})

#: The ``previous`` token recorded for a label or ``case`` colon: like ``;``,
#: it ends a statement head, so a ``{`` after it opens a block.
_STATEMENT_COLON: Final = ";"


@dataclass
class _Frame:
    """What one open bracket (or the top level) holds of its colons' meaning."""

    #: ``(``, ``[``, ``{`` for a block or ``o`` for an object; ``""`` at top level.
    kind: str
    #: Ternary ``?`` still waiting for their ``:``.
    ternaries: int = 0
    #: ``case`` or ``default`` still waiting for their ``:``.
    cases: int = 0

    @property
    def holds_statements(self) -> bool:
        return self.kind in {"", "{"}


@dataclass
class _Brackets:
    """The open brackets around the scan position, and what each one means."""

    #: Per open ``{``: whether it opens a block, whose ``}`` ends no operand.
    blocks: list[bool] = field(default_factory=list[bool])
    #: Per open ``(``: whether it holds an if/for/while/with condition.
    conditions: list[bool] = field(default_factory=list[bool])
    #: Per open bracket, innermost last: how its colons read.
    frames: list[_Frame] = field(default_factory=lambda: [_Frame("")])
    #: Per ``function``/``class`` whose body is still ahead: the bracket depth
    #: its ``{`` will open at, and whether the body ends an operand.
    bodies: list[tuple[int, bool]] = field(default_factory=list[tuple[int, bool]])

    def statement_starts(self, previous: str, *, operand_expected: bool) -> bool:
        """Whether the token after ``previous`` starts a statement or declaration."""
        if previous in _DECLARATION_MODIFIERS:
            return True
        return operand_expected and (
            previous in _STATEMENT_AFTER or (previous == "{" and self.frames[-1].kind == "{")
        )

    def word(self, word: str, *, statement_starts: bool) -> None:
        """Note a word whose meaning a later ``{`` or ``:`` depends on."""
        if word in {"function", "class"}:
            # A declaration's body is a block; an expression's ends an operand.
            self.bodies.append((len(self.frames), not statement_starts))
        elif word in {"case", "default"}:
            self.frames[-1].cases += 1

    def open(self, char: str, *, previous_word: str, previous: str) -> None:
        """Open ``(``, ``[`` or ``{``, after the word and token before it."""
        if char == "(":
            self.conditions.append(previous_word in _CONDITION_KEYWORDS)
            self.frames.append(_Frame("("))
        elif char == "[":
            self.frames.append(_Frame("["))
        else:
            if self.bodies and self.bodies[-1][0] == len(self.frames):
                block = not self.bodies.pop()[1]
            else:
                block = _opens_block(previous)
            self.blocks.append(block)
            self.frames.append(_Frame("{" if block else "o"))

    def close(self, char: str) -> bool:
        """Close ``)``, ``]`` or ``}``; whether an operand is expected after it."""
        if len(self.frames) > 1:
            self.frames.pop()
        if char == ")":
            return self.conditions.pop() if self.conditions else False
        if char == "}":
            # After a block a statement starts, so a ``/`` opens a regex.
            return self.blocks.pop() if self.blocks else False
        return False

    def colon(self, *, labelled: bool) -> bool:
        """Read a ``:``; whether it ends a label or ``case`` head."""
        frame = self.frames[-1]
        if frame.ternaries:
            frame.ternaries -= 1
            return False
        if frame.holds_statements and (frame.cases or labelled):
            frame.cases -= 0 if labelled else 1
            return True
        return False

    def statement_end(self) -> None:
        """Read a ``;``: a body-less overload ``function f(): void;`` has no body to wait for."""
        while self.bodies and self.bodies[-1][0] == len(self.frames):
            self.bodies.pop()


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
        brackets = _Brackets()
        # Whether the previous token was a word that can be a statement label.
        label = False
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
            labelled, label = label, False
            statement_starts = brackets.statement_starts(
                previous_token, operand_expected=operand_expected
            )
            if _is_word_char(char):
                end = self.i
                while end < len(source) and _is_word_char(source[end]):
                    end += 1
                # A property is an operand whatever it is called: ``obj.return``.
                word = "" if member else source[self.i : end]
                if word == "async" and source.startswith("function", _skip_trivia(source, end)):
                    # ``async function`` is read as ``function`` in the same position.
                    self.i = end
                    continue
                brackets.word(word, statement_starts=statement_starts)
                label = statement_starts and brackets.frames[-1].holds_statements
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
            if char in "([{":
                brackets.open(char, previous_word=previous_word, previous=previous_token)
                operand_expected = True
            elif char in ")]}":
                if char == "}" and nested and not brackets.blocks:
                    return
                operand_expected = brackets.close(char)
            elif char == ".":
                after_dot = True
                operand_expected = True
            elif char == "?":
                if source.startswith("?", self.i):
                    self.i += 1
                elif not source.startswith(".", self.i):
                    brackets.frames[-1].ternaries += 1
                operand_expected = True
            else:
                if char == ":" and brackets.colon(labelled=labelled):
                    previous = _STATEMENT_COLON
                elif char == ";":
                    brackets.statement_end()
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
        if source[self.i + 1 : end] == "const" and _is_word_char(source[after : after + 1] or " "):
            # ``<const T,>``: the modifier is not the name; judge what follows it.
            end = after
            while end < len(source) and _is_word_char(source[end]):
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
