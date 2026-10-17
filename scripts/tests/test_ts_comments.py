"""``blank_ts_comments`` blanks comments and nothing else (#1631).

Each case is a trap a naive "delete from ``//`` to end of line" gets wrong:
a ``//`` or ``/*`` inside a string, template or regex literal is code, and an
escaped quote does not end a string. Every result must also keep the source's
length and newlines, or the harness-format gate reports wrong line numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ts_comments import blank_ts_comments


def blanked(source: str) -> str:
    out = blank_ts_comments(source)
    assert len(out) == len(source)
    assert [i for i, c in enumerate(out) if c == "\n"] == [
        i for i, c in enumerate(source) if c == "\n"
    ]
    return out


def spaced(source: str, comment: str) -> str:
    """``source`` with ``comment`` (which it must contain) blanked by hand."""
    assert comment in source
    return source.replace(comment, "".join(c if c == "\n" else " " for c in comment))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "comment"),
    [
        ("const a = 1 // `sessionId`", "// `sessionId`"),
        ("a /* 'agentId' */ b", "/* 'agentId' */"),
        ("/* one\n 'isSidechain'\n*/ x", "/* one\n 'isSidechain'\n*/"),
        ("x // a /* b\ny", "// a /* b"),
        ("x /* a // b */ y", "/* a // b */"),
        ("x /* never closed\n'sessionId'", "/* never closed\n'sessionId'"),
        ("{/* JSX comment */}", "/* JSX comment */"),
    ],
)
def test_comments_are_blanked(source: str, comment: str) -> None:
    assert blanked(source) == spaced(source, comment)


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "const url = 'https://x'; const k = `sessionId`",
        'const url = "https://x/*"; const k = "agentId"',
        "const t = `http://a ${b} /* not a comment */`",
        "const t = `line one\n// still template\n`",
        "const s = 'it\\'s // not a comment'",
        'const s = "say \\"/*\\" here"',
        "const re = /\\/\\/'turn_context'/g",
        "const re = /[/*]'agentId'/",
        "if (x) return /'sessionId'/.test(y)",
        "const half = a / b / c",
    ],
)
def test_literals_and_operators_are_code(source: str) -> None:
    assert blanked(source) == source


@pytest.mark.unit
def test_comment_after_a_literal_on_the_same_line_is_still_blanked() -> None:
    source = "const url = 'https://x' // `sessionId`"
    assert blanked(source) == spaced(source, "// `sessionId`")


@pytest.mark.unit
def test_template_expressions_nest_and_their_comments_are_blanked() -> None:
    source = "`a ${ {k: 1}[`k`] /* `agentId` */ } b // c` // `sessionId`"
    expected = spaced(spaced(source, "/* `agentId` */"), "// `sessionId`")
    assert blanked(source) == expected


@pytest.mark.unit
def test_division_after_an_operand_does_not_start_a_regex() -> None:
    # Read as a regex, ``/ 2 // `` would hide the comment after it.
    source = "const r = (a) / 2 // `sessionId`"
    assert blanked(source) == spaced(source, "// `sessionId`")


@pytest.mark.unit
def test_an_unterminated_string_stops_at_the_newline() -> None:
    source = "<p>Don't</p>\n// `sessionId`"
    assert blanked(source) == spaced(source, "// `sessionId`")
