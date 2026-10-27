"""Tests for scripts/eval_referee.py, the container referee for implementer runs (#2108 S4).

The unit tests drive the referee with a docker double that records every call,
so the order the plan requires (prepare with the network on, cut it, prove it
is cut, then run the agent's code) is asserted without Docker. The bundles are
real git. ``test_eval_referee_on_docker.py`` runs the same path on a real
container.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eval_referee
from eval_implementer import ImplementerCase
from eval_referee import (
    INTERFACE_PROBE,
    _RefereeError,
    fetch_patch,
    referee_score,
    score_case,
    scorer_commit_of,
    verdict_of,
    write_inputs,
)
from eval_suite import ROOT

pytestmark = pytest.mark.unit

SCORER_COMMIT = subprocess.run(
    ["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--", "scripts/implementer_scorer.py"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
"""A commit of this repository that holds the scorer, whatever the working tree says."""


def _git(at: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(at), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _subject(tmp_path: Path, submodule: bool = False) -> tuple[ImplementerCase, Path]:
    """A repository with a pin and a fix whose hidden test catches the bug."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    (repo / "bug.py").write_text("value = 0\n")
    if submodule:
        lib = tmp_path / "lib-origin"
        lib.mkdir()
        _git(lib, "init", "--quiet")
        _git(lib, "commit", "--quiet", "--allow-empty", "-m", "lib at the pin")
        _git(
            repo,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "--quiet",
            str(lib),
            "lib/dep",
        )
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "pin")
    pin = _git(repo, "rev-parse", "HEAD")
    if submodule:
        _git(repo / "lib/dep", "commit", "--quiet", "--allow-empty", "-m", "lib at the fix")
        _git(repo, "add", "lib/dep")
    (repo / "tests").mkdir()
    (repo / "tests/test_value.py").write_text(
        "from bug import value\n\ndef test_value():\n    assert value == 1\n"
    )
    (repo / "bug.py").write_text("value = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "fix")
    case = ImplementerCase(
        id="subject",
        source_pr=1,
        commit=pin,
        fix_commit=_git(repo, "rev-parse", "HEAD"),
        task="value must be one",
        hidden_tests=("tests/test_value.py",),
    )
    return case, repo


def _done(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


@dataclass
class FakeDocker:
    """Answers every docker call; `answers` overrides by the call's first distinctive word."""

    answers: dict[str, subprocess.CompletedProcess[str]] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    score_result: str = "RESULT: PASS"

    def __call__(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        key = _kind(args)
        if key in self.answers:
            return self.answers[key]
        if key == "offline-check":
            return _done("lo\n")
        if key == "score":
            outcome = self.score_result.removeprefix("RESULT: ")
            return _done(
                f"pytest exit\n{self.score_result}\n", {"PASS": 0, "FAIL": 1}.get(outcome, 2)
            )
        return _done()

    def kinds(self) -> list[str]:
        return [_kind(c) for c in self.calls]


def _kind(args: list[str]) -> str:
    if args[:2] == ["network", "disconnect"]:
        return "disconnect"
    if args[:1] == ["exec"] and "prepare" in args:
        return "prepare"
    if args[:1] == ["exec"] and "score" in args:
        return "score"
    if args[:1] == ["exec"] and INTERFACE_PROBE in args:
        return "offline-check"
    if args[:1] == ["exec"] and "fetch" in args:
        return "unbundle"
    return " ".join(args[:2])


def _score(
    case: ImplementerCase, repo: Path, docker: FakeDocker, patch: str = "x"
) -> eval_referee.TestRun:
    return referee_score(
        case.pin(), patch, repo=repo, scorer_commit=SCORER_COMMIT, image="image", docker=docker
    )


def test_the_agent_s_code_runs_only_after_the_network_is_cut_and_proven_cut(tmp_path: Path) -> None:
    case, repo = _subject(tmp_path)
    docker = FakeDocker()
    run = _score(case, repo, docker)
    assert run.outcome == "PASS", run.detail
    kinds = docker.kinds()
    assert (
        kinds.index("prepare")
        < kinds.index("disconnect")
        < kinds.index("offline-check")
        < kinds.index("score")
    )
    run_call = next(c for c in docker.calls if c[:1] == ["run"])
    assert run_call[run_call.index("--network") + 1] == run_call[run_call.index("--name") + 1]
    assert any(a.endswith(":ro") for a in run_call)
    assert kinds[-2:] == ["rm --force", "network rm"]


@pytest.mark.parametrize(
    "answers",
    [
        {"disconnect": _done(code=1, stderr="no such network")},
        {"offline-check": _done("eth0 lo\n")},
        {"offline-check": _done(code=126)},
        {"prepare": _done("collect failed\nRESULT: ERROR\n", 2)},
        {"unbundle": _done(code=128, stderr="bad bundle")},
    ],
    ids=["disconnect-fails", "interface-left", "check-fails", "prepare-fails", "unbundle-fails"],
)
def test_no_patch_is_scored_unless_everything_before_it_held(
    tmp_path: Path, answers: dict[str, subprocess.CompletedProcess[str]]
) -> None:
    case, repo = _subject(tmp_path)
    docker = FakeDocker(answers=answers)
    run = _score(case, repo, docker)
    assert run.outcome == "ERROR"
    assert "score" not in docker.kinds()
    assert docker.kinds()[-2:] == ["rm --force", "network rm"]


@pytest.mark.parametrize(
    "answers",
    [
        {"rm --force": _done(code=1, stderr="Error response from daemon: device busy")},
        {"network rm": _done(code=124, stderr="timed out after 300s")},
    ],
    ids=["container-stays", "network-stays"],
)
def test_a_pass_is_withheld_when_cleanup_does_not_hold(
    tmp_path: Path, answers: dict[str, subprocess.CompletedProcess[str]]
) -> None:
    case, repo = _subject(tmp_path)
    docker = FakeDocker(answers=answers)
    run = _score(case, repo, docker)
    assert run.outcome == "ERROR", run.detail
    assert "verdict PASS withheld" in run.detail
    (kind,) = answers
    assert docker.kinds().count(kind) == 3


def test_cleanup_of_what_was_never_made_is_not_an_error(tmp_path: Path) -> None:
    case, repo = _subject(tmp_path)
    docker = FakeDocker(
        answers={
            "rm --force": _done(code=1, stderr="Error response from daemon: No such container: x"),
            "network rm": _done(code=1, stderr="Error response from daemon: network x not found"),
        }
    )
    assert _score(case, repo, docker).outcome == "PASS"


def test_the_scorer_is_read_from_its_recorded_commit_not_the_working_tree(tmp_path: Path) -> None:
    case, repo = _subject(tmp_path)
    into = tmp_path / "in"
    into.mkdir()
    write_inputs(case.pin(), "patch text", SCORER_COMMIT, repo, into)
    recorded = _git(ROOT, "show", f"{SCORER_COMMIT}:scripts/implementer_scorer.py")
    assert (into / "implementer_scorer.py").read_text().strip() == recorded
    assert (into / "implement.patch").read_text() == "patch text"


def test_the_bundles_hold_the_pin_the_fix_and_every_submodule_gitlink_and_leave_no_ref(
    tmp_path: Path,
) -> None:
    case, repo = _subject(tmp_path, submodule=True)
    refs_before = _git(repo, "for-each-ref")
    into = tmp_path / "in"
    into.mkdir()
    assert write_inputs(case.pin(), "", SCORER_COMMIT, repo, into) == ["lib/dep"]

    clone = tmp_path / "clone"
    _git(tmp_path, "init", "--quiet", str(clone))
    subprocess.run(eval_referee.unbundle(str(into / "repo.bundle"), str(clone)), check=True)
    for sha in (case.commit, case.fix_commit):
        _git(clone, "cat-file", "-e", f"{sha}^{{commit}}")
    sub = clone / "lib/dep"
    _git(tmp_path, "init", "--quiet", str(sub))
    subprocess.run(eval_referee.unbundle(str(into / "submodule-0.bundle"), str(sub)), check=True)
    for sha in (case.commit, case.fix_commit):
        gitlink = _git(repo, "ls-tree", sha, "lib/dep").split()[2]
        _git(sub, "cat-file", "-e", f"{gitlink}^{{commit}}")
    assert _git(repo, "for-each-ref") == refs_before
    assert _git(repo / "lib/dep", "for-each-ref", eval_referee._REF_NAMESPACE) == ""


def test_a_submodule_with_no_local_clone_is_error_not_a_fetch(tmp_path: Path) -> None:
    case, repo = _subject(tmp_path, submodule=True)
    clone = tmp_path / "fresh"
    _git(tmp_path, "clone", "--quiet", str(repo), str(clone))  # submodules not initialised
    docker = FakeDocker()
    run = _score(case, clone, docker)
    assert run.outcome == "ERROR"
    assert "no local clone" in run.detail
    assert docker.calls == []


@pytest.mark.parametrize(
    ("stdout", "code", "outcome"),
    [
        ("pytest exit 0\nRESULT: PASS\n", 0, "PASS"),
        ("pytest exit 1\nRESULT: FAIL\n", 1, "FAIL"),
        ("prepared tree has no .venv\nRESULT: ERROR\n", 2, "ERROR"),
        ("Traceback (most recent call last):\nKeyError: 'x'\n", 1, "ERROR"),
        ("pytest exit 0\nRESULT: PASS\n", 1, "ERROR"),
        ("RESULT: FAIL\n", 0, "ERROR"),
        ("", 137, "ERROR"),
    ],
    ids=["pass", "fail", "error", "crash", "pass-but-exit-1", "fail-but-exit-0", "killed"],
)
def test_a_verdict_needs_the_result_line_and_the_exit_code_to_agree(
    stdout: str, code: int, outcome: str
) -> None:
    assert verdict_of(_done(stdout, code)).outcome == outcome


def test_no_agent_patch_is_scored_when_a_control_does_not_hold(tmp_path: Path) -> None:
    case, repo = _subject(tmp_path)
    docker = FakeDocker(score_result="RESULT: PASS")  # so the empty patch PASSes too
    controls, scored = score_case(
        case,
        [("exec-1", "agent patch")],
        repo=repo,
        scorer_commit=SCORER_COMMIT,
        image="i",
        docker=docker,
    )
    assert [c.run.outcome for c in controls] == ["PASS", "PASS"]
    assert scored == []
    assert docker.kinds().count("score") == 2


def test_agent_patches_are_scored_after_both_controls_hold(tmp_path: Path) -> None:
    case, repo = _subject(tmp_path)
    results = iter(["RESULT: PASS", "RESULT: FAIL", "RESULT: FAIL"])

    class Sequenced(FakeDocker):
        def __call__(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            if _kind(args) == "score":
                self.score_result = next(results)
            return super().__call__(args, timeout)

    controls, scored = score_case(
        case,
        [("exec-1", "agent patch")],
        repo=repo,
        scorer_commit=SCORER_COMMIT,
        image="i",
        docker=Sequenced(),
    )
    assert [c.run.outcome for c in controls] == ["PASS", "FAIL"]
    assert [(s.label, s.run.outcome) for s in scored] == [("exec-1", "FAIL")]


def test_a_scorer_with_uncommitted_changes_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "scorer-repo"
    (repo / "scripts").mkdir(parents=True)
    _git(repo, "init", "--quiet")
    (repo / "scripts/implementer_scorer.py").write_text("committed\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "scorer")
    assert scorer_commit_of(repo) == _git(repo, "rev-parse", "HEAD")
    (repo / "scripts/implementer_scorer.py").write_text("edited\n")
    with pytest.raises(_RefereeError, match="uncommitted"):
        scorer_commit_of(repo)


def _api(
    artifacts: list[dict[str, str]], raw: bytes = b"diff --git a/x b/x\n", cap: int = 200
) -> httpx.Client:
    """The listing pages as the API does, `page_size` capped at `cap` (the API's is 200)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/artifacts":
            assert request.url.params["execution_id"] == "exec-1"
            assert request.url.params["phase_id"] == "implement"
            size = min(int(request.url.params.get("page_size", "50")), cap)
            start = (int(request.url.params.get("page", "1")) - 1) * size
            page = artifacts[start : start + size]
            return httpx.Response(200, json={"artifacts": page, "total": len(artifacts)})
        return httpx.Response(200, content=raw)

    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))


def test_the_patch_is_the_implement_phase_s_one_implement_patch_byte_for_byte() -> None:
    raw = b"diff --git a/x b/x\n \n+trailing space kept \n"
    client = _api(
        [{"id": "a1", "title": "implement.patch"}, {"id": "a2", "title": "notes.md"}], raw
    )
    assert fetch_patch(client, "exec-1") == raw.decode()


def test_every_page_is_read_before_the_patch_is_chosen() -> None:
    notes = [{"id": f"n{i}", "title": f"notes-{i}.md"} for i in range(3)]
    patch = {"id": "p1", "title": "Implement: implement.patch"}
    assert fetch_patch(_api([*notes, patch], cap=2), "exec-1") == "diff --git a/x b/x\n"
    with pytest.raises(_RefereeError, match=r"has 2 implement\.patch"):
        fetch_patch(
            _api([patch, *notes, {"id": "p2", "title": "implement.patch"}], cap=2), "exec-1"
        )


def test_a_patch_that_is_not_utf_8_reaches_the_container_byte_for_byte(tmp_path: Path) -> None:
    raw = b"diff --git a/x b/x\n+caf\xe9 latin-1\n"
    patch = fetch_patch(_api([{"id": "p1", "title": "implement.patch"}], raw), "exec-1")
    case, repo = _subject(tmp_path)
    into = tmp_path / "in"
    into.mkdir()
    write_inputs(case.pin(), patch, SCORER_COMMIT, repo, into)
    assert (into / "implement.patch").read_bytes() == raw


@pytest.mark.parametrize(
    "artifacts",
    [
        [],
        [{"id": "a1", "title": "notes.md"}],
        [{"id": "a1", "title": "implement.patch"}, {"id": "a2", "title": "x/implement.patch"}],
    ],
    ids=["none", "no-patch", "two-patches"],
)
def test_a_run_without_exactly_one_patch_is_refused_not_guessed(
    artifacts: list[dict[str, str]],
) -> None:
    with pytest.raises(_RefereeError, match=r"implement\.patch"):
        fetch_patch(_api(artifacts), "exec-1")
