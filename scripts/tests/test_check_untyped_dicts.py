"""The untyped-dict ratchet must measure typing, not spelling.

It used to measure spelling. The gate was one ``re.findall`` for the literal
string ``dict[str, Any]``, which meant three separate ways to be wrong:

1. Renaming the annotation satisfied it. ``Mapping[str, object]`` erases the
   value type exactly as much as ``dict[str, object]`` does, and scored zero.
   On PR #1186 a package crossed its ceiling by one and was brought back under
   by exactly that rename. The change was defensible on its own merits - which
   is the problem, because the honest edit and the evasion were the same edit
   and the gate could not tell them apart.
2. It counted prose. A ``dict[str, Any]`` inside a docstring or a comment spent
   budget. Comments explaining *why* a dict was untyped were charged for the
   explanation.
3. It could be dodged by formatting. The same annotation wrapped across two
   lines, or written ``Dict[str, Any]``, was invisible.

These tests pin all three. Each one fails against the regex it replaced; that
was verified by reverting the implementation and watching them go red, not by
assuming it.

See #1188.
"""

from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_untyped_dicts import (
    Occurrence,
    contains_dict_shaped_state,
    find_dict_shaped_state,
    main,
    scan_package,
)


def count(source: str) -> int:
    """Occurrences in a dedented snippet, so tests can be written indented."""
    return len(find_dict_shaped_state(textwrap.dedent(source)))


@pytest.mark.unit
class TestEverySpellingCountsOnce:
    """(a) One shape, however it is written.

    Every case here erases the value type of a str-keyed mapping. The regex saw
    only the first one.
    """

    @pytest.mark.parametrize(
        ("label", "source"),
        [
            ("builtin dict", "x: dict[str, Any]\n"),
            ("read-only Mapping", "x: Mapping[str, object]\n"),
            ("MutableMapping", "x: MutableMapping[str, Any]\n"),
            ("typing.Dict, the pre-3.9 spelling", "x: Dict[str, Any]\n"),
            ("dotted typing.Dict", "x: typing.Dict[str, Any]\n"),
            ("dotted collections.abc.Mapping", "x: collections.abc.Mapping[str, object]\n"),
            ("quoted value type", 'x: dict[str, "Any"]\n'),
            ("wholly quoted forward reference", 'x: "dict[str, Any]"\n'),
            ("split across two lines", "x: dict[\n    str, Any\n]\n"),
            ("alias definition", "D = dict[str, Any]\n"),
            ("parameter annotation", "def f(a: Mapping[str, object]) -> None: ...\n"),
            ("return annotation", "def f() -> dict[str, Any]: ...\n"),
            ("quoted cast target", 'y = cast("dict[str, Any]", raw)\n'),
            ("unquoted cast target", "y = cast(dict[str, Any], raw)\n"),
            ("nested in a container", "x: list[dict[str, Any]]\n"),
            ("behind an optional", "x: dict[str, Any] | None\n"),
        ],
    )
    def test_counted_exactly_once(self, label: str, source: str) -> None:
        assert count(source) == 1, f"{label} should count once: {source!r}"

    def test_only_the_erased_layer_of_a_nested_mapping_counts(self) -> None:
        """``dict[str, dict[str, Any]]`` is one erasure, not two.

        The outer mapping's value type is a ``dict`` - that is a constraint, so
        the outer is not itself untyped. Only the inner ``Any`` erases anything.
        """
        assert count("x: dict[str, dict[str, Any]]\n") == 1

    def test_siblings_each_count(self) -> None:
        """Two independent erasures in one annotation are two occurrences."""
        assert count("x: tuple[dict[str, Any], Mapping[str, object]]\n") == 2


@pytest.mark.unit
class TestProseIsNotCode:
    """(b) A mention of a type is not a use of one.

    This is the half of the old gate that cost people budget for writing
    documentation.
    """

    def test_a_docstring_mention_counts_zero(self) -> None:
        source = '''
        def f(rows):
            """Normalise rows.

            Returns a dict[str, Any] because the payload is external.
            """
            return rows
        '''
        assert count(source) == 0

    def test_a_comment_mention_counts_zero(self) -> None:
        source = """
        # Any: dict[str, Any] used for JSON from an external CLI (boundary).
        def f(rows):
            return rows
        """
        assert count(source) == 0

    def test_a_type_ignore_comment_counts_zero(self) -> None:
        source = """
        data: dict[str, int] = payload.model_dump()  # type: ignore[assignment]  # -> dict[str, Any]
        """
        assert count(source) == 0

    def test_a_string_literal_counts_zero(self) -> None:
        """A fixture or log message that happens to contain the text."""
        source = """
        MESSAGE = "expected dict[str, Any] at the boundary"
        FIXTURE = '''
        x: dict[str, Any]
        '''
        """
        assert count(source) == 0

    def test_the_module_docstring_of_the_gate_itself_counts_zero(self) -> None:
        """The regex counted its own explanation. This one must not."""
        gate = Path(__file__).resolve().parents[1] / "check_untyped_dicts.py"
        occurrences = find_dict_shaped_state(gate.read_text())
        assert occurrences == [], f"gate counts itself: {occurrences}"


@pytest.mark.unit
class TestTypedDictsAreNotCounted:
    """(c) The gate measures erasure, not the word ``dict``."""

    @pytest.mark.parametrize(
        "source",
        [
            "x: dict[str, int]\n",
            "x: dict[str, str]\n",
            "x: Mapping[str, RepositoryRef]\n",
            "x: dict[UUID, Any]\n",  # key is not str
            "x: dict\n",  # bare, unparameterised
            "x: list[Any]\n",  # not a mapping
            "x: Sequence[str]\n",
            "x: TypedDictSubclass\n",
            "value = some_dict['str', 'Any']\n",  # runtime subscript, not a type
        ],
    )
    def test_counts_zero(self, source: str) -> None:
        assert count(source) == 0, f"should not count: {source!r}"


@pytest.mark.unit
class TestAliases:
    """(d) An alias is debt in one place, not once per reference.

    Counting usages would make the number track how popular a type is rather
    than how much erasure exists, and would punish a codebase for centralising
    the thing it will eventually have to fix in one edit.
    """

    def test_the_definition_counts_and_its_usages_do_not(self) -> None:
        source = """
        D = dict[str, Any]

        def one(a: D) -> D: ...
        def two(b: D) -> None: ...
        def three() -> D: ...
        """
        assert count(source) == 1

    def test_the_occurrence_is_reported_at_the_definition(self) -> None:
        source = textwrap.dedent(
            """
            D = dict[str, Any]

            def one(a: D) -> D: ...
            """
        )
        (occurrence,) = find_dict_shaped_state(source)
        assert occurrence == Occurrence(line=2, text="dict[str, Any]")


@pytest.mark.unit
class TestUnparseableFilesAreLoud:
    """(e) A file that cannot be measured has an unknown count, not zero.

    A counter that skips what it cannot parse reports an improvement every time
    a file breaks - the one direction a ratchet must never move by accident.
    These assert on the gate's exit status, not on the parser, because the exit
    status is what CI reads.
    """

    def _package(self, tmp_path: Path, *, broken: bool) -> Path:
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "good.py").write_text("x: dict[str, Any]\n")
        if broken:
            (package / "broken.py").write_text("def f(:\n")
        return package

    def test_the_parser_refuses_to_guess(self) -> None:
        with pytest.raises(SyntaxError):
            find_dict_shaped_state("def f(:\n")

    def test_a_broken_file_is_named_in_the_scan(self, tmp_path: Path) -> None:
        scan = scan_package("pkg", self._package(tmp_path, broken=True), allowed=99, issue="#1188")
        assert [file.path.name for file in scan.unreadable] == ["broken.py"]

    def test_the_gate_fails_even_when_the_count_is_under_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The consumer's verdict, not the parser's.

        Budget is 99 against a count of 1, so nothing about the number can fail
        this run. Only the unmeasurable file can.
        """
        self._package(tmp_path, broken=True)
        (tmp_path / "fitness-exceptions.toml").write_text(
            '[untyped-dicts.pkg]\npath = "pkg"\nvalue = 99\nissue = "#1188"\n'
        )
        monkeypatch.chdir(tmp_path)
        assert main() == 1

    def test_the_same_package_passes_once_the_file_parses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure above is caused by the broken file and nothing else."""
        self._package(tmp_path, broken=False)
        (tmp_path / "fitness-exceptions.toml").write_text(
            '[untyped-dicts.pkg]\npath = "pkg"\nvalue = 99\nissue = "#1188"\n'
        )
        monkeypatch.chdir(tmp_path)
        assert main() == 0


@pytest.mark.unit
class TestPackageScanning:
    """What the ratchet counts across a tree."""

    def test_worktree_copies_are_not_counted_twice(self, tmp_path: Path) -> None:
        """``.claude/worktrees`` holds whole repo copies.

        ``check_test_markers`` shipped this exact false positive: it counted
        every agent worktree as more source.
        """
        package = tmp_path / "pkg"
        (package / ".claude" / "worktrees" / "copy").mkdir(parents=True)
        (package / "real.py").write_text("x: dict[str, Any]\n")
        (package / ".claude" / "worktrees" / "copy" / "real.py").write_text("x: dict[str, Any]\n")
        assert scan_package("pkg", package, allowed=0, issue="").count == 1

    def test_a_count_over_budget_fails_the_scan(self, tmp_path: Path) -> None:
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "a.py").write_text("x: Mapping[str, object]\n")
        assert scan_package("pkg", package, allowed=0, issue="").exceeded


@pytest.mark.unit
class TestTheNodeLevelEntry:
    """``contains_dict_shaped_state`` is what ADR-063's boundary gate consumes.

    That gate used to run its own regex over annotation source text and so
    shared the defect this change fixes: renaming a Protocol parameter from
    ``dict[str, Any]`` to ``Mapping[str, Any]`` silenced it without typing
    anything. It now asks this function, which is why these tests live here.
    """

    def _annotation(self, source: str) -> ast.expr:
        statement = ast.parse(textwrap.dedent(source)).body[0]
        assert isinstance(statement, ast.AnnAssign)
        return statement.annotation

    @pytest.mark.parametrize(
        "source",
        ["x: dict[str, Any]\n", "x: Mapping[str, object]\n", "x: list[dict[str, Any]]\n"],
    )
    def test_finds_erased_mappings_by_default(self, source: str) -> None:
        assert contains_dict_shaped_state(self._annotation(source))

    def test_a_typed_mapping_is_not_flagged(self) -> None:
        assert not contains_dict_shaped_state(self._annotation("x: Mapping[str, int]\n"))

    def test_str_values_are_opaque_only_when_the_caller_says_so(self) -> None:
        """ADR-063 counts ``dict[str, str]``; the ratchet does not.

        Same definition of what a mapping is, one axis of difference, declared
        by the caller rather than duplicated in a second regex.
        """
        annotation = self._annotation("x: dict[str, str]\n")
        assert not contains_dict_shaped_state(annotation)
        assert contains_dict_shaped_state(annotation, values=frozenset({"str", "Any", "object"}))

    def test_the_boundary_gate_can_no_longer_be_dodged_by_renaming(self) -> None:
        """The PR #1186 evasion, applied to a Protocol signature."""
        opaque = frozenset({"str", "Any", "object"})
        for spelling in ("dict[str, object]", "Mapping[str, object]", "Dict[str, Any]"):
            assert contains_dict_shaped_state(
                self._annotation(f"x: {spelling}\n"), values=opaque
            ), spelling


@pytest.mark.unit
class TestTypedDictIsDictShapedState:
    """(f) ``TypedDict`` is a dict that the ratchet used to be blind to.

    The reproduction is #1248's, which is PR #1246's. A change failed
    ``check-untyped-dicts`` with a ``dict[str, Any]``, replaced it with a
    ``TypedDict`` carrying the same string keys, and the gate went green.
    Independent review refused the head anyway::

        A TypedDict is still dictionary-shaped structured state and is consumed
        through json["permissions"]. Passing the AST ratchet does not satisfy
        that requirement; it only shows the ratchet does not count this
        spelling.

    Unlike the mapping shapes, a ``TypedDict`` counts regardless of its value
    types: ``contents: str`` constrains the value perfectly and still fails the
    rule, because the rule is about string-keyed access to structured state,
    not about erasure. So there is no "typed enough" ``TypedDict`` and no case
    below that should score zero.
    """

    def test_the_issue_reproduction_is_reported(self) -> None:
        """#1248 verbatim. Against the pre-fix gate this returns ``[]``."""
        source = """
        from typing import TypedDict

        class Permissions(TypedDict):
            contents: str
            pull_requests: str

        def read(p: Permissions) -> str:
            return p["contents"]
        """
        (occurrence,) = find_dict_shaped_state(textwrap.dedent(source))
        assert occurrence.text == "class Permissions(TypedDict)"

    @pytest.mark.parametrize(
        ("label", "source"),
        [
            ("bare base", "class P(TypedDict):\n    a: int\n"),
            ("dotted base", "class P(typing.TypedDict):\n    a: int\n"),
            (
                "typing_extensions, the runtime-features spelling",
                "class P(typing_extensions.TypedDict):\n    a: int\n",
            ),
            ("total=False", "class P(TypedDict, total=False):\n    a: int\n"),
            ("functional syntax", 'P = TypedDict("P", {"a": int})\n'),
            ("dotted functional syntax", 'P = typing.TypedDict("P", {"a": int})\n'),
        ],
    )
    def test_every_declaration_form_counts_once(self, label: str, source: str) -> None:
        assert count(source) == 1, f"{label} should count once: {source!r}"

    def test_the_declaration_counts_and_its_usages_do_not(self) -> None:
        """Same rule as an alias: the fix happens once, at the declaration.

        Replacing the declaration with a dataclass repairs every reference to
        it, so counting the references would measure popularity rather than
        debt.
        """
        source = """
        class P(TypedDict):
            a: int

        def one(p: P) -> P: ...
        def two(p: P) -> None: ...
        """
        assert count(source) == 1

    def test_a_docstring_about_typeddict_counts_zero(self) -> None:
        """Prose is prose for the new shape too, not only for ``dict``."""
        source = '''
        def f(rows):
            """Normalise rows.

            The upstream payload is a TypedDict, so class P(TypedDict) applies.
            """
            return rows
        '''
        assert count(source) == 0

    def test_a_plain_class_is_not_a_typed_dict(self) -> None:
        source = """
        @dataclass(frozen=True)
        class P:
            a: int
        """
        assert count(source) == 0


@pytest.mark.unit
class TestImportAliasesDoNotHide:
    """(g) A shape renamed on the way in is the same shape.

    ``_trailing_name`` answers what a type expression is *called*, which is why
    the dotted spellings resolve. It cannot see a rename that happened in the
    import statement: ``from typing import Dict as D`` makes ``D[str, Any]``
    the same annotation under a name that appears in no constant here. That is
    the same seam #1188 closed for formatting, left open for imports - and the
    cheapest possible dodge once ``TypedDict`` is counted.
    """

    @pytest.mark.parametrize(
        ("label", "source"),
        [
            ("aliased typing.Dict", "from typing import Dict as D\nx: D[str, Any]\n"),
            (
                "aliased collections.abc.Mapping",
                "from collections.abc import Mapping as M\nx: M[str, object]\n",
            ),
            (
                "aliased MutableMapping",
                "from collections.abc import MutableMapping as MM\nx: MM[str, Any]\n",
            ),
            ("aliased builtin dict", "from builtins import dict as d\nx: d[str, Any]\n"),
            ("aliased value type", "from typing import Any as A\nx: dict[str, A]\n"),
            (
                "aliased TypedDict base",
                "from typing import TypedDict as TD\nclass P(TD):\n    a: int\n",
            ),
            (
                "aliased TypedDict, functional",
                'from typing import TypedDict as TD\nP = TD("P", {"a": int})\n',
            ),
            (
                "aliased inside a forward reference",
                'from typing import Dict as D\nx: "D[str, Any]"\n',
            ),
        ],
    )
    def test_the_alias_is_resolved(self, label: str, source: str) -> None:
        assert count(source) == 1, f"{label} should count once: {source!r}"

    def test_an_unrelated_alias_is_not_invented(self) -> None:
        """Resolution must not turn every short name into a mapping."""
        source = """
        from decimal import Decimal as D
        x: D
        y: dict[str, D]
        """
        assert count(source) == 0

    def test_a_module_alias_still_resolves_by_attribute(self) -> None:
        """``import typing as t`` already worked; it must keep working."""
        assert count("import typing as t\nx: t.Dict[str, Any]\n") == 1


@pytest.mark.unit
class TestSimpleNamespaceIsErasureWithDotSyntax:
    """(h) ``SimpleNamespace`` is ``dict[str, Any]`` wearing attribute access.

    It declares no fields at all, so a type checker knows less about it than
    about the ``dict[str, Any]`` the gate already counts, and
    ``SimpleNamespace(**payload)`` is a one-line way to turn a counted
    annotation into an uncounted one. Every place the name is written is a
    place the erasure has to be repaired, so each is counted - there is no
    single declaration site to attribute it to the way there is for an alias or
    a ``TypedDict``.
    """

    @pytest.mark.parametrize(
        ("label", "source"),
        [
            ("construction", "obj = SimpleNamespace(a=1, b=2)\n"),
            ("dotted construction", "obj = types.SimpleNamespace(a=1)\n"),
            ("parameter annotation", "def f(o: SimpleNamespace) -> None: ...\n"),
            ("return annotation", "def f() -> SimpleNamespace: ...\n"),
            ("aliased import", "from types import SimpleNamespace as NS\nobj = NS(a=1)\n"),
        ],
    )
    def test_counted_once(self, label: str, source: str) -> None:
        assert count(source) == 1, f"{label} should count once: {source!r}"

    def test_the_import_alone_is_not_a_use(self) -> None:
        assert count("from types import SimpleNamespace\n") == 0


@pytest.mark.unit
class TestNamedTupleIsDeliberatelyNotCounted:
    """(i) The judgement call #1248 asked for, pinned so it stays a decision.

    A ``NamedTuple`` names and types every field and is read by attribute, so
    it satisfies both halves of the rule this gate enforces: it is not a
    dictionary, and there is no string-keyed lookup to replace. ``EventInfo``
    in ``syn-domain`` is the shape the rule wants people to move *toward*;
    charging budget for it would push them back to the thing it replaced.

    Its real weaknesses - positional unpacking, index access, comparing equal
    to a bare tuple - are a different concern from the one measured here, and
    counting them would quietly widen the gate from "not dict-shaped" to "must
    be a Pydantic model", which is not the rule AGENTS.md states. If that
    becomes the rule, it should arrive as its own gate with its own budgets,
    not smuggled in under this one.
    """

    @pytest.mark.parametrize(
        "source",
        [
            "class P(NamedTuple):\n    a: int\n",
            "class P(typing.NamedTuple):\n    a: int\n",
            'P = NamedTuple("P", [("a", int)])\n',
        ],
    )
    def test_counts_zero(self, source: str) -> None:
        assert count(source) == 0, f"should not count: {source!r}"

    def test_but_an_erased_field_inside_one_still_counts(self) -> None:
        """Excluding the container does not excuse what it holds."""
        assert count("class P(NamedTuple):\n    a: dict[str, Any]\n") == 1


@pytest.mark.unit
class TestAssignmentRenamesDoNotHide:
    """(j) A rename is a rename, whichever statement performs it.

    ``TestImportAliasesDoNotHide`` closed the rename that happens on the import
    line. It left open the cheaper one: ``D = dict`` needs no import at all, is
    one line, and every constructor this gate knows about could be spelled
    through it without spending a byte of budget. Closing a spelling and
    leaving that open recreates #1188 one level up - a number that stays still
    for a shape nobody listed - which is the defect this gate exists to stop.

    A rename writes no type. ``D = dict`` erases nothing on its own; the
    erasure arrives later at ``D[str, Any]`` and is counted there, exactly as
    it is for ``from typing import Dict as D``. That is what separates it from
    ``D = dict[str, Any]`` in ``TestAliases``, which is a complete type
    expression and is counted where it is written.
    """

    @pytest.mark.parametrize(
        ("label", "source"),
        [
            ("renamed builtin dict", "D = dict\nx: D[str, Any]\n"),
            ("renamed typing.Dict", "from typing import Dict\nD = Dict\nx: D[str, Any]\n"),
            (
                "renamed Mapping",
                "from collections.abc import Mapping\nM = Mapping\nx: M[str, object]\n",
            ),
            (
                "renamed MutableMapping",
                "from collections.abc import MutableMapping\nMM = MutableMapping\nx: MM[str, Any]\n",
            ),
            ("renamed by attribute", "import typing\nD = typing.Dict\nx: D[str, Any]\n"),
            (
                "renamed TypedDict base",
                "from typing import TypedDict\nTD = TypedDict\nclass P(TD):\n    a: int\n",
            ),
            (
                "renamed TypedDict, functional",
                'from typing import TypedDict\nTD = TypedDict\nP = TD("P", {"a": int})\n',
            ),
            ("renamed value type", "from typing import Any\nA = Any\nx: dict[str, A]\n"),
            ("renamed key type", "S = str\nx: dict[S, Any]\n"),
            ("renamed inside a forward reference", 'D = dict\nx: "D[str, Any]"\n'),
            (
                "renamed under an annotation",
                "from typing import TypeAlias\nD: TypeAlias = dict\nx: D[str, Any]\n",
            ),
            ("renamed by a type statement", "type D = dict\nx: D[str, Any]\n"),
            ("renamed twice", "D = dict\nE = D\nx: E[str, Any]\n"),
            (
                "renamed from an import rename",
                "from typing import Dict as D\nE = D\nx: E[str, Any]\n",
            ),
        ],
    )
    def test_the_rename_is_resolved(self, label: str, source: str) -> None:
        assert count(source) == 1, f"{label} should count once: {source!r}"

    def test_the_rename_itself_writes_no_type(self) -> None:
        """``D = dict`` is not an erased mapping until someone parameterises it."""
        assert count("D = dict\nE = Mapping\n") == 0

    def test_an_unrelated_rename_is_not_invented(self) -> None:
        """Resolution must not turn every assigned name into a mapping."""
        source = """
        from decimal import Decimal
        D = Decimal
        x: D
        y: dict[str, D]
        """
        assert count(source) == 0

    def test_a_rename_cycle_terminates(self) -> None:
        """``a = b`` and ``b = a`` name nothing and must not hang the walk."""
        assert count("a = b\nb = a\nx: a[str, Any]\n") == 0

    def test_the_erased_use_is_reported_at_its_own_line(self) -> None:
        """The budget is spent where the type is written, not where it is named."""
        source = textwrap.dedent(
            """
            D = dict

            def one(a: D[str, Any]) -> None: ...
            """
        )
        (occurrence,) = find_dict_shaped_state(source)
        assert occurrence == Occurrence(line=4, text="D[str, Any]")

    def test_every_use_of_a_renamed_namespace_counts(self) -> None:
        """``SimpleNamespace`` is counted per use, so a rename must not pool them.

        Two constructions behind a renamed constructor are two ad-hoc shapes,
        the same as two written out in full. Before renames were resolved this
        source counted one - the name on the rename line - however many objects
        it went on to build.

        Three and not two: the rename line writes ``SimpleNamespace`` itself,
        and the rule for this shape is that every written mention is a place
        the erasure has to be repaired. Deleting the rename is one of the ways
        to repair it, so it is a fair place to charge for.
        """
        source = """
        from types import SimpleNamespace
        NS = SimpleNamespace
        first = NS(a=1)
        second = NS(b=2)
        """
        assert count(source) == 3

    def test_a_name_being_bound_is_not_a_use(self) -> None:
        """Resolving the rename must not make the rename line count twice."""
        assert count("from types import SimpleNamespace\nNS = SimpleNamespace\n") == 1
