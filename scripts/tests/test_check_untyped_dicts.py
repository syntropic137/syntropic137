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
    contains_untyped_mapping,
    find_untyped_mappings,
    main,
    scan_package,
)


def count(source: str) -> int:
    """Occurrences in a dedented snippet, so tests can be written indented."""
    return len(find_untyped_mappings(textwrap.dedent(source)))


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
        occurrences = find_untyped_mappings(gate.read_text())
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
        (occurrence,) = find_untyped_mappings(source)
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
            find_untyped_mappings("def f(:\n")

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
    """``contains_untyped_mapping`` is what ADR-063's boundary gate consumes.

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
        assert contains_untyped_mapping(self._annotation(source))

    def test_a_typed_mapping_is_not_flagged(self) -> None:
        assert not contains_untyped_mapping(self._annotation("x: Mapping[str, int]\n"))

    def test_str_values_are_opaque_only_when_the_caller_says_so(self) -> None:
        """ADR-063 counts ``dict[str, str]``; the ratchet does not.

        Same definition of what a mapping is, one axis of difference, declared
        by the caller rather than duplicated in a second regex.
        """
        annotation = self._annotation("x: dict[str, str]\n")
        assert not contains_untyped_mapping(annotation)
        assert contains_untyped_mapping(annotation, values=frozenset({"str", "Any", "object"}))

    def test_the_boundary_gate_can_no_longer_be_dodged_by_renaming(self) -> None:
        """The PR #1186 evasion, applied to a Protocol signature."""
        opaque = frozenset({"str", "Any", "object"})
        for spelling in ("dict[str, object]", "Mapping[str, object]", "Dict[str, Any]"):
            assert contains_untyped_mapping(self._annotation(f"x: {spelling}\n"), values=opaque), (
                spelling
            )
