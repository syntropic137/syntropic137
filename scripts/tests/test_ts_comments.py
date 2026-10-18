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


def blanked(source: str, *, jsx: bool = False) -> str:
    out = blank_ts_comments(source, jsx=jsx)
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
    ids=[
        "line",
        "block",
        "multiline-block",
        "block-opener-in-line",
        "line-in-block",
        "unclosed-block",
        "jsx",
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
        "if (ok) /[//]/.test(x); const k = 'agentId'",
        "while (ok) /[/*]/.exec(x)",
        "const t = `x ${(() => { if (ok) /[//]/.test(x); return 'agentId' })()}`",
    ],
    ids=[
        "url-in-string",
        "block-opener-in-string",
        "template",
        "multiline-template",
        "escaped-single-quote",
        "escaped-double-quote",
        "regex-escaped-slashes",
        "regex-class",
        "regex-after-return",
        "division",
        "regex-after-if-condition",
        "regex-after-while-condition",
        "regex-after-condition-in-template-expression",
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


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "let x = n++ / 2 // `sessionId`",
        "let x = n-- / 2 // `sessionId`",
        "f(a) / 2 // `sessionId`",
        "obj.if(x) / 2 // `sessionId`",
        "obj.while(x) / 2 // `sessionId`",
        "obj.for(x) / 2 // `sessionId`",
        "obj.with(x) / 2 // `sessionId`",
        "obj?.if(x) / 2 // `sessionId`",
        "obj.\n  if(x) / 2 // `sessionId`",
        "obj.return / 2 // `sessionId`",
    ],
    ids=[
        "postfix-increment",
        "postfix-decrement",
        "call",
        "method-named-if",
        "method-named-while",
        "method-named-for",
        "method-named-with",
        "optional-method-named-if",
        "method-named-if-on-next-line",
        "property-named-return",
    ],
)
def test_division_after_a_postfix_operator_or_call_does_not_start_a_regex(source: str) -> None:
    # Only the ``)`` of an if/for/while/with condition is followed by a regex.
    assert blanked(source) == spaced(source, "// `sessionId`")


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "const n = <a href='/x'>https://x</a>; const k = 'agentId'",
        "const n = <><b>Don't</b> a /* b</>; const k = 'agentId'",
        "const n = <A.B x={`y`} />; const k = 'agentId'",
    ],
    ids=["url-text", "fragment-apostrophe-and-block-opener", "self-closing"],
)
def test_jsx_text_is_prose_and_the_code_after_it_is_kept(source: str) -> None:
    assert blanked(source, jsx=True) == source


@pytest.mark.unit
def test_comments_in_jsx_expressions_and_after_elements_are_blanked() -> None:
    source = "const n = <p>Don't {/* `agentId` */}</p>; // `sessionId`"
    expected = spaced(spaced(source, "/* `agentId` */"), "// `sessionId`")
    assert blanked(source, jsx=True) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "const f = <T,>(x: T) => x // `sessionId`",
        "const f = <T extends U>(x: T) => x // `sessionId`",
        "const f = <T extends\nunknown>(x: T) => x // `sessionId`",
        "const f = <T = unknown>(x: T) => x // `sessionId`",
        "const f = <T=unknown>(x: T) => x // `sessionId`",
        "const f = <const T,>(x: T) => x // `sessionId`",
        "const f = <const T extends U>(x: T) => x // `sessionId`",
    ],
    ids=[
        "trailing-comma",
        "extends",
        "extends-then-newline",
        "default",
        "default-unspaced",
        "const-trailing-comma",
        "const-extends",
    ],
)
def test_a_generic_in_tsx_is_not_jsx(source: str) -> None:
    assert blanked(source, jsx=True) == spaced(source, "// `sessionId`")


@pytest.mark.unit
@pytest.mark.parametrize("pattern", ["/[//]/", "/[/*]/"])
@pytest.mark.parametrize(
    "prefix",
    ["if (ok) {} ", "if (ok) {}\n", "function f() {}\n", "class C {}\n", "do {} while (ok)\n"],
    ids=["if-block", "if-block-newline", "function", "class", "do-while"],
)
def test_a_regex_after_a_block_is_code(prefix: str, pattern: str) -> None:
    # Read as division, the regex's ``//`` or ``/*`` would blank the code after it.
    source = f"{prefix}{pattern}.test(x); const k = 'agentId'\nconst j = 'sessionId'"
    assert blanked(source) == source


@pytest.mark.unit
@pytest.mark.parametrize("pattern", ["/[//]/", "/[/*]/"])
@pytest.mark.parametrize(
    "prefix",
    [
        "label: {} ",
        "outer: for (;;) {} ",
        "switch (x) { case 1: {} ",
        "switch (x) { case a ? 1 : 2: {} ",
        "switch (x) { default: {} ",
        "export default function () {}\n",
        "export default class {}\n",
    ],
    ids=[
        "label",
        "labelled-loop",
        "case",
        "case-with-ternary",
        "default",
        "export-default-function",
        "export-default-class",
    ],
)
def test_a_regex_after_a_statement_block_is_code(prefix: str, pattern: str) -> None:
    # A ``{`` after a label or case colon is a block, not an object (#2016 review).
    source = f"{prefix}{pattern}.test(x); const k = 'agentId'\nconst j = 'sessionId'"
    assert blanked(source) == source


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "const x = function() {} / 2; // `sessionId`",
        "const x = async function() {} / 2; // `sessionId`",
        "const x = class {} / 2; // `sessionId`",
        "const x = f(class extends B {}) / 2; // `sessionId`",
        "const x = function g(a = function() {}) {} / 2; // `sessionId`",
        "const r = a ? {} : {} / 2; // `sessionId`",
        "const r = {default: {}} / 2; // `sessionId`",
        "export default ok ? {} : {} / 2; // `sessionId`",
        "function f(): void;\nconst r = {} / 2; // `sessionId`",
    ],
    ids=[
        "function-expression",
        "async-function-expression",
        "class-expression",
        "class-expression-argument",
        "nested-function-expressions",
        "ternary-object",
        "default-property-object",
        "ternary-after-default",
        "object-after-overload",
    ],
)
def test_division_after_an_expression_body_does_not_start_a_regex(source: str) -> None:
    assert blanked(source) == spaced(source, "// `sessionId`")


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "const r = {a: 1} / 2 // `sessionId`",
        "const r = f({}) / 2 // `sessionId`",
        "const r = `${x}` / 2 // `sessionId`",
    ],
    ids=["object-literal", "object-argument", "template-expression"],
)
def test_division_after_an_object_does_not_start_a_regex(source: str) -> None:
    assert blanked(source) == spaced(source, "// `sessionId`")


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "const x = n! / 2; // `sessionId`",
        "const x = a.b!.c / 2; // `sessionId`",
        "const x = f(y)! / 2; // `sessionId`",
    ],
    ids=["identifier", "member", "call"],
)
def test_division_after_a_non_null_assertion_does_not_start_a_regex(source: str) -> None:
    assert blanked(source) == spaced(source, "// `sessionId`")


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "const t = !/[//]/.test(x); const k = 'agentId'",
        "const t = a !== /[//]/; const k = 'agentId'",
        "const t = a != /[//]/; const k = 'agentId'",
    ],
    ids=["logical-not", "strict-inequality", "inequality"],
)
def test_a_regex_after_negation_or_inequality_is_code(source: str) -> None:
    assert blanked(source) == source


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "const f = <T /* note */,>(x: T) => x // `sessionId`",
        "const f = <T // note\n,>(x: T) => x // `sessionId`",
        "const f = <T /* note */ = unknown>(x: T) => x // `sessionId`",
        "const f = <T extends/* note */unknown>(x: T) => x // `sessionId`",
    ],
    ids=[
        "block-comment-before-comma",
        "line-comment-before-comma",
        "before-default",
        "after-extends",
    ],
)
def test_a_generic_in_tsx_is_not_jsx_across_comments(source: str) -> None:
    comments = [c for c in ("/* note */", "// note") if c in source]
    expected = spaced(source, "// `sessionId`")
    for comment in comments:
        expected = spaced(expected, comment)
    assert blanked(source, jsx=True) == expected


@pytest.mark.unit
def test_a_tag_whose_name_starts_with_extends_is_jsx() -> None:
    source = "const n = <T extendsX>https://x</T>; const k = 'agentId'"
    assert blanked(source, jsx=True) == source


@pytest.mark.unit
def test_angle_brackets_in_ts_are_not_jsx() -> None:
    # In a ``.ts`` file ``<a>`` is a type assertion, so ``//`` after it is a comment.
    source = "const n = <a>https://x // `sessionId`"
    assert blanked(source) == spaced(source, "//x // `sessionId`")


@pytest.mark.unit
def test_a_tag_named_const_is_jsx() -> None:
    source = "const n = <const>https://x</const>; const k = 'agentId'"
    assert blanked(source, jsx=True) == source
