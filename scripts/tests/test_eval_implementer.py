"""Tests for scripts/eval_implementer.py and the implementer seed suite (#1725).

The checked-in suite is validated for real: it must parse, agree with the
workflow it names, and (on a full clone) pin each case at its fix's first
parent with every hidden test present at the fix and absent from what the
reference patch carries. Running the hidden tests is `admit`'s job, not this
file's: it builds a uv environment per case and takes minutes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import implementer_scorer
import yaml
from eval_implementer import (
    DEFAULT_SUITE,
    ROOT,
    ImplementerCase,
    asserted_contracts,
    check_commits,
    fix_patch,
    load_suite,
    main,
)
from eval_suite import DefinitionError
from implementer_scorer import _outcome_of, score_patch

pytestmark = pytest.mark.unit


def _full_clone() -> bool:
    shallow = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
    )
    return shallow.returncode == 0 and shallow.stdout.strip() == "false"


needs_history = pytest.mark.skipif(not _full_clone(), reason="needs the full git history")


def _copy_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    shutil.copytree(DEFAULT_SUITE, suite)
    return suite


def test_the_seed_suite_loads_against_its_workflow() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    assert loaded.suite.workflows[0].id == "eval-implement-pinned-v1"
    assert loaded.suite.workflows[0].models == {"implement": "opus"}
    assert len(loaded.cases) == 5


def test_the_workflow_writes_a_patch_and_delivers_no_repo_change() -> None:
    workflow = yaml.safe_load((ROOT / "workflows/evals/implement-pinned/workflow.yaml").read_text())
    (phase,) = workflow["phases"]
    assert phase["output_artifacts"] == ["patch"]
    assert phase["delivers_repo_changes"] is False


def test_a_model_change_without_the_suite_is_refused(tmp_path: Path) -> None:
    suite = _copy_suite(tmp_path)
    text = (suite / "suite.yaml").read_text().replace("implement: opus", "implement: sonnet")
    (suite / "suite.yaml").write_text(text)
    with pytest.raises(DefinitionError, match="the workflow declares"):
        load_suite(suite)


def test_a_task_that_names_the_fix_pr_is_refused(tmp_path: Path) -> None:
    suite = _copy_suite(tmp_path)
    case = suite / "cases" / "exec-status-lost.yaml"
    data = yaml.safe_load(case.read_text())
    data["task"] += f"\nSee #{data['source_pr']}."
    case.write_text(yaml.safe_dump(data))
    with pytest.raises(DefinitionError, match="could fetch the fix"):
        load_suite(suite)


def test_a_case_without_hidden_tests_is_refused(tmp_path: Path) -> None:
    suite = _copy_suite(tmp_path)
    case = suite / "cases" / "exec-status-lost.yaml"
    data = yaml.safe_load(case.read_text())
    data["hidden_tests"] = []
    case.write_text(yaml.safe_dump(data))
    with pytest.raises(DefinitionError, match="hidden_tests"):
        load_suite(suite)


@pytest.mark.parametrize(
    ("pytest_exit", "outcome"),
    [(0, "PASS"), (1, "FAIL"), (2, "FAIL"), (3, "ERROR"), (4, "ERROR"), (5, "ERROR")],
)
def test_pytest_exit_codes_map_to_a_verdict_on_the_change(pytest_exit: int, outcome: str) -> None:
    # 2 is a collection error: the environment was built at the pin before the
    # patch, so a hidden test that cannot import is the change's failure. 5 is
    # nothing collected, which says nothing about the change.
    assert _outcome_of(pytest_exit) == outcome


@needs_history
def test_every_case_is_pinned_at_its_fix_s_first_parent_with_its_hidden_tests() -> None:
    assert check_commits(load_suite(DEFAULT_SUITE), ROOT) == []


@needs_history
def test_a_pin_that_is_not_the_first_parent_is_reported() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    case = loaded.cases[0]
    wrong = loaded.model_copy(
        update={"cases": (case.model_copy(update={"commit": case.fix_commit}),)}
    )
    assert any("first parent" in p for p in check_commits(wrong, ROOT))


def test_a_hidden_test_s_exact_spellings_are_read_from_its_ast() -> None:
    found = asserted_contracts(
        "from syn_adapters.x import status_was_lost, RetryPolicy\n"
        "from os import path\n"
        "class _Double:\n"
        "    def mkdir(self): ...\n"
        "def test(monkeypatch, caplog):\n"
        "    monkeypatch.setattr(mod, 'container_state', f)\n"
        "    with pytest.raises(E, match=r'could not create TMPDIR\\.') as raised:\n"
        "        pass\n"
        "    assert raised.value.unsettled == 1\n"
        "    _Double().mkdir()\n"
        "    double.calls = []\n"
        "    assert double.calls\n"
        "    assert 'Could not destroy workspace' in caplog.text\n"
        "    assert 'printed nothing' not in text\n"
        "    assert x == 'not a contract'\n"
    )
    assert found.names == {"status_was_lost", "RetryPolicy", "container_state"}
    # `not in` is satisfied by never printing the text, so it needs no statement
    assert found.literals == {"could not create TMPDIR.", "Could not destroy workspace"}
    # what the test defines itself (mkdir, calls) is not a contract on the fix
    assert {"unsettled", "value", "text"} <= found.attributes
    assert not {"mkdir", "calls"} & found.attributes


def test_a_monkeypatch_target_is_read_as_the_module_or_object_it_patches() -> None:
    found = asserted_contracts(
        "from syn_adapters.github import client_retry\n"
        "from syn_adapters.github.client import GitHubAppClient as Client\n"
        "import syn_shared.settings as settings\n"
        "def test(monkeypatch, local):\n"
        "    monkeypatch.setattr(client_retry, '_now', lambda: 0.0)\n"
        "    monkeypatch.setattr(Client, '_generate_jwt', lambda _self: 'jwt')\n"
        "    monkeypatch.setattr(settings, 'reset', lambda: None)\n"
        "    monkeypatch.setattr('syn_adapters.github.GitHubAppClient', object)\n"
        "    monkeypatch.setattr(local, 'helper', None)\n"
        "    monkeypatch.setattr('os.path.join', None)\n"
    )
    assert found.patched == {
        ("syn_adapters.github.client_retry", "_now"),
        ("syn_adapters.github.client.GitHubAppClient", "_generate_jwt"),
        ("syn_shared.settings", "reset"),
        ("syn_adapters.github", "GitHubAppClient"),
    }


def test_a_monkeypatch_target_reached_by_attribute_chain_is_resolved() -> None:
    """Codex on #2019: a plain `import a.b.c` target was unresolved, so the check fell
    back to a tree-wide name match and `_now` in an unrelated module passed it."""
    found = asserted_contracts(
        "import syn_adapters.github.client_retry\n"
        "import syn_adapters.github as gh\n"
        "import os.path\n"
        "def test(monkeypatch):\n"
        "    monkeypatch.setattr(syn_adapters.github.client_retry, '_now', lambda: 0.0)\n"
        "    monkeypatch.setattr(gh.client.GitHubAppClient, '_generate_jwt', None)\n"
        "    monkeypatch.setattr(os.path, 'join', None)\n"
    )
    assert found.patched == {
        ("syn_adapters.github.client_retry", "_now"),
        ("syn_adapters.github.client.GitHubAppClient", "_generate_jwt"),
    }


@needs_history
def test_a_fixture_that_patches_a_name_only_the_fix_defines_is_reported() -> None:
    """E2: `_now` appeared at the pin only in unrelated apps/syn-api tests, so a tree-wide
    grep passed it while every token-mint test errored at setup in both arms."""
    loaded = load_suite(DEFAULT_SUITE)
    case = loaded.case("token-mint-retry-5xx")
    stated = "`client_retry._now() -> float`"
    assert stated in case.task
    unstated = loaded.model_copy(
        update={"cases": (case.model_copy(update={"task": case.task.replace(stated, "a clock")}),)}
    )
    problems = check_commits(unstated, ROOT)
    assert [p for p in problems if "monkeypatches" in p] == [
        "token-mint-retry-5xx: packages/syn-adapters/tests/github/test_provisioning_retry.py"
        " monkeypatches syn_adapters.github.client_retry._now, which the pin does not define"
        " and the task never states"
    ], "patch targets that exist at the pin (_generate_jwt, delay_after, ...) are not reported"


@needs_history
def test_an_attribute_the_hidden_tests_read_but_the_task_never_states_is_reported() -> None:
    """`unsettled` existed at the pin only as an unrelated local variable, so a word match passed it."""
    loaded = load_suite(DEFAULT_SUITE)
    case = loaded.case("pause-not-blocked-by-queue")
    stated = "That error has an `unsettled` attribute"
    assert stated in case.task
    unstated = loaded.model_copy(
        update={"cases": (case.model_copy(update={"task": case.task.replace(stated, "It")}),)}
    )
    problems = check_commits(unstated, ROOT)
    assert any("reads attribute 'unsettled'" in p for p in problems)
    assert not any("'_run_exec'" in p for p in problems), "submodule attributes are searched"


@needs_history
def test_an_unsearchable_submodule_makes_the_attribute_check_incomplete_not_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing submodule clone once counted every attribute as present (codex, #2019)."""
    loaded = load_suite(DEFAULT_SUITE)
    case = loaded.case("pause-not-blocked-by-queue")
    stated = "That error has an `unsettled` attribute"
    unstated = loaded.model_copy(
        update={"cases": (case.model_copy(update={"task": case.task.replace(stated, "It")}),)}
    )
    real_exists = Path.exists

    def no_submodule_clone(path: Path) -> bool:
        if path.name == ".git" and path.parent != ROOT:
            return False
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", no_submodule_clone)
    problems = check_commits(unstated, ROOT)
    assert any("could not be searched" in p and "unsettled" in p for p in problems), problems


@needs_history
def test_a_name_the_hidden_tests_need_but_the_task_never_states_is_reported() -> None:
    """#2023: exec-status-lost's tests monkeypatch `container_state`, which no pin defines."""
    loaded = load_suite(DEFAULT_SUITE)
    case = loaded.case("exec-status-lost")
    stated = "`exec_status_lost.container_state(container_name: str) -> str`"
    assert stated in case.task
    unstated = loaded.model_copy(
        update={"cases": (case.model_copy(update={"task": case.task.replace(stated, "a helper")}),)}
    )
    assert any("'container_state'" in p for p in check_commits(unstated, ROOT))


@needs_history
def test_a_message_the_hidden_tests_assert_but_the_task_never_states_is_reported() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    case = loaded.case("codex-sandbox-tmpdir")
    unstated = loaded.model_copy(
        update={
            "cases": (
                case.model_copy(
                    update={"task": case.task.replace("Could not destroy workspace", "an error")}
                ),
            )
        }
    )
    assert any("'Could not destroy workspace'" in p for p in check_commits(unstated, ROOT))


@needs_history
@pytest.mark.parametrize("case", load_suite(DEFAULT_SUITE).cases, ids=lambda c: c.id)
def test_the_reference_patch_leaves_the_hidden_tests_out(case: ImplementerCase) -> None:
    patch = fix_patch(case, ROOT)
    touched = {
        line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git ")
    }
    assert touched, f"{case.id}: the fix changed nothing but its hidden tests"
    assert touched.isdisjoint(case.hidden_tests)


@needs_history
def test_check_passes_on_the_checked_in_suite(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check"]) == 0
    assert "5 case(s) OK" in capsys.readouterr().out


def _new_file(path: str, *lines: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
        + "".join(f"+{line}\n" for line in lines)
    )


def _addopts(opts: str) -> str:
    """A patch adding `addopts` to the tiny repository's pytest configuration."""
    return (
        "diff --git a/pyproject.toml b/pyproject.toml\n--- a/pyproject.toml\n"
        "+++ b/pyproject.toml\n@@ -1,2 +1,3 @@\n [tool.pytest.ini_options]\n"
        f' pythonpath = ["."]\n+addopts = "{opts}"\n'
    )


def _plugin(*body: str) -> str:
    """The bug left in place, and a pytest plugin outside any conftest loaded by config."""
    return _new_file("hooks.py", "import pytest", *body) + _addopts("-p hooks")


def _conftest(*body: str) -> str:
    return _new_file("tests/conftest.py", "import pytest", *body)


def _mark_second(mark: str) -> tuple[str, ...]:
    return (
        "def pytest_collection_modifyitems(items):",
        "    for item in items:",
        "        if item.name == 'test_second':",
        f"            item.add_marker(pytest.mark.{mark}(reason='bug untouched'))",
    )


_SKIP_ALL = (
    "def pytest_collection_modifyitems(items):",
    "    for item in items:",
    "        item.add_marker(pytest.mark.skip(reason='bug untouched'))",
)
_REPORT_PASSED = (
    "@pytest.hookimpl(hookwrapper=True)",
    "def pytest_runtest_makereport(item, call):",
    "    outcome = yield",
    "    outcome.get_result().outcome = 'passed'",
)


@pytest.fixture
def two_hidden_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ImplementerCase, Path]:
    """A repository whose fix adds two hidden files: one passes at the pin, one catches the bug.

    The real worktree, `git apply` and pytest subprocess run; only the uv
    environment is this interpreter's, so the test needs no lockfile or network.
    """
    monkeypatch.setattr(implementer_scorer, "SYNC", ("true",))
    monkeypatch.setattr(implementer_scorer, "PYTEST", (sys.executable, "-m", "pytest"))
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "--quiet")
    git("config", "user.name", "eval test")
    git("config", "user.email", "eval@example.invalid")
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (repo / "bug.py").write_text("value = 0\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "pin")
    pin = git("rev-parse", "HEAD")
    (repo / "tests").mkdir()
    (repo / "tests/test_first.py").write_text("def test_first():\n    assert True\n")
    (repo / "tests/test_second.py").write_text(
        "from bug import value\n\ndef test_second():\n    assert value == 1\n"
    )
    (repo / "bug.py").write_text("value = 1\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "fix")
    case = ImplementerCase(
        id="two-hidden-files",
        source_pr=1,
        commit=pin,
        fix_commit=git("rev-parse", "HEAD"),
        task="value must be one",
        hidden_tests=("tests/test_first.py", "tests/test_second.py"),
    )
    return case, repo


def test_scoring_in_a_worktree_never_writes_the_shared_submodule_config(
    two_hidden_files: tuple[ImplementerCase, Path], tmp_path: Path
) -> None:
    """Admit in a scratch worktree once repointed every checkout's submodule URLs at it."""
    case, repo = two_hidden_files

    def git(at: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(at), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    lib = tmp_path / "lib-origin"
    lib.mkdir()
    git(lib, "init", "--quiet")
    git(
        lib,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "--quiet",
        "--allow-empty",
        "-m",
        "lib",
    )
    git(
        repo, "-c", "protocol.file.allow=always", "submodule", "add", "--quiet", str(lib), "lib/dep"
    )
    git(repo, "commit", "--quiet", "-m", "add submodule")
    pinned = case.model_copy(update={"commit": git(repo, "rev-parse", "HEAD")})
    before = git(repo, "config", "--get-regexp", "submodule")

    with implementer_scorer._worktree(repo, pinned.commit) as tree:
        assert git(tree / "lib/dep", "rev-parse", "HEAD") == git(lib, "rev-parse", "HEAD")

    assert git(repo, "config", "--get-regexp", "submodule") == before


def test_the_bug_left_in_place_fails_and_the_fix_passes(
    two_hidden_files: tuple[ImplementerCase, Path],
) -> None:
    case, repo = two_hidden_files
    assert score_patch(case.pin(), "", repo).outcome == "FAIL"
    fixed = score_patch(case.pin(), fix_patch(case, repo), repo)
    assert fixed.outcome == "PASS", fixed.detail


@pytest.mark.parametrize(
    "patch",
    [
        _plugin(*_SKIP_ALL),
        _plugin(*_mark_second("skip")),
        _plugin(*_mark_second("xfail")),
        _addopts("--deselect tests/test_second.py::test_second"),
        _conftest(*_SKIP_ALL),
        _conftest(*_mark_second("skip")),
        _conftest(*_REPORT_PASSED),
    ],
    ids=[
        "plugin-skip-all",
        "plugin-skip-second",
        "plugin-xfail-second",
        "addopts-deselect-second",
        "conftest-skip-all",
        "conftest-skip-second",
        "conftest-report-passed",
    ],
)
def test_a_change_that_hides_the_bug_from_pytest_is_not_a_pass(
    two_hidden_files: tuple[ImplementerCase, Path], patch: str
) -> None:
    # Every one of these leaves the bug in place and, unchecked, exits pytest 0.
    case, repo = two_hidden_files
    run = score_patch(case.pin(), patch, repo)
    assert run.outcome == "FAIL", run.detail
    assert "test_second" in run.detail


def test_a_fix_plus_a_harmless_conftest_still_passes(
    two_hidden_files: tuple[ImplementerCase, Path],
) -> None:
    case, repo = two_hidden_files
    run = score_patch(case.pin(), fix_patch(case, repo) + _conftest("FIXTURE = 1"), repo)
    assert run.outcome == "PASS", run.detail


@pytest.fixture
def prepared(
    two_hidden_files: tuple[ImplementerCase, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ImplementerCase, Path, Path]:
    """`prepare` on the two-file repository, with SYNC building the environment it checks for."""
    case, repo = two_hidden_files
    monkeypatch.setattr(implementer_scorer, "SYNC", ("mkdir", "-p", implementer_scorer.ENVIRONMENT))
    out = tmp_path / "prepared"
    assert implementer_scorer.prepare(case.pin(), repo, out) is None
    return case, repo, out


def test_a_prepared_tree_scores_the_fix_pass_and_the_bug_fail(
    prepared: tuple[ImplementerCase, Path, Path], tmp_path: Path
) -> None:
    case, repo, out = prepared
    fixed = implementer_scorer.score_prepared(out, fix_patch(case, repo))
    assert fixed.outcome == "PASS", fixed.detail
    again = tmp_path / "again"
    assert implementer_scorer.prepare(case.pin(), repo, again) is None
    assert implementer_scorer.score_prepared(again, "").outcome == "FAIL"


def test_a_prepared_tree_without_its_environment_is_error_never_a_sync(
    prepared: tuple[ImplementerCase, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    case, repo, out = prepared
    (out / "tree" / implementer_scorer.ENVIRONMENT).rmdir()
    synced: list[str] = []
    monkeypatch.setattr(implementer_scorer, "_run", lambda *a: synced.append(a[2]))
    run = implementer_scorer.score_prepared(out, fix_patch(case, repo))
    assert run.outcome == "ERROR"
    assert "never syncs" in run.detail
    assert synced == []


def test_a_prepared_tree_scores_one_patch_only(
    prepared: tuple[ImplementerCase, Path, Path],
) -> None:
    case, repo, out = prepared
    assert implementer_scorer.score_prepared(out, "").outcome == "FAIL"
    second = implementer_scorer.score_prepared(out, fix_patch(case, repo))
    assert second.outcome == "ERROR"
    assert "already scored" in second.detail


def test_prepare_refuses_a_directory_that_is_not_empty(
    two_hidden_files: tuple[ImplementerCase, Path], tmp_path: Path
) -> None:
    case, repo = two_hidden_files
    out = tmp_path / "used"
    out.mkdir()
    (out / "left-over").write_text("")
    failed = implementer_scorer.prepare(case.pin(), repo, out)
    assert failed is not None
    assert failed.outcome == "ERROR"


def test_the_scorer_cli_ends_with_a_result_line_matching_its_exit(
    prepared: tuple[ImplementerCase, Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case, repo, out = prepared
    patch = tmp_path / "fix.patch"
    patch.write_text(fix_patch(case, repo))
    code = implementer_scorer.main(["score", "--prepared", str(out), "--patch", str(patch)])
    assert code == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "RESULT: PASS"
