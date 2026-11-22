"""The container referee on real Docker and the pinned workspace image (#2108 S4).

Plan section 12, S4: the reference fix PASSes and the empty patch FAILs through
the container path, a patch that needs the network to pass FAILs, and a sync
attempt offline is ERROR. The subject is a tiny uv project whose lockfile pins
the pytest this repository runs, so `prepare` really syncs over the network and
`score --prepared` really runs with none.

Set SYN_EVAL_REFEREE_TEST_IMAGE to try another image; the default is the pinned
claude-cli workspace image, the one the referee uses.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import implementer_scorer
from eval_implementer import ImplementerCase
from eval_referee import _WORK, docker_cli, referee_score, score_case
from eval_suite import ROOT

from syn_shared.settings.workspace_images import WorkspaceImageProvider, workspace_image_ref

pytestmark = pytest.mark.integration


@pytest.fixture
def docker_present() -> None:
    """Fail, never skip, without Docker: a skip here would report nothing (#1984)."""
    assert shutil.which("docker"), "the container referee tests need Docker on PATH"


IMAGE = os.environ.get(
    "SYN_EVAL_REFEREE_TEST_IMAGE", workspace_image_ref(WorkspaceImageProvider.CLAUDE_CLI)
)
SCORER_COMMIT = subprocess.run(
    ["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--", "scripts/implementer_scorer.py"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()

NETWORK_PATCH = """\
diff --git a/bug.py b/bug.py
--- a/bug.py
+++ b/bug.py
@@ -1 +1,3 @@
-value = 0
+import urllib.request
+
+value = 1 if urllib.request.urlopen("https://pypi.org/simple/", timeout=20).status == 200 else 0
"""


def _git(at: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(at), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture(scope="module")
def subject(tmp_path_factory: pytest.TempPathFactory) -> tuple[ImplementerCase, Path]:
    """A locked uv project: a pin with the bug, a fix with the hidden test that catches it."""
    repo = tmp_path_factory.mktemp("subject")
    _git(repo, "init", "--quiet")
    (repo / "pyproject.toml").write_text(
        "[project]\n"
        'name = "subject"\n'
        'version = "0"\n'
        'requires-python = ">=3.12"\n'
        f'dependencies = ["pytest=={version("pytest")}", "pytest-xdist=={version("pytest-xdist")}"]\n'
        "[tool.uv]\n"
        "package = false\n"
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["."]\n'
    )
    (repo / ".gitignore").write_text(".venv/\n")
    (repo / "bug.py").write_text("value = 0\n")
    subprocess.run(["uv", "lock", "--quiet"], cwd=repo, check=True)
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "pin")
    pin = _git(repo, "rev-parse", "HEAD")
    (repo / "tests").mkdir()
    (repo / "tests/test_value.py").write_text(
        "from bug import value\n\n\ndef test_value():\n    assert value == 1\n"
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


def test_the_network_patch_passes_where_the_network_is_on(
    subject: tuple[ImplementerCase, Path],
) -> None:
    """The positive half: without this, its FAIL in the container could be any bug."""
    case, repo = subject
    run = implementer_scorer.score_patch(case.pin(), NETWORK_PATCH, repo)
    assert run.outcome == "PASS", run.detail


@pytest.mark.usefixtures("docker_present")
def test_the_controls_hold_and_a_patch_that_needs_the_network_fails(
    subject: tuple[ImplementerCase, Path],
) -> None:
    case, repo = subject
    controls, scored = score_case(
        case, [("network", NETWORK_PATCH)], repo=repo, scorer_commit=SCORER_COMMIT, image=IMAGE
    )
    assert [c.run.outcome for c in controls] == ["PASS", "FAIL"], [c.run.detail for c in controls]
    (network,) = scored
    assert network.run.outcome == "FAIL", network.run.detail
    assert "URLError" in network.run.detail or "urlopen" in network.run.detail


@pytest.mark.usefixtures("docker_present")
def test_a_sync_attempt_offline_is_error(subject: tuple[ImplementerCase, Path]) -> None:
    """The prepared environment disappears once the network is cut: score must not rebuild it."""
    case, repo = subject

    def drop_the_environment(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        ran = docker_cli(args, timeout)
        if args[:2] == ["network", "disconnect"] and ran.returncode == 0:
            venv = f"{_WORK}/prepared/tree/{implementer_scorer.ENVIRONMENT}"
            docker_cli(["exec", args[3], "rm", "-rf", venv], timeout)
        return ran

    run = referee_score(
        case.pin(),
        "",
        repo=repo,
        scorer_commit=SCORER_COMMIT,
        image=IMAGE,
        docker=drop_the_environment,
    )
    assert run.outcome == "ERROR", run.detail
    assert "never syncs" in run.detail
