"""The shape printer must not have the failure it exists to prevent.

This script was written after four wrong claims in one day, all the same
mistake: reading a field off a response that does not carry it, getting None,
and reporting the silence as a finding.

A codex review then found the script itself did exactly that. `describe()`
inspected only element [0] of a list, so a field present on later elements was
silently absent from the output and the command still exited 0 -- a partial
listing that reads as complete. `find_value()` searched values but never keys
while reporting that a needle "does not appear anywhere", and a field NAME is
the thing most often searched for.

The exit codes are load-bearing for the same reason: the failure being guarded
is silence, so 0/1/2 have to mean found / absent / could-not-look.
"""

from __future__ import annotations

import pytest
from scripts.api_shape import describe, find_value

pytestmark = pytest.mark.unit


class TestEveryElementIsInspected:
    def test_a_key_only_on_a_later_element_is_still_shown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        describe({"rows": [{"first_only": 1}, {"later_only": 2}]})
        out = capsys.readouterr().out
        assert "later_only" in out

    def test_a_non_universal_key_is_marked_as_such(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The count is the point. Without it the output still reads as
        "these are the fields", which is the claim that was false."""
        describe({"rows": [{"a": 1}, {"a": 2}, {"rare": 3}]})
        out = capsys.readouterr().out
        assert "[in 1/3]" in out

    def test_a_universal_key_is_not_annotated(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Annotating every key would make the signal worthless."""
        describe({"rows": [{"a": 1}, {"a": 2}]})
        out = capsys.readouterr().out
        assert "a: int" in out
        assert "[in " not in out

    def test_a_list_of_scalars_reports_the_element_type(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The first version asserted only that output was non-empty, which
        `describe()` satisfies before the list walker runs at all -- so it
        passed even with the walker gutted."""
        describe({"rows": [1, 2, 3]})
        assert "int" in capsys.readouterr().out

    def test_a_field_nested_inside_a_later_element_is_shown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The regression that made the first fix WORSE than what it replaced:
        merging immediate keys without recursing hid every nested field,
        including ones the old element-[0] version did print."""
        describe({"rows": [{"meta": {"visible": 1}}, {"meta": {"hidden": 2}}]})
        out = capsys.readouterr().out
        assert "visible" in out
        assert "hidden" in out

    def test_a_field_in_a_later_inner_list_is_shown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        describe({"rows": [[{"visible": 1}], [{"hidden_later": 2}]]})
        assert "hidden_later" in capsys.readouterr().out

    def test_a_list_sibling_of_a_dict_is_not_skipped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Handling dicts and returning early hid everything inside sibling
        list elements."""
        describe({"rows": [{"visible": 1}, [{"hidden_mixed": 2}]]})
        assert "hidden_mixed" in capsys.readouterr().out

    def test_the_denominator_counts_non_dict_elements(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`[in n/N]` claims "not on all elements", so N must be the list
        length, not the number of dicts in it."""
        describe({"rows": [{"a": 1}, 7]})
        assert "[in 1/2]" in capsys.readouterr().out


class TestFindLooksWhereItSaysItLooks:
    def test_a_needle_used_only_as_a_key_is_found(self) -> None:
        assert find_value({"later_only": 2}, "later_only")

    def test_a_needle_in_a_value_is_found(self) -> None:
        assert find_value({"k": "target"}, "target")

    def test_a_needle_on_a_later_list_element_is_found(self) -> None:
        assert find_value({"rows": [{"a": 1}, {"b": "target"}]}, "target")

    def test_a_genuinely_absent_needle_reports_absent(self) -> None:
        """The negative control. Without it, a find() that returned everything
        would satisfy every test above."""
        assert find_value({"k": "value"}, "nothing-like-this") == []


class TestSubstringIsNotPresence:
    def test_substring_matches_by_default(self) -> None:
        assert find_value({"k": "foobar"}, "foo")

    def test_exact_refuses_a_partial_match(self) -> None:
        """`foo` is not present just because `foobar` is -- and the exit code
        is used as a presence check."""
        assert find_value({"k": "foobar"}, "foo", exact=True) == []

    def test_exact_still_matches_a_whole_value(self) -> None:
        assert find_value({"k": "foobar"}, "foobar", exact=True)


class TestTheCommandAnswersTheQuestionItWasAsked:
    """`main()` had no coverage at all, so removing the whole `--at` fix
    survived every test in the first version of this file."""

    def _run(self, monkeypatch: pytest.MonkeyPatch, payload: object, *argv: str) -> int:
        import scripts.api_shape as mod

        monkeypatch.setattr(mod, "_fetch", lambda _url, _timeout: payload)
        monkeypatch.setattr("sys.argv", ["api_shape.py", "http://x", *argv])
        return mod.main()

    def test_at_scopes_the_search(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The needle exists, but NOT under the requested subtree. Exiting 0
        here would answer a question the caller did not ask."""
        payload = {"wanted": {"a": 1}, "elsewhere": {"needle": 2}}
        code = self._run(monkeypatch, payload, "--at", "wanted", "--find", "needle")
        capsys.readouterr()
        assert code == 1

    def test_at_finds_it_when_it_is_in_scope(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {"wanted": {"needle": 1}}
        code = self._run(monkeypatch, payload, "--at", "wanted", "--find", "needle")
        capsys.readouterr()
        assert code == 0

    def test_a_missing_at_key_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = self._run(monkeypatch, {"a": 1}, "--at", "nope")
        capsys.readouterr()
        assert code == 1

    def test_an_empty_exact_needle_is_still_a_question(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Truthiness treated `--find-exact ""` as "not supplied", printed the
        shape, and exited 0 without searching."""
        code = self._run(monkeypatch, {"k": ""}, "--find-exact", "")
        out = capsys.readouterr().out
        assert code == 0
        assert "appears at" in out

    def test_an_empty_exact_needle_that_is_absent_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = self._run(monkeypatch, {"k": "nonempty"}, "--find-exact", "")
        capsys.readouterr()
        assert code == 1

    def test_both_find_flags_together_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two conflicting questions used to silently answer only one."""
        with pytest.raises(SystemExit):
            self._run(monkeypatch, {"k": 1}, "--find", "a", "--find-exact", "b")


class TestJsonSpellingsAreSearchable:
    """The response was JSON, so a caller types `null`, not `None`.

    Searching only Python's `str()` spelling reported a value that IS present
    as absent -- the exact false-absence this script exists to prevent,
    reproduced inside it.
    """

    @pytest.mark.parametrize(
        ("needle", "value"),
        [("null", None), ("true", True), ("false", False)],
    )
    def test_the_json_spelling_is_found(self, needle: str, value: object) -> None:
        assert find_value({"k": value}, needle, exact=True)

    @pytest.mark.parametrize(
        ("needle", "value"),
        [("None", None), ("True", True), ("False", False)],
    )
    def test_the_python_spelling_still_works(self, needle: str, value: object) -> None:
        """The caller may have copied the needle from this tool's own output."""
        assert find_value({"k": value}, needle, exact=True)

    def test_a_genuinely_absent_scalar_still_reports_absent(self) -> None:
        assert find_value({"k": None}, "nope", exact=True) == []


class TestNoVariantIsSuppressed:
    """A position is not one type, and choosing among observed values is how
    this file lost information twice.

    First by describing only element [0]; then by merging immediate keys and
    dropping nested ones; then by reporting the object variant of a key and
    silently dropping the null one. Each fix was a different CHOICE where the
    answer was always the union.
    """

    def test_a_key_that_is_sometimes_null_reports_both(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        describe({"rows": [{"meta": None}, {"meta": {"visible": 1}}]})
        out = capsys.readouterr().out
        assert "null" in out
        assert "object" in out
        assert "visible" in out

    def test_a_bare_scalar_beside_objects_is_reported(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The old element-[0] version printed this; the first merge did not.

        The value must be one ONLY the scalar can produce. The first version
        of this test asserted `"int" in out`, which the key line `field: int`
        satisfies on its own -- so it passed with scalars fully suppressed.
        """
        describe({"rows": [99991, {"field": 2}]})
        out = capsys.readouterr().out
        assert "field" in out
        assert "99991" in out


class TestCouldNotLookIsNeverSpelledLikeAbsent:
    """Exit 1 means "looked and it is absent". Anything that did not look
    must be 2, or a network blip reads as a real answer."""

    def _run(self, monkeypatch: pytest.MonkeyPatch, raises: BaseException, *argv: str) -> int:
        import scripts.api_shape as mod

        def _boom(_url: str, _timeout: float) -> object:
            raise raises

        monkeypatch.setattr(mod, "_fetch", _boom)
        monkeypatch.setattr("sys.argv", ["api_shape.py", "http://x", *argv])
        return mod.main()

    def test_a_transport_failure_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without this, changing the transport `return 2` to `return 0`
        survived the entire suite."""
        import urllib.error

        code = self._run(monkeypatch, urllib.error.URLError("down"), "--find", "x")
        capsys.readouterr()
        assert code == 2

    def test_a_timeout_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = self._run(monkeypatch, TimeoutError("slow"))
        capsys.readouterr()
        assert code == 2

    def test_a_response_too_deep_to_walk_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import scripts.api_shape as mod

        payload: object = {"target": 1}
        for _ in range(2000):
            payload = {"k": [payload]}
        monkeypatch.setattr(mod, "_fetch", lambda _u, _t: payload)
        monkeypatch.setattr("sys.argv", ["api_shape.py", "http://x", "--find", "target"])
        code = mod.main()
        capsys.readouterr()
        assert code == 2
