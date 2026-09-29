"""A copied default image in .env follows pin bumps; an operator's own never moves (#1398)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from syn_shared.settings.workspace_image_migration import (
    MigrationOutcome,
    main,
    migrate_file,
    migrate_text,
)
from syn_shared.settings.workspace_images import (
    DEFAULT_WORKSPACE_IMAGE,
    PINNED_DIGESTS,
    PREVIOUS_DEFAULT_WORKSPACE_IMAGES,
    WorkspaceImageProvider,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
OLD = (
    "ghcr.io/agentparadise/agentic-workspace-omni-agent@sha256:"
    "89189b6c9cf67ac6a9b137fa7427990ca5535077e53e729a0ff4635053e6970d"
)
CUSTOM = "ghcr.io/example/my-omni@sha256:" + "ab" * 32


def test_the_current_default_is_never_a_previous_one() -> None:
    assert DEFAULT_WORKSPACE_IMAGE not in PREVIOUS_DEFAULT_WORKSPACE_IMAGES
    assert DEFAULT_WORKSPACE_IMAGE.endswith(PINNED_DIGESTS[WorkspaceImageProvider.OMNI_AGENT])
    assert len(set(PREVIOUS_DEFAULT_WORKSPACE_IMAGES)) == len(PREVIOUS_DEFAULT_WORKSPACE_IMAGES)
    # The default this change replaced is the most recent previous one.
    assert PREVIOUS_DEFAULT_WORKSPACE_IMAGES[-1] == OLD


@pytest.mark.parametrize(
    "line",
    [
        f"SYN_WORKSPACE_DOCKER_IMAGE='{OLD}'\n",
        f'SYN_WORKSPACE_DOCKER_IMAGE="{OLD}"\n',
        f"SYN_WORKSPACE_DOCKER_IMAGE={OLD}\n",
        f"export SYN_WORKSPACE_DOCKER_IMAGE={OLD}  # copied\n",
    ],
)
def test_old_default_is_migrated_keeping_quotes_and_neighbours(line: str) -> None:
    text = f"# header\nA=1\n{line}B='two'\n"
    result = migrate_text(text)
    assert result.outcome is MigrationOutcome.MIGRATED
    assert result.previous == OLD
    assert OLD not in result.text
    assert DEFAULT_WORKSPACE_IMAGE in result.text
    assert result.text.startswith("# header\nA=1\n") and result.text.endswith("B='two'\n")
    assert migrate_text(result.text).outcome is MigrationOutcome.CURRENT


@pytest.mark.parametrize("previous", PREVIOUS_DEFAULT_WORKSPACE_IMAGES)
def test_every_previous_default_migrates(previous: str) -> None:
    result = migrate_text(f"SYN_WORKSPACE_DOCKER_IMAGE='{previous}'\n")
    assert result.outcome is MigrationOutcome.MIGRATED
    assert result.text == f"SYN_WORKSPACE_DOCKER_IMAGE='{DEFAULT_WORKSPACE_IMAGE}'\n"


def test_custom_override_is_untouched() -> None:
    text = f"SYN_WORKSPACE_DOCKER_IMAGE='{CUSTOM}'\n"
    result = migrate_text(text)
    assert result.outcome is MigrationOutcome.CUSTOM
    assert result.text == text


def test_absent_and_commented_out_are_left_alone() -> None:
    text = f"A=1\n# SYN_WORKSPACE_DOCKER_IMAGE='{OLD}'\n"
    result = migrate_text(text)
    assert result.outcome is MigrationOutcome.ABSENT
    assert result.text == text


def test_file_is_rewritten_only_when_migrated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old, custom = tmp_path / "old.env", tmp_path / "custom.env"
    old.write_text(f"SYN_WORKSPACE_DOCKER_IMAGE='{OLD}'\n")
    custom.write_text(f"SYN_WORKSPACE_DOCKER_IMAGE='{CUSTOM}'\n")
    before = custom.stat().st_mtime_ns
    assert main([str(old)]) == 0
    assert OLD in capsys.readouterr().out
    assert old.read_text() == f"SYN_WORKSPACE_DOCKER_IMAGE='{DEFAULT_WORKSPACE_IMAGE}'\n"
    assert migrate_file(custom).outcome is MigrationOutcome.CUSTOM
    assert custom.stat().st_mtime_ns == before
    assert migrate_file(tmp_path / "missing.env").outcome is MigrationOutcome.ABSENT


def test_env_example_ships_the_current_default() -> None:
    """The generated example must carry today's default, or the next operator copies a stale one."""
    example = (_REPO / ".env.example").read_text()
    assert f"SYN_WORKSPACE_DOCKER_IMAGE='{DEFAULT_WORKSPACE_IMAGE}'" in example


def test_every_shipped_example_value_is_known() -> None:
    """Each value .env.example ever carried on this branch is either current or listed."""
    log = subprocess.run(
        ["git", "-C", str(_REPO), "log", "--format=%H", "--", ".env.example"],
        capture_output=True,
        text=True,
        check=False,
    )
    if log.returncode != 0 or not log.stdout.strip():
        pytest.skip("git history unavailable (shallow or exported tree)")
    known = {DEFAULT_WORKSPACE_IMAGE, *PREVIOUS_DEFAULT_WORKSPACE_IMAGES}
    for commit in log.stdout.split():
        shown = subprocess.run(
            ["git", "-C", str(_REPO), "show", f"{commit}:.env.example"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in shown.stdout.splitlines():
            if line.startswith("SYN_WORKSPACE_DOCKER_IMAGE="):
                value = line.split("=", 1)[1].strip("'\"")
                assert value in known, f"{commit[:8]} shipped {value}"
