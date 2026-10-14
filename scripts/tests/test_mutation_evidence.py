"""Tests for the mutation-evidence runner.

The runner's product is a verdict an agent will cite, so the failure modes that
matter are the ones that turn a non-result into a kill: an input that smuggles
shell or pytest options, a patch that changed nothing, a patch that mutated a
test (by name, by symlink, or through an ignored path), a red baseline, an
interrupt read as a failure, a tree left dirty for the next patch. Each is
driven against a real git repository; only the pytest call is replaced, by a
runner that fails exactly when the source file differs from HEAD.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import pytest
from scripts import mutation_evidence as me
from scripts.mutation_evidence import (
    MARKER,
    Evidence,
    InputError,
    Inputs,
    Outcome,
    PatchResult,
    PytestRun,
    Sandbox,
    changed_paths,
    classify,
    evaluate_patch,
    execute,
    forbidden_reason,
    inputs_from_env,
    parse_inputs,
    parse_mutations_dir,
    parse_numstat,
    parse_pytest_output,
    parse_tests,
    render,
    restore,
)

pytestmark = pytest.mark.unit

SHA = "a" * 40
ORIGINAL = "def add(a, b):\n    return a + b\n"
TEST_ID = "pkg/tests/test_mod.py::test_add"


# --------------------------------------------------------------------------
# Input validation: the injection surface
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node_id",
    [
        "scripts/tests/test_x.py",
        "scripts/tests/test_x.py::test_y",
        "a/b/test_x.py::TestC::test_y",
        "a/test_x.py::test_y[case-1]",
        "a/test_x.py::test_y[a.b,c=d+e]",
    ],
)
def test_accepts_plain_node_ids(node_id: str) -> None:
    assert parse_tests(node_id) == (node_id,)


@pytest.mark.parametrize(
    "node_id",
    [
        "-p",
        "--rootdir=/",
        "a/test_x.py;rm",
        "a/test_x.py::test_y$(id)",
        "a/test_x.py::test_`id`",
        "../outside/test_x.py",
        "/abs/test_x.py",
        "a/../../test_x.py",
        "a/-x/test_x.py",
        "a/test_x.txt",
        "a/test_x.py::test_y[a b]",
        "a/test_x.py::test_y[$(id)]",
        "a//test_x.py",
    ],
)
def test_rejects_unsafe_node_ids(node_id: str) -> None:
    with pytest.raises(InputError):
        parse_tests(node_id)


def test_rejects_empty_and_too_many_tests() -> None:
    with pytest.raises(InputError):
        parse_tests("   ")
    with pytest.raises(InputError):
        parse_tests(" ".join(f"t/test_{i}.py" for i in range(me.MAX_TESTS + 1)))


@pytest.mark.parametrize(
    "raw", [".mutations/", ".mutations", ".mutations/pr-12", ".mutations/a/b/"]
)
def test_accepts_mutation_dirs_under_the_root(raw: str) -> None:
    assert parse_mutations_dir(raw) == PurePosixPath(raw.rstrip("/"))


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "/",
        "/etc",
        "..",
        "../x",
        ".",
        ".git",
        "-x",
        "a b",
        "a;b",
        "$(id)",
        # Outside .mutations/: ci.yml mutations-not-merged would not see them.
        "evidence",
        "src/x",
        ".mutationsx",
        ".mutations/../src",
    ],
)
def test_rejects_mutation_dirs_that_escape(raw: str) -> None:
    with pytest.raises(InputError):
        parse_mutations_dir(raw)


@pytest.mark.parametrize("raw", ["0", "-1", "1e3", "abc", "1;2", ""])
def test_rejects_bad_pr_numbers(raw: str) -> None:
    with pytest.raises(InputError):
        parse_inputs(raw, "a/test_x.py", ".mutations")


def test_dispatch_id_is_validated() -> None:
    env = {"MUTATION_PR": "7", "MUTATION_TESTS": "a/test_x.py", "MUTATION_DIR": ".mutations/"}
    assert inputs_from_env({**env, "MUTATION_DISPATCH_ID": "ab-12"}).pr == 7
    with pytest.raises(InputError):
        inputs_from_env({**env, "MUTATION_DISPATCH_ID": "a b$(id)"})


# --------------------------------------------------------------------------
# What a mutation may touch, by name
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "pkg/tests/helper.py",
        "pkg/test/x.py",
        "pkg/test_mod.py",
        "pkg/mod_test.py",
        "pkg/conftest.py",
        "pyproject.toml",
        "apps/a/pyproject.toml",
        "uv.lock",
        ".github/workflows/ci.yml",
        "ci/fitness/x.py",
        "lib/event-sourcing-platform/x.py",
        ".mutations/other.patch",
    ],
)
def test_forbids_tests_config_and_infra(path: str) -> None:
    assert forbidden_reason(path, PurePosixPath(".mutations")) is not None


@pytest.mark.parametrize("path", ["pkg/mod.py", "apps/syn-api/src/x/testing_utils.py", "README.md"])
def test_allows_source(path: str) -> None:
    assert forbidden_reason(path, PurePosixPath(".mutations")) is None


def test_numstat_names_both_sides_of_a_rename() -> None:
    out = "1\t1\tpkg/a.py\x000\t0\t\x00pkg/old.py\x00pkg/new.py\x00-\t-\tbin.dat\x00"
    assert parse_numstat(out) == ["bin.dat", "pkg/a.py", "pkg/new.py", "pkg/old.py"]


# --------------------------------------------------------------------------
# pytest output and exit codes
# --------------------------------------------------------------------------


def test_parses_failing_ids_and_passed_count() -> None:
    out = (
        "..F\n=== short test summary info ===\n"
        "FAILED a/test_x.py::test_y - AssertionError: no\n"
        "ERROR a/test_x.py::test_z - ImportError\n"
        "FAILED a/test_x.py::test_y - again\n"
        "1 failed, 2 passed, 1 error in 0.1s\n"
    )
    assert parse_pytest_output(out) == (("a/test_x.py::test_y", "a/test_x.py::test_z"), 2)


@pytest.mark.parametrize(
    ("code", "failing", "outcome"),
    [
        (0, (), Outcome.SURVIVED),
        (1, ("a/test_x.py::t",), Outcome.KILLED),
        (2, ("a/test_x.py",), Outcome.KILLED),
        # Exit 2 with nothing on record is an interrupt, not a kill.
        (2, (), Outcome.ERROR),
        (1, (), Outcome.ERROR),
        (4, (), Outcome.ERROR),
        (5, (), Outcome.ERROR),
        (-1, (), Outcome.ERROR),
    ],
)
def test_classifies_exit_codes(code: int, failing: tuple[str, ...], outcome: Outcome) -> None:
    assert classify(PytestRun(code, failing, 0, 0.0)) is outcome


# --------------------------------------------------------------------------
# The sandbox command
# --------------------------------------------------------------------------


def test_sandbox_mounts_git_read_only_and_forwards_only_listed_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_EVENTSTORE_PORT", "55051")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_" + "x" * 8)
    cmd = Sandbox("img@sha256:" + "0" * 64).command(tmp_path, ["uv", "sync"])

    joined = " ".join(cmd)
    assert f"{tmp_path.resolve() / '.git'}:/work/.git:ro" in joined
    assert "TEST_EVENTSTORE_PORT=55051" in joined
    assert "GITHUB_TOKEN" not in joined
    assert "/var/run/docker.sock" not in joined
    assert cmd[-2:] == ["uv", "sync"]


# --------------------------------------------------------------------------
# The run, against a real git repository
# --------------------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _diff_patch(root: Path, path: str, new: str) -> str:
    """A real `git diff` of one edit, then the edit reverted."""
    target = root / path
    old = target.read_text()
    target.write_text(new)
    patch = subprocess.run(
        ["git", "diff"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    target.write_text(old)
    return patch


def _new_file_patch(path: str, content: str) -> str:
    lines = content.splitlines()
    body = "".join(f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n"
        f"+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}"
    )


def _commit_patch(root: Path, name: str, text: str) -> Path:
    patch = root / ".mutations" / name
    patch.write_text(text)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", name)
    return patch


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg" / "tests").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text(ORIGINAL)
    (root / "pkg" / "other.py").write_text("X = 1\n")
    (root / "pkg" / "tests" / "test_mod.py").write_text("def test_add():\n    assert True\n")
    (root / "checks").mkdir()
    (root / "checks" / "spec.py").write_text("def test_guard():\n    assert True\n")
    (root / ".gitignore").write_text("build/\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "source")
    muts = root / ".mutations"
    muts.mkdir()
    (muts / "01-kill.patch").write_text(_diff_patch(root, "pkg/mod.py", ORIGINAL.replace("+", "-")))
    (muts / "02-survive.patch").write_text(_diff_patch(root, "pkg/other.py", "X = 2\n"))
    (muts / "03-test.patch").write_text(
        _diff_patch(root, "pkg/tests/test_mod.py", "def test_add():\n    assert False\n")
    )
    stale = _diff_patch(root, "pkg/mod.py", "def add(a, b):\n    return 0\n")
    (muts / "04-stale.patch").write_text(stale.replace("return a + b", "return a * b"))
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "patches")
    return root


def _runner_sensitive_to_mod(root: Path, tests: tuple[str, ...]) -> PytestRun:
    if (root / "pkg" / "mod.py").read_text() == ORIGINAL:
        return PytestRun(0, (), len(tests), 0.01)
    return PytestRun(1, tests, 0, 0.02)


def _inputs(*tests: str) -> Inputs:
    return Inputs(pr=7, tests=tests or (TEST_ID,), mutations_dir=PurePosixPath(".mutations"))


def test_full_run_classifies_each_patch_and_leaves_tree_clean(repo: Path) -> None:
    evidence = execute(repo, _inputs(), SHA, _runner_sensitive_to_mod)

    by_patch = {r.patch: r for r in evidence.results}
    assert by_patch["01-kill.patch"].outcome is Outcome.KILLED
    assert by_patch["01-kill.patch"].files == ("pkg/mod.py",)
    assert by_patch["01-kill.patch"].failing == (TEST_ID,)
    assert by_patch["02-survive.patch"].outcome is Outcome.SURVIVED
    assert by_patch["03-test.patch"].outcome is Outcome.REFUSED
    assert by_patch["04-stale.patch"].outcome is Outcome.APPLY_FAILED
    assert not evidence.ok
    assert changed_paths(repo) == []
    assert (repo / "pkg" / "mod.py").read_text() == ORIGINAL


def test_all_killed_is_ok(repo: Path) -> None:
    for name in ("02-survive.patch", "03-test.patch", "04-stale.patch"):
        _git(repo, "rm", "-q", f".mutations/{name}")
    _git(repo, "commit", "-q", "-m", "only the killer")

    evidence = execute(repo, _inputs(), SHA, _runner_sensitive_to_mod)

    assert [r.outcome for r in evidence.results] == [Outcome.KILLED]
    assert evidence.ok


def test_red_baseline_voids_the_evidence(repo: Path) -> None:
    def red(root: Path, tests: tuple[str, ...]) -> PytestRun:
        return PytestRun(1, tests, 0, 0.0)

    evidence = execute(repo, _inputs(), SHA, red)

    assert "evidence void" in evidence.baseline_detail
    assert evidence.results == []
    assert not evidence.ok


def test_zero_test_baseline_voids_the_evidence(repo: Path) -> None:
    def empty(root: Path, tests: tuple[str, ...]) -> PytestRun:
        return PytestRun(0, (), 0, 0.0)

    evidence = execute(repo, _inputs(), SHA, empty)

    assert "zero tests" in evidence.baseline_detail
    assert not evidence.ok


def test_empty_patch_is_never_a_kill(repo: Path) -> None:
    patch = _commit_patch(repo, "05-noop.patch", "")
    result = evaluate_patch(repo, patch, _inputs(), _runner_sensitive_to_mod)
    restore(repo)
    assert result.outcome in {Outcome.NOT_APPLIED, Outcome.APPLY_FAILED}


def test_patch_adding_an_ignored_file_is_refused(repo: Path) -> None:
    # Source edit plus an ignored test: the old check saw only the source.
    text = _diff_patch(repo, "pkg/mod.py", ORIGINAL.replace("+", "-"))
    text += _new_file_patch("build/plugin.py", "raise SystemExit(1)")
    patch = _commit_patch(repo, "05-ignored.patch", text)

    result = evaluate_patch(repo, patch, _inputs(), _runner_sensitive_to_mod)
    restore(repo)

    assert result.outcome is Outcome.REFUSED
    assert "git-ignored" in result.detail
    assert not (repo / "build").exists()


def test_rename_out_of_an_ignored_path_is_refused(repo: Path) -> None:
    # numstat names only `pkg/disabled.py`; the ignored source would vanish
    # unvetted and could break an import the named tests rely on.
    (repo / "build").mkdir()
    (repo / "build" / "dep.py").write_text("VALUE = 1\n")
    text = (
        "diff --git a/build/dep.py b/pkg/disabled.py\nsimilarity index 100%\n"
        "rename from build/dep.py\nrename to pkg/disabled.py\n"
    )
    patch = _commit_patch(repo, "05-rename.patch", text)

    result = evaluate_patch(repo, patch, _inputs(), _runner_sensitive_to_mod)
    restore(repo)

    assert result.outcome is Outcome.REFUSED
    assert "renames" in result.detail
    assert (repo / "build" / "dep.py").read_text() == "VALUE = 1\n"


def test_patch_of_a_named_test_with_an_unconventional_name_is_refused(repo: Path) -> None:
    text = _diff_patch(repo, "checks/spec.py", "def test_guard():\n    assert False\n")
    patch = _commit_patch(repo, "05-spec.patch", text)

    result = evaluate_patch(
        repo, patch, _inputs("checks/spec.py::test_guard"), _runner_sensitive_to_mod
    )
    restore(repo)

    assert result.outcome is Outcome.REFUSED
    assert "named test file" in result.detail


def test_patch_through_a_symlink_is_refused(repo: Path) -> None:
    (repo / "pkg" / "alias.py").symlink_to("tests/test_mod.py")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "alias")
    text = (
        "diff --git a/pkg/alias.py b/pkg/alias.py\n--- a/pkg/alias.py\n+++ b/pkg/alias.py\n"
        "@@ -1 +1 @@\n-tests/test_mod.py\n\\ No newline at end of file\n+pkg/mod.py\n"
        "\\ No newline at end of file\n"
    )
    patch = _commit_patch(repo, "05-link.patch", text)

    result = evaluate_patch(repo, patch, _inputs(), _runner_sensitive_to_mod)
    restore(repo)

    assert result.outcome is Outcome.REFUSED
    assert "symlink" in result.detail


def test_interrupt_is_an_error_not_a_kill(repo: Path) -> None:
    def interrupted(root: Path, tests: tuple[str, ...]) -> PytestRun:
        if (root / "pkg" / "mod.py").read_text() == ORIGINAL:
            return PytestRun(0, (), 1, 0.0)
        return PytestRun(2, (), 0, 0.0)

    evidence = execute(repo, _inputs(), SHA, interrupted)

    assert evidence.results[0].outcome is Outcome.ERROR
    assert not evidence.ok


def test_baseline_byproducts_are_not_charged_to_the_first_patch(repo: Path) -> None:
    def messy(root: Path, tests: tuple[str, ...]) -> PytestRun:
        (root / "pkg" / "tests" / "artifact.txt").write_text("left behind")
        return _runner_sensitive_to_mod(root, tests)

    evidence = execute(repo, _inputs(), SHA, messy)

    assert evidence.results[0].files == ("pkg/mod.py",)
    assert evidence.results[0].outcome is Outcome.KILLED


def test_dirty_tree_before_baseline_refuses(repo: Path) -> None:
    (repo / "pkg" / "mod.py").write_text("dirty\n")
    with pytest.raises(RuntimeError, match="dirty"):
        execute(repo, _inputs(), SHA, _runner_sensitive_to_mod)


def test_missing_test_file_and_dir_refuse(repo: Path) -> None:
    with pytest.raises(InputError, match="does not exist"):
        execute(repo, _inputs("pkg/tests/test_nope.py"), SHA, _runner_sensitive_to_mod)
    missing_dir = Inputs(7, (TEST_ID,), PurePosixPath(".mutations/nope"))
    with pytest.raises(InputError, match="does not exist"):
        execute(repo, missing_dir, SHA, _runner_sensitive_to_mod)


def test_symlinked_mutations_dir_cannot_escape(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".mutations" / "escape").symlink_to(outside)
    escaping = Inputs(7, (TEST_ID,), PurePosixPath(".mutations/escape"))
    with pytest.raises(InputError, match="outside"):
        execute(repo, escaping, SHA, _runner_sensitive_to_mod)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def test_report_has_marker_table_and_neutralised_cells() -> None:
    evidence = Evidence(pr=7, sha=SHA, tests=(TEST_ID,), baseline=PytestRun(0, (), 1, 1.0))
    evidence.results = [
        PatchResult("01.patch", Outcome.KILLED, ("pkg/mod.py",), ("a|b`@x",), 2.0),
        PatchResult("02.patch", Outcome.SURVIVED, ("pkg/other.py",), (), 3.0),
        PatchResult("03.patch", Outcome.ERROR, detail="[click](https://evil.invalid) <img>"),
    ]

    text = render(evidence, "https://example.invalid/run/1")

    assert text.startswith(MARKER)
    assert "| `01.patch` | `pkg/mod.py` | killed |" in text
    assert "SURVIVED" in text
    assert "**FAIL**" in text
    assert "a\\|b'@​x" in text
    assert "`a|b" not in text
    # Detail text from PR code renders inside a code span, never as a link.
    assert "ERROR `[click](https://evil.invalid) <img>`" in text
