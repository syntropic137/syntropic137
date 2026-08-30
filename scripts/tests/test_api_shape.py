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

    def test_a_list_of_scalars_still_reports_something(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        describe({"rows": [1, 2, 3]})
        assert capsys.readouterr().out.strip() != ""


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
