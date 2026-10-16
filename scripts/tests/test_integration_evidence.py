"""Tests for the integration-evidence runner.

The runner's product is `evidence.json`, so each case drives a real pytest
JUnit report shape through `build_report` and parses the result with PR 1's
`EvidenceReport` contract: a report the platform would refuse is a bug here.
The cases that matter are the ones that turn a non-result into a pass: a
requested test that was skipped, xfailed, xpassed or never collected, a red
suite, a run that stopped with nothing on record.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from scripts import integration_evidence as ie
from scripts.integration_evidence import Inputs, SuiteRun, build_report, inputs_from_env, mangle

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceReport,
    EvidenceVerdict,
    TestOutcome,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

SHA = "b" * 40
WANTED = "tests/integration/test_store.py::TestStore::test_append[pg]"
OTHER = "tests/integration/test_other.py::test_unrelated"


STORE = "tests/integration/test_store.py"
OTHER_FILE = "tests/integration/test_other.py"


def _case(file: str, classname: str, name: str, body: str = "") -> str:
    return (
        f'<testcase file="{file}" classname="{classname}" name="{name}" time="0.1">'
        f"{body}</testcase>"
    )


PASS_WANTED = _case(STORE, "tests.integration.test_store.TestStore", "test_append[pg]")
PASS_OTHER = _case(OTHER_FILE, "tests.integration.test_other", "test_unrelated")
SKIP = '<skipped type="pytest.skip" message="no docker">skip</skipped>'
XFAIL = '<skipped type="pytest.xfail" message="known"/>'
STRICT_XPASS = '<skipped message="xfail-marked test passes unexpectedly"/>'
FAIL = '<failure message="boom">trace</failure>'
ERROR = '<error message="setup">trace</error>'


def _junit(*cases: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
        + "".join(cases)
        + "</testsuite></testsuites>"
    )


def _inputs(*tests: str) -> Inputs:
    return Inputs(pr=12, tests=tests or (WANTED,), sha=SHA, dispatch_id="d-9")


def _report(junit: str, exit_code: int = 0, *tests: str, output: str = "") -> EvidenceReport:
    built = build_report(_inputs(*tests), SuiteRun(exit_code, output), junit, "https://run")
    return EvidenceReport.model_validate_json(built.to_json())


def _outcomes(report: EvidenceReport) -> list[TestOutcome]:
    return [r.outcome for r in report.requested]


def test_green_suite_with_the_requested_test_passed_is_passed() -> None:
    report = _report(_junit(PASS_WANTED, PASS_OTHER))

    assert report.kind is EvidenceKind.INTEGRATION
    assert report.verdict is EvidenceVerdict.PASSED
    assert (report.pr, report.head_sha, report.dispatch_id) == (12, SHA, "d-9")
    assert _outcomes(report) == [TestOutcome.PASSED]
    assert (report.suite.collected, report.suite.passed) == (2, 2)
    assert WANTED in report.report_md


def test_an_unrelated_skip_is_counted_and_does_not_void() -> None:
    report = _report(
        _junit(
            PASS_WANTED, _case(OTHER_FILE, "tests.integration.test_other", "test_unrelated", SKIP)
        )
    )

    assert report.verdict is EvidenceVerdict.PASSED
    assert report.suite.skipped == 1


@pytest.mark.parametrize(
    ("body", "outcome"),
    [(SKIP, TestOutcome.SKIPPED), (XFAIL, TestOutcome.XFAIL)],
)
def test_a_requested_test_that_did_not_run_and_pass_voids(body: str, outcome: TestOutcome) -> None:
    report = _report(
        _junit(
            _case(STORE, "tests.integration.test_store.TestStore", "test_append[pg]", body),
            PASS_OTHER,
        )
    )

    assert report.verdict is EvidenceVerdict.VOID
    assert _outcomes(report) == [outcome]
    assert WANTED in report.summary


def test_a_requested_non_strict_xpass_voids_though_junit_calls_it_a_pass() -> None:
    report = _report(_junit(PASS_WANTED, PASS_OTHER), output=f"XPASS {WANTED} - known\n")

    assert report.verdict is EvidenceVerdict.VOID
    assert _outcomes(report) == [TestOutcome.XFAIL]


def test_a_strict_xpass_is_a_failure() -> None:
    strict = _case(OTHER_FILE, "tests.integration.test_other", "test_unrelated", STRICT_XPASS)

    report = _report(_junit(PASS_WANTED, strict), 1)

    assert report.verdict is EvidenceVerdict.FAILED


def test_a_requested_test_that_was_never_collected_voids() -> None:
    report = _report(_junit(PASS_OTHER))

    assert report.verdict is EvidenceVerdict.VOID
    assert _outcomes(report) == [TestOutcome.NOT_COLLECTED]


def test_a_near_miss_name_is_not_the_requested_test() -> None:
    lookalike = _case(STORE, "tests.integration.test_store.TestStore", "test_append_more")

    selector = "tests/integration/test_store.py::TestStore::test_append"

    report = _report(_junit(lookalike, PASS_OTHER), 0, selector)

    assert _outcomes(report) == [TestOutcome.NOT_COLLECTED]


@pytest.mark.parametrize("body", [FAIL, ERROR])
def test_any_failure_in_the_suite_fails_even_an_unrequested_one(body: str) -> None:
    report = _report(
        _junit(
            PASS_WANTED, _case(OTHER_FILE, "tests.integration.test_other", "test_unrelated", body)
        ),
        1,
    )

    assert report.verdict is EvidenceVerdict.FAILED
    assert report.suite.failed == 1
    assert _outcomes(report) == [TestOutcome.PASSED]


def test_a_teardown_error_after_a_pass_is_a_failure() -> None:
    teardown = _case(STORE, "tests.integration.test_store.TestStore", "test_append[pg]", ERROR)

    report = _report(_junit(PASS_WANTED, teardown, PASS_OTHER), 1)

    assert report.verdict is EvidenceVerdict.FAILED
    assert _outcomes(report) == [TestOutcome.FAILED]
    assert report.suite.collected == 2


@pytest.mark.parametrize("exit_code", [2, 3, 4, -1])
def test_a_run_that_stopped_with_nothing_on_record_is_void(exit_code: int) -> None:
    report = _report(_junit(PASS_WANTED, PASS_OTHER), exit_code)

    assert report.verdict is EvidenceVerdict.VOID
    assert f"pytest exit {exit_code}" in report.summary


def test_a_file_selector_covers_every_case_in_it_and_takes_the_worst() -> None:
    selector = "tests/integration/test_store.py"
    skipped_sibling = _case(STORE, "tests.integration.test_store.TestStore", "test_read", SKIP)

    report = _report(_junit(PASS_WANTED, skipped_sibling), 0, selector)

    assert _outcomes(report) == [TestOutcome.SKIPPED]
    assert report.verdict is EvidenceVerdict.VOID


@pytest.mark.parametrize(
    ("node_id", "address"),
    [
        ("tests/test_x.py", "tests.test_x"),
        ("tests/test_x.py::test_y", "tests.test_x.test_y"),
        ("a/b/test_x.py::TestC::test_y[p-1]", "a.b.test_x.TestC.test_y[p-1]"),
        ("tests/test_x.py::test_y[a::b c/d.py]", "tests.test_x.test_y[a::b c/d.py]"),
    ],
)
def test_mangle_matches_pytest_junit_addresses(node_id: str, address: str) -> None:
    assert mangle(node_id) == address


def test_inputs_are_validated_and_deduplicated() -> None:
    env = {
        ie.ENV_PR: "12",
        ie.ENV_TESTS: f"{WANTED} {WANTED}",
        ie.ENV_SHA: SHA,
        ie.ENV_DISPATCH_ID: "d-9",
    }

    assert inputs_from_env(env).tests == (WANTED,)
    with pytest.raises(ie.InputError):
        inputs_from_env({**env, ie.ENV_TESTS: "tests/x.py --pdb"})
    with pytest.raises(ie.InputError):
        inputs_from_env({**env, ie.ENV_SHA: "HEAD"})


def test_pytest_runs_the_full_suite_without_stopping_early(tmp_path: Path) -> None:
    args = ie.pytest_args(tmp_path / "j.xml")

    assert "-x" not in args
    assert "-rfEsxX" in args  # the XPASS lines parse_junit needs
    assert args[args.index("-m") + 1] == "integration"
    assert f"--junitxml={tmp_path / 'j.xml'}" in args


def _cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ie.ENV_PR, "12")
    monkeypatch.setenv(ie.ENV_TESTS, WANTED)
    monkeypatch.setenv(ie.ENV_SHA, SHA)
    monkeypatch.setenv(ie.ENV_DISPATCH_ID, "d-9")


def test_run_writes_the_report_and_evidence_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cli_env(monkeypatch)

    def fake_suite(_root: Path, junit: Path) -> SuiteRun:
        junit.write_text(_junit(PASS_WANTED))
        return SuiteRun(0, "")

    monkeypatch.setattr(ie, "run_suite", fake_suite)
    md, evidence = tmp_path / "r.md", tmp_path / "evidence.json"

    code = ie.main(
        ["run", "--root", str(tmp_path), "--report", str(md), "--evidence", str(evidence)]
    )

    report = EvidenceReport.model_validate_json(evidence.read_text())
    assert code == 0
    assert report.verdict is EvidenceVerdict.PASSED
    assert report.report_md == md.read_text()


def test_run_writes_no_evidence_json_without_a_junit_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cli_env(monkeypatch)
    monkeypatch.setattr(ie, "run_suite", lambda _root, _junit: SuiteRun(3, ""))
    md, evidence = tmp_path / "r.md", tmp_path / "evidence.json"

    code = ie.main(
        ["run", "--root", str(tmp_path), "--report", str(md), "--evidence", str(evidence)]
    )

    assert code == 1
    assert not evidence.exists()


def _real_pytest(root: Path, *argv: str) -> tuple[SuiteRun, str]:
    """Real pytest with the runner's own report flags: its JUnit and output."""
    junit = root / "j.xml"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "--rootdir", str(root),
         *ie.PYTEST_REPORT_ARGS, f"--junitxml={junit}", *argv],
        cwd=root, capture_output=True, text=True, check=False,
    )  # fmt: skip
    return SuiteRun(proc.returncode, proc.stdout + proc.stderr), junit.read_text()


def test_a_real_pytest_junit_report_maps_back_to_node_ids(tmp_path: Path) -> None:
    # The JUnit shape is pytest's, not ours: drive real pytest once so a change
    # in its address mangling or XPASS encoding fails here, not in the gate.
    suite = tmp_path / "tests" / "integration"
    suite.mkdir(parents=True)
    (suite / "test_store.py").write_text(
        "import pytest\n"
        "class TestStore:\n"
        "    @pytest.mark.parametrize('db', ['pg'])\n"
        "    def test_append(self, db):\n        pass\n"
        "@pytest.mark.xfail(reason='known')\n"
        "def test_xpass():\n    pass\n"
        "def test_skip():\n    pytest.skip('no docker')\n"
    )
    run, junit = _real_pytest(tmp_path, "tests")
    xpass = "tests/integration/test_store.py::test_xpass"
    skip = "tests/integration/test_store.py::test_skip"

    report = _report(junit, run.exit_code, WANTED, xpass, skip, output=run.output)

    assert _outcomes(report) == [TestOutcome.PASSED, TestOutcome.XFAIL, TestOutcome.SKIPPED]
    assert report.suite.collected == 3


@pytest.mark.parametrize("param", ["normal", "has space", "has::colon", "a - b"])
def test_a_file_selector_never_certifies_an_xpass_whatever_its_parameter(
    tmp_path: Path, param: str
) -> None:
    # A file selector reaches parameter ids the request grammar never sees.
    (tmp_path / "test_shapes.py").write_text(
        "import pytest\n"
        "def test_first_passes(): pass\n"
        f"@pytest.mark.parametrize('value', [{param!r}])\n"
        "@pytest.mark.xfail(reason='known')\n"
        "def test_second_xpasses(value): pass\n"
    )
    run, junit = _real_pytest(tmp_path, "test_shapes.py")
    function = "test_shapes.py::test_second_xpasses"

    report = _report(junit, run.exit_code, "test_shapes.py", function, output=run.output)

    assert run.exit_code == 0, run.output
    assert _outcomes(report) == [TestOutcome.XFAIL, TestOutcome.XFAIL]
    assert report.verdict is EvidenceVerdict.VOID
    assert (report.suite.passed, report.suite.skipped) == (1, 1)


def test_a_deselected_file_cannot_borrow_a_pass_from_a_same_named_directory(
    tmp_path: Path,
) -> None:
    # `tests/test_shapes.py` and `tests/test_shapes/` share a dotted address.
    nested = tmp_path / "tests" / "test_shapes"
    nested.mkdir(parents=True)
    (tmp_path / "tests" / "test_shapes.py").write_text("def test_not_integration(): pass\n")
    (nested / "test_other.py").write_text(
        "import pytest\n@pytest.mark.integration\ndef test_pass(): pass\n"
    )
    run, junit = _real_pytest(tmp_path, "-m", "integration", "tests")
    other = "tests/test_shapes/test_other.py"

    report = _report(junit, run.exit_code, "tests/test_shapes.py", other, output=run.output)

    assert run.exit_code == 0, run.output
    assert _outcomes(report) == [TestOutcome.NOT_COLLECTED, TestOutcome.PASSED]
    assert report.verdict is EvidenceVerdict.VOID


def test_a_class_function_and_parameter_selector_still_select(tmp_path: Path) -> None:
    (tmp_path / "test_c.py").write_text(
        "import pytest\n"
        "class TestC:\n"
        "    @pytest.mark.parametrize('v', ['x-1', 'p::q'])\n"
        "    def test_f(self, v): pass\n"
    )
    run, junit = _real_pytest(tmp_path, "test_c.py")
    selectors = ("test_c.py::TestC", "test_c.py::TestC::test_f", "test_c.py::TestC::test_f[x-1]")

    report = _report(junit, run.exit_code, *selectors, output=run.output)

    assert _outcomes(report) == [TestOutcome.PASSED] * 3
    assert report.verdict is EvidenceVerdict.PASSED


def test_a_case_whose_file_does_not_fit_cannot_certify_a_selector() -> None:
    # An inherited test reports the file it was DEFINED in, not collected from.
    inherited = _case("tests/base.py", "tests.integration.test_store.TestStore", "test_append[pg]")

    report = _report(_junit(inherited, PASS_OTHER))

    assert _outcomes(report) == [TestOutcome.NOT_COLLECTED]


def test_a_case_whose_file_does_not_fit_can_still_make_a_selector_worse() -> None:
    inherited = _case("tests/base.py", "tests.integration.test_store.TestStore", "test_read", SKIP)

    report = _report(_junit(PASS_WANTED, inherited), 0, STORE)

    assert _outcomes(report) == [TestOutcome.SKIPPED]
    assert report.verdict is EvidenceVerdict.VOID


@pytest.mark.parametrize("param", ["normal", "has space", "has::colon"])
def test_an_inherited_xpass_cannot_pass_a_file_through_its_passing_sibling(
    tmp_path: Path, param: str
) -> None:
    # The inherited case's `file` is base.py, so it has no node id: only its
    # dotted address can carry the XPASS, and JUnit itself calls it a pass.
    (tmp_path / "base.py").write_text(
        "import pytest\n"
        "class Base:\n"
        f"    @pytest.mark.parametrize('value', [{param!r}])\n"
        "    @pytest.mark.xfail(reason='known')\n"
        "    def test_inherited(self, value): pass\n"
    )
    (tmp_path / "test_child.py").write_text(
        "import pytest\n"
        "pytestmark = pytest.mark.integration\n"
        "from base import Base\n"
        "class TestChild(Base): pass\n"
        "def test_ordinary(): pass\n"
    )
    run, junit = _real_pytest(tmp_path, "-m", "integration", "test_child.py")

    report = _report(junit, run.exit_code, "test_child.py", output=run.output)

    assert run.exit_code == 0, run.output
    assert _outcomes(report) == [TestOutcome.XFAIL]
    assert report.verdict is EvidenceVerdict.VOID
    assert (report.suite.passed, report.suite.skipped) == (1, 1)
