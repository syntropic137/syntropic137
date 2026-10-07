"""Tests for scripts/eval_suite.py and the suites it reads (#967 step 8).

The checked-in suite is validated for real: its files must parse, agree with
the workflow they name, and (on a full clone) pin commits that exist and that
the recorded fix descends from. The scorer and the launcher are driven through
an HTTP transport that answers with the API's own response shapes, so a field
the script reads under the wrong name fails here rather than on the owner's
first scored run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_suite import (
    DEFAULT_SUITE,
    ROOT,
    DefinitionError,
    Expected,
    check_commits,
    launch_suite,
    load_suite,
    render,
    score_report,
    score_suite,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _copy_suite(tmp_path: Path) -> Path:
    target = tmp_path / "suite"
    shutil.copytree(DEFAULT_SUITE, target)
    return target


# ---------------------------------------------------------------------------
# The checked-in suite
# ---------------------------------------------------------------------------


def test_the_seed_suite_loads_and_records_its_workflow_and_models() -> None:
    loaded = load_suite(DEFAULT_SUITE)

    assert loaded.suite.tag == "verifier-seed-v1:v1"
    assert loaded.suite.workflow.id == "eval-verify-pinned-v1"
    assert loaded.suite.workflow.models == {"verify": "opus"}
    assert {c.source_pr for c in loaded.cases} == {1574, 1649, 1652, 1654}


def _is_shallow() -> bool:
    return _git(ROOT, "rev-parse", "--is-shallow-repository") == "true"


@pytest.mark.skipif(_is_shallow(), reason="a shallow clone does not hold the pinned commits")
def test_every_seed_pins_a_real_commit_before_its_fix() -> None:
    assert check_commits(load_suite(DEFAULT_SUITE), ROOT) == []


# ---------------------------------------------------------------------------
# Definition validation
# ---------------------------------------------------------------------------


def test_a_model_change_without_the_suite_record_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    suite_yaml = suite_dir / "suite.yaml"
    suite_yaml.write_text(suite_yaml.read_text().replace("verify: opus", "verify: sonnet"))

    with pytest.raises(DefinitionError, match="the workflow declares"):
        load_suite(suite_dir)


def test_a_task_that_names_the_source_pr_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    case = suite_dir / "cases" / "codex-cost-limit.yaml"
    case.write_text(case.read_text().replace("The change under review", "PR #1654"))

    with pytest.raises(DefinitionError, match="names #1654"):
        load_suite(suite_dir)


def test_an_abbreviated_sha_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    case = suite_dir / "cases" / "codex-cost-limit.yaml"
    case.write_text(
        case.read_text().replace("123b25204fce5052f1b0ab494d2c59fa607624ad", "123b25204")
    )

    with pytest.raises(DefinitionError, match="full 40-character"):
        load_suite(suite_dir)


def test_a_case_file_must_be_named_for_its_case(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    cases = suite_dir / "cases"
    (cases / "codex-cost-limit.yaml").rename(cases / "renamed.yaml")

    with pytest.raises(DefinitionError, match="file name must be the case id"):
        load_suite(suite_dir)


# ---------------------------------------------------------------------------
# check_commits against a repository built for the purpose
# ---------------------------------------------------------------------------


@pytest.fixture
def history(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A repo with bug -> fix (touching bug.py) -> unrelated (touching other.py)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "bug.py").write_text("broken\n")
    (repo / "other.py").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "bug")
    bug = _git(repo, "rev-parse", "HEAD")
    (repo / "bug.py").write_text("fixed\n")
    _git(repo, "commit", "-qam", "fix")
    fix = _git(repo, "rev-parse", "HEAD")
    (repo / "other.py").write_text("y\n")
    _git(repo, "commit", "-qam", "unrelated")
    unrelated = _git(repo, "rev-parse", "HEAD")
    return repo, bug, fix, unrelated


def _one_case_suite(tmp_path: Path, commit: str, fix: str, file: str) -> Path:
    suite_dir = _copy_suite(tmp_path)
    cases = suite_dir / "cases"
    for p in cases.glob("*.yaml"):
        p.unlink()
    (cases / "seed.yaml").write_text(
        json.dumps(
            {
                "id": "seed",
                "source_pr": 1,
                "commit": commit,
                "fix_commit": fix,
                "task": "Review it.",
                "expected": {"files": [file], "keywords": [["broken"]]},
            }
        )
    )
    return suite_dir


def test_check_passes_a_pin_its_fix_descends_from(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, fix, _ = history
    assert check_commits(load_suite(_one_case_suite(tmp_path, bug, fix, "bug.py")), repo) == []


def test_check_refuses_a_pin_after_its_fix(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, fix, _ = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, fix, bug, "bug.py")), repo)
    assert any("is not an ancestor" in p for p in problems)


def test_check_refuses_a_fix_that_does_not_touch_the_expected_file(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, _, fix, unrelated = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, fix, unrelated, "bug.py")), repo)
    assert problems == ["seed: the fix changes none of ['bug.py']"]


def test_check_refuses_a_sha_the_repo_does_not_hold(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, _, _ = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, bug, "f" * 40, "bug.py")), repo)
    assert problems == [f"seed: no such commit {'f' * 40} (try `git fetch origin`)"]


def test_check_refuses_a_file_absent_at_the_pin(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, fix, _ = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, bug, fix, "missing.py")), repo)
    assert "seed: missing.py does not exist at " + bug[:12] in problems


# ---------------------------------------------------------------------------
# score_report
# ---------------------------------------------------------------------------

_EXPECTED = Expected(
    files=("packages/syn-adapters/src/syn_adapters/storage/artifact_storage/minio.py",),
    keywords=(("key",), ("404", "not found")),
)
_FINDING = "BLOCKING: minio.py:212 download() builds the id-only key; upload keys by execution, so reads 404."


def test_a_blocked_report_naming_file_and_defect_passes() -> None:
    assert score_report(_EXPECTED, "blocked", _FINDING).passed


def test_a_certified_run_fails_even_when_the_report_names_the_defect() -> None:
    score = score_report(_EXPECTED, "certified", _FINDING)
    assert score.matched and not score.passed


def test_a_report_that_misses_the_file_does_not_match() -> None:
    score = score_report(_EXPECTED, "blocked", "the object key does not match, so reads 404")
    assert score.named_file is None and not score.passed


def test_a_report_missing_a_keyword_group_says_which() -> None:
    score = score_report(_EXPECTED, "blocked", "minio.py uses the wrong key")
    assert score.missing_keywords == (("404", "not found"),) and not score.passed


# ---------------------------------------------------------------------------
# score_suite and launch_suite against the API's response shapes
# ---------------------------------------------------------------------------

_CASE = "binary-artifact-minio-key"
_PIN = "b2f680f00b4e154b94fa4802a92ead30429e7b98"


def _api(requests: list[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/evals":
            body = json.loads(request.content)
            pin = body["baseline_repos"][0]["requested_ref"]
            return httpx.Response(
                200,
                json={
                    "eval_id": f"eval-{pin[:6]}",
                    "name": body["name"],
                    "goal": body["goal"],
                    "starting_workflow_id": body["starting_workflow_id"],
                    "tags": body["tags"],
                    "baseline_repos": [
                        {
                            "repository": "syntropic137/syntropic137",
                            "requested_ref": pin,
                            "commit_sha": pin,
                        }
                    ],
                },
            )
        if request.method == "POST" and path.endswith("/execute"):
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "execution_id": f"exec-for-{body['eval_id']}",
                    "workflow_id": "eval-verify-pinned-v1",
                },
            )
        if path == "/evals":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "page": 1,
                    "page_size": 200,
                    "status_counts": {},
                    "evals": [
                        {
                            "eval_id": "eval-1",
                            "name": "n",
                            "goal": "g",
                            "starting_workflow_id": None,
                            "tags": ["verifier-seed-v1:v1", f"case:{_CASE}"],
                            "frozen": True,
                            "archived": False,
                            "created_at": None,
                            "updated_at": None,
                            "run_count": 1,
                            "run_status_counts": {"completed": 1},
                            "baseline_repos": [
                                {
                                    "repository": "syntropic137/syntropic137",
                                    "requested_ref": _PIN,
                                    "commit_sha": _PIN,
                                }
                            ],
                        }
                    ],
                },
            )
        if path == "/evals/eval-1/runs":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "page": 1,
                    "page_size": 200,
                    "executions": [
                        {
                            "workflow_execution_id": "exec-1",
                            "workflow_id": "eval-verify-pinned-v1",
                            "workflow_name": "w",
                            "status": "completed",
                        }
                    ],
                },
            )
        if path == "/executions/exec-1":
            return httpx.Response(
                200,
                json={
                    "workflow_execution_id": "exec-1",
                    "workflow_id": "eval-verify-pinned-v1",
                    "workflow_name": "w",
                    "status": "completed",
                    "review_verdict": "blocked",
                    "total_cost_usd": "3.75",
                    "total_duration_seconds": 640.2,
                    "unknown_duration_phase_count": 0,
                    "total_input_tokens": 1,
                    "total_output_tokens": 1,
                    "total_cache_creation_tokens": 0,
                    "total_cache_read_tokens": 0,
                    "total_tokens": 2,
                    "artifact_ids": ["art-1"],
                    "phases": [
                        {
                            "phase_id": "verify",
                            "name": "v",
                            "status": "completed",
                            "artifact_id": "art-1",
                            "model": "claude-opus-5-5",
                            "requested_model": "opus",
                        }
                    ],
                },
            )
        if path == "/artifacts/art-1/content":
            return httpx.Response(
                200,
                json={
                    "artifact_id": "art-1",
                    "content": _FINDING,
                    "content_type": "text/markdown",
                    "size_bytes": 10,
                },
            )
        return httpx.Response(404, json={"detail": path})

    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(handle))


def test_score_reads_verdict_report_cost_and_model_from_the_api() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    requests: list[httpx.Request] = []
    rows = score_suite(loaded, _api(requests))

    assert requests[0].url.params.get_list("tag") == ["verifier-seed-v1:v1"]
    scored = [r for r in rows if r.case == _CASE]
    assert len(scored) == 1
    row = scored[0]
    assert row.run_id == "exec-1"
    assert row.score is not None and row.score.verdict == "blocked" and row.score.passed
    assert row.cost_usd == Decimal("3.75")
    assert row.models == "verify=claude-opus-5-5"
    assert {r.status for r in rows if r.case != _CASE} == {"not launched"}

    table = render(loaded, rows)
    assert "exec-1" in table and "PASS" in table and "$3.75" in table and "1/4 passed" in table


def test_launch_pins_each_case_and_starts_its_run_in_that_eval() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    requests: list[httpx.Request] = []
    lines = launch_suite(loaded, _api(requests))

    creates = [json.loads(r.content) for r in requests if r.url.path == "/evals"]
    starts = [json.loads(r.content) for r in requests if r.url.path.endswith("/execute")]
    assert [c["baseline_repos"][0]["requested_ref"] for c in creates] == [
        c.commit for c in loaded.cases
    ]
    assert all("verifier-seed-v1:v1" in c["tags"] for c in creates)
    assert [s["eval_id"] for s in starts] == [f"eval-{c.commit[:6]}" for c in loaded.cases]
    assert all(
        r.url.path == "/workflows/eval-verify-pinned-v1/execute"
        for r in requests
        if r.method == "POST" and r.url.path != "/evals"
    )
    assert len(lines) == 4


def test_launch_stops_when_the_server_pins_another_commit() -> None:
    loaded = load_suite(DEFAULT_SUITE)

    def wrong_pin(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "eval_id": "e",
                "baseline_repos": [
                    {
                        "repository": "syntropic137/syntropic137",
                        "requested_ref": "x",
                        "commit_sha": "0" * 40,
                    }
                ],
            },
        )

    client = httpx.Client(base_url="http://api", transport=httpx.MockTransport(wrong_pin))
    with pytest.raises(RuntimeError, match="pinned"):
        launch_suite(loaded, client)


def test_a_run_that_reported_no_verdict_fails() -> None:
    assert not score_report(_EXPECTED, None, _FINDING).passed
