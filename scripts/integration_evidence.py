"""Integration evidence: run the whole integration suite and say what it proved.

Run by `.github/workflows/integration-evidence.yml` (plan
docs/plans/20261015_platform-dispatched-evidence.md, PR 3), or locally with
`just test-integration-ci`. CI's integration job runs `pytest -m integration
-x -q`, which stops at the first failure and names no test; this runner runs
the FULL suite with JUnit XML, so every outcome is on record.

The verdict, schema 1 of `evidence.json` (ADR-014 §10, plan §A.1):

- `failed`: any integration test failed or errored.
- `void`: a REQUESTED test was not collected, or was skipped, xfailed or
  xpassed, or pytest stopped without recording a failure. None of those is a
  pass, and each would read as one.
- `passed`: otherwise. The whole suite was green on that head AND every test
  the phase named ran and passed. Unrelated skips are counted in
  `suite.skipped` and do not void.

Like `mutation_evidence.py` this script is trusted and stdlib-only, run with
`python -I` on the host; it shares that script's input grammar and the
`evidence.json` types rather than restating them. The integration suite runs on
the host, as in ci.yml: the suite drives Docker and real services.

Usage:

    integration_evidence.py validate                         # inputs from env
    integration_evidence.py run --root PR --report FILE --evidence FILE
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

# `python -I` puts no script directory on sys.path. This one is the trusted
# checkout the script itself was read from, never the PR's.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mutation_evidence import (
    EvidenceReport,
    InputError,
    RequestedResult,
    SuiteCounts,
    TestOutcome,
    Verdict,
    parse_dispatch_id,
    parse_pr,
    parse_tests,
)

MARKER: Final = "<!-- integration-evidence -->"

ENV_PR: Final = "INTEGRATION_PR"
ENV_TESTS: Final = "INTEGRATION_TESTS"
ENV_SHA: Final = "INTEGRATION_SHA"
ENV_DISPATCH_ID: Final = "INTEGRATION_DISPATCH_ID"

PYTEST_TIMEOUT_SECONDS: Final = 45 * 60
#: pytest writes a STRICT xpass, which fails the run, as a `skipped` element
#: with this message.
_STRICT_XPASS_MESSAGE: Final = "xfail-marked test passes unexpectedly"
#: A non-strict xpass is a plain pass in JUnit; only the `-rX` summary says so,
#: as `XPASS <node id>` or `XPASS <node id> - <reason>`.
_XPASS_PREFIX: Final = "XPASS "
#: JUnit flags the parse depends on. xunit1 keeps each testcase's `file`: its
#: `classname` alone cannot tell `tests/a.py` from a `tests/a/` directory.
PYTEST_REPORT_ARGS: Final = ("-p", "no:cacheprovider", "--color=no", "-q", "-rfEsxX",
                             "-o", "junit_family=xunit1")  # fmt: skip


@dataclass(frozen=True)
class Inputs:
    pr: int
    tests: tuple[str, ...]
    sha: str
    dispatch_id: str


@dataclass(frozen=True)
class Case:
    """One JUnit `testcase`: its pytest node id and what happened.

    `node_id` is None when the testcase's `file` does not prefix its
    `classname` (a test inherited from another module): then only the lossy
    dotted `address` is known, and it can never certify a selector.
    """

    node_id: str | None
    address: str
    outcome: TestOutcome


def inputs_from_env(env: dict[str, str]) -> Inputs:
    sha = env.get(ENV_SHA, "")
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise InputError(f"{ENV_SHA} {sha!r} is not a commit sha")
    return Inputs(
        pr=parse_pr(env.get(ENV_PR, "")),
        tests=tuple(dict.fromkeys(parse_tests(env.get(ENV_TESTS, "")))),
        sha=sha,
        dispatch_id=parse_dispatch_id(env.get(ENV_DISPATCH_ID, "")),
    )


def _dotted(path: str) -> str:
    return path.removesuffix(".py").replace("/", ".")


def mangle(node_id: str) -> str:
    """A node id in pytest junitxml's address space (`mangle_test_address`).

    JUnit names a test by `classname` + `name`: the node id's path with `/` ->
    `.` and `.py` dropped, then its `::` parts, then any `[params]` verbatim.
    Lossy (a dot may have been a slash), so it only ever widens a failure.
    """
    path, bracket, params = node_id.partition("[")
    names = path.split("::")
    names[0] = _dotted(names[0])
    return ".".join(names) + bracket + params


def node_id_of(file: str, classname: str, name: str) -> str | None:
    """Undo `mangle` using the testcase's `file`; None if it does not fit."""
    if not file:
        return None
    module = _dotted(file)
    if classname == module:
        return f"{file}::{name}"
    if classname.startswith(f"{module}."):
        # Class names are identifiers, so the remaining dots are all `::`.
        return "::".join((file, *classname[len(module) + 1 :].split("."), name))
    return None


def _selects(selector: str, node_id: str) -> bool:
    return node_id == selector or node_id.startswith((f"{selector}::", f"{selector}["))


def _addresses_overlap(selector: str, address: str) -> bool:
    return address == selector or address.startswith((f"{selector}.", f"{selector}["))


def _xpassed(node_id: str, xpass_lines: list[str]) -> bool:
    line = f"{_XPASS_PREFIX}{node_id}"
    return any(x == line or x.startswith(f"{line} - ") for x in xpass_lines)


def _xpassed_address(address: str, xpass_lines: list[str]) -> bool:
    """Whether an XPASS line could name the case at JUnit `address`.

    For a case with no node id. A ` - ` may sit in the parameters or before
    the reason, so every cut is tried; lossy, so it only ever widens to xfail.
    """
    for line in xpass_lines:
        parts = line.removeprefix(_XPASS_PREFIX).split(" - ")
        if any(mangle(" - ".join(parts[:n])) == address for n in range(1, len(parts) + 1)):
            return True
    return False


def _case_outcome(case: ET.Element) -> TestOutcome:
    if case.find("failure") is not None or case.find("error") is not None:
        return TestOutcome.FAILED
    skipped = case.find("skipped")
    if skipped is None:
        return TestOutcome.PASSED
    # The type decides, never the wording: a skip or xfail reason is the
    # test author's free text, and may read exactly like the untyped record
    # pytest writes for an unexpected pass.
    kind = skipped.get("type")
    if kind == "pytest.xfail":
        return TestOutcome.XFAIL
    if kind is None and skipped.get("message") == _STRICT_XPASS_MESSAGE:
        return TestOutcome.FAILED
    return TestOutcome.SKIPPED


def parse_junit(xml_text: str, output: str) -> list[Case]:
    """Every testcase in a pytest JUnit report, corrected by pytest's terminal
    `output`. A teardown error, or a hook that runs an item twice, repeats a
    testcase; the worst outcome any record had is kept, so a later pass can
    never erase an earlier failure, skip or xfail."""
    xpass_lines = [line for line in output.splitlines() if line.startswith(_XPASS_PREFIX)]
    cases: dict[str, Case] = {}
    for element in ET.fromstring(xml_text).iter("testcase"):
        classname, name = element.get("classname", ""), element.get("name", "")
        address = f"{classname}.{name}" if classname else name
        node_id = node_id_of(element.get("file", ""), classname, name)
        outcome = _case_outcome(element)
        if outcome is TestOutcome.PASSED and (
            _xpassed(node_id, xpass_lines) if node_id else _xpassed_address(address, xpass_lines)
        ):
            outcome = TestOutcome.XFAIL
        key = node_id or address
        previous = cases.get(key)
        if previous is not None:
            outcome = _worst((previous.outcome, outcome))
        cases[key] = Case(node_id, address, outcome)
    return list(cases.values())


#: When several records or cases bear on one test, the first of these any had wins.
_PRECEDENCE: Final = (TestOutcome.FAILED, TestOutcome.SKIPPED, TestOutcome.XFAIL)


def _worst(outcomes: tuple[TestOutcome, ...] | set[TestOutcome]) -> TestOutcome:
    return next((o for o in _PRECEDENCE if o in outcomes), TestOutcome.PASSED)


def requested_outcome(node_id: str, cases: list[Case]) -> TestOutcome:
    seen = {c.outcome for c in cases if c.node_id and _selects(node_id, c.node_id)}
    if not seen:
        return TestOutcome.NOT_COLLECTED
    # A case with no recoverable id may or may not be the selector's: it can
    # make the selector worse, never pass it.
    address = mangle(node_id)
    seen |= {c.outcome for c in cases if not c.node_id and _addresses_overlap(address, c.address)}
    return _worst(seen)


def suite_counts(cases: list[Case]) -> SuiteCounts:
    def count(*outcomes: TestOutcome) -> int:
        return sum(1 for c in cases if c.outcome in outcomes)

    return SuiteCounts(
        collected=len(cases),
        passed=count(TestOutcome.PASSED),
        failed=count(TestOutcome.FAILED),
        skipped=count(TestOutcome.SKIPPED, TestOutcome.XFAIL),
    )


def decide(
    exit_code: int, suite: SuiteCounts, requested: tuple[RequestedResult, ...]
) -> tuple[Verdict, str]:
    """The §A.1 verdict and a one-line reason."""
    if suite.failed:
        return Verdict.FAILED, f"{suite.failed} integration test(s) failed or errored"
    if exit_code not in {0, 5}:
        # 5 is "nothing collected", which voids below. Anything else (an
        # interrupt, an internal or usage error) is a run that did not finish.
        return Verdict.VOID, f"pytest exit {exit_code} with no failure on record, evidence void"
    unproven = [
        f"{r.id} {r.outcome.value}" for r in requested if r.outcome is not TestOutcome.PASSED
    ]
    if unproven:
        return Verdict.VOID, f"requested test(s) did not run and pass: {', '.join(unproven)}"
    return Verdict.PASSED, (
        f"integration suite green ({suite.passed} passed, {suite.skipped} skipped); "
        "every requested test passed"
    )


def render(report: EvidenceReport, run_url: str) -> str:
    lines = [
        MARKER,
        "## Integration evidence",
        "",
        f"**{report.verdict.value.upper()}** | PR #{report.pr} | head `{report.head_sha}` | "
        f"[run]({run_url})",
        "",
        report.summary,
        "",
        "| Requested test | Outcome |",
        "|---|---|",
        *(f"| `{r.id}` | {r.outcome.value} |" for r in report.requested),
        "",
        f"Suite: {report.suite.collected} collected, {report.suite.passed} passed, "
        f"{report.suite.failed} failed, {report.suite.skipped} skipped.",
    ]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class SuiteRun:
    exit_code: int
    output: str


def build_report(inputs: Inputs, run: SuiteRun, junit_xml: str, run_url: str) -> EvidenceReport:
    cases = parse_junit(junit_xml, run.output)
    requested = tuple(RequestedResult(t, requested_outcome(t, cases)) for t in inputs.tests)
    suite = suite_counts(cases)
    verdict, summary = decide(run.exit_code, suite, requested)
    report = EvidenceReport(
        kind="integration",
        pr=inputs.pr,
        head_sha=inputs.sha,
        dispatch_id=inputs.dispatch_id,
        verdict=verdict,
        requested=requested,
        suite=suite,
        summary=summary,
        report_md="",
    )
    return replace(report, report_md=render(report, run_url))


def pytest_args(junit: Path) -> list[str]:
    # No `-x`: a run that stops at the first failure reports nothing after it.
    return [
        "uv", "run", "--frozen", "pytest", "-m", "integration", *PYTEST_REPORT_ARGS,
        f"--junitxml={junit}",
    ]  # fmt: skip


def run_suite(root: Path, junit: Path) -> SuiteRun:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    try:
        proc = subprocess.run(
            pytest_args(junit), cwd=root, env=env, capture_output=True, text=True,
            check=False, timeout=PYTEST_TIMEOUT_SECONDS,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return SuiteRun(-1, "")
    output = proc.stdout + proc.stderr
    print(output[-20000:], flush=True)
    return SuiteRun(proc.returncode, output)


def _run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate the inputs in the environment")
    run = sub.add_parser("run", help="the full integration suite against a PR checkout")
    run.add_argument("--root", type=Path, required=True, help="the PR checkout")
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--evidence", type=Path, required=True, help="evidence.json")
    args = parser.parse_args(argv)

    try:
        inputs = inputs_from_env(dict(os.environ))
    except InputError as exc:
        print(f"::error::{exc}")
        return 1
    if args.command == "validate":
        print(f"inputs ok: pr={inputs.pr} tests={len(inputs.tests)}")
        return 0

    with tempfile.TemporaryDirectory() as scratch:
        junit = Path(scratch) / "junit.xml"
        run = run_suite(args.root.resolve(), junit)
        try:
            report = build_report(inputs, run, junit.read_text(), _run_url())
        except (OSError, ET.ParseError) as exc:
            # No JUnit, no record of what ran: write no evidence.json, so the
            # gate reads "no evidence" rather than a verdict nothing backs.
            print(f"::error::pytest exit {run.exit_code} left no readable JUnit report: {exc}")
            return 1
    args.report.write_text(report.report_md)
    args.evidence.write_text(report.to_json())
    print(report.report_md)
    return 0 if report.verdict is Verdict.PASSED else 1


if __name__ == "__main__":
    sys.exit(main())
