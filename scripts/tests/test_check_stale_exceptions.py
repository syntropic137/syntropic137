"""Unit tests for the stale-exception gate.

The gate exists because the fitness tool reports stale waivers and then exits 0,
so three of them accumulated unnoticed (#1084). A gate against silent passes
must not have one of its own: these drive `main()` - the actual verdict - and
the malformed-input cases assert a NON-ZERO exit, because a report the gate
cannot read must never be indistinguishable from a report with nothing in it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.check_stale_exceptions import main, stale_from_report

pytestmark = pytest.mark.unit


def _report(tmp_path: Path, payload: object, name: str = "report.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


def _stale(entity: str) -> dict[str, str]:
    return {"entity": entity, "rule_id": "max-cognitive", "reason": "now_passing"}


class TestVerdict:
    def test_no_stale_exceptions_passes(self, tmp_path: Path) -> None:
        assert main(["prog", _report(tmp_path, {"stale_exceptions": []})]) == 0

    def test_one_stale_exception_fails(self, tmp_path: Path) -> None:
        payload = {"stale_exceptions": [_stale("python:a.b::c")]}
        assert main(["prog", _report(tmp_path, payload)]) == 1

    def test_every_stale_entity_is_named(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Naming only the first would leave the others to be found one CI round at a time."""
        entities = ["python:a::one", "python:b::two", "tsx:c/d::Three"]
        payload = {"stale_exceptions": [_stale(e) for e in entities]}

        assert main(["prog", _report(tmp_path, payload)]) == 1

        err = capsys.readouterr().err
        for entity in entities:
            assert entity in err, f"{entity} was not named in the failure output"


class TestFailsClosed:
    """A report the gate cannot read must not be reported as a clean one."""

    def test_missing_file(self, tmp_path: Path) -> None:
        assert main(["prog", str(tmp_path / "absent.json")]) == 2

    def test_not_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json at all")
        assert main(["prog", str(path)]) == 2

    def test_key_absent_is_not_read_as_zero(self, tmp_path: Path) -> None:
        """The exact silent-pass this gate exists to prevent, aimed at itself."""
        assert main(["prog", _report(tmp_path, {"summary": {"failed": 0}})]) == 2

    def test_wrong_type(self, tmp_path: Path) -> None:
        assert main(["prog", _report(tmp_path, {"stale_exceptions": 3})]) == 2

    def test_entry_is_not_an_object(self, tmp_path: Path) -> None:
        assert main(["prog", _report(tmp_path, {"stale_exceptions": ["a string"]})]) == 2

    def test_report_is_a_list(self, tmp_path: Path) -> None:
        assert main(["prog", _report(tmp_path, [])]) == 2

    def test_wrong_argument_count(self) -> None:
        assert main(["prog"]) == 2


class TestExtraction:
    def test_missing_fields_do_not_raise(self) -> None:
        """A future tool version may drop a field; that is not this gate's failure."""
        parsed = stale_from_report({"stale_exceptions": [{"entity": "python:a::b"}]})
        assert parsed == [{"entity": "python:a::b", "rule_id": "<unknown>", "reason": "<unknown>"}]

    def test_preserves_order_and_count(self) -> None:
        payload = {"stale_exceptions": [_stale("one"), _stale("two"), _stale("one")]}
        assert [e["entity"] for e in stale_from_report(payload)] == ["one", "two", "one"]
