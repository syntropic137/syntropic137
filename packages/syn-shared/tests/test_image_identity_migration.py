"""A copied default signer identity in .env follows the publisher; an operator's own never moves (#1398)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from syn_shared.settings.image_verification import (
    AGENTIC_PRIMITIVES_IDENTITY_REGEXP,
    PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS,
    WORKSPACE_IMAGE_IDENTITY_REGEXP,
    ImageVerificationSettings,
)
from syn_shared.settings.workspace_image_migration import (
    IMAGE_IDENTITY_RULE,
    WORKSPACE_IMAGE_RULE,
    MigrationOutcome,
    main,
    migrate_file,
    migrate_text,
    stale_default_message,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
VAR = "SYN_IMAGE_VERIFY_CERTIFICATE_IDENTITY_REGEXP"
CUSTOM = r"^https://github\.com/example/fork/\.github/workflows/build\.yml@refs/heads/main$"


def test_previous_identities_are_distinct_and_exclude_the_current_default() -> None:
    assert WORKSPACE_IMAGE_IDENTITY_REGEXP not in PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS
    assert len(set(PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS)) == len(
        PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS
    )
    assert AGENTIC_PRIMITIVES_IDENTITY_REGEXP in PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS
    assert (
        ImageVerificationSettings.model_fields["certificate_identity_regexp"].default
        == WORKSPACE_IMAGE_IDENTITY_REGEXP
    )


@pytest.mark.parametrize("previous", PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS)
@pytest.mark.parametrize("quote", ["'", '"', ""])
def test_every_previous_identity_migrates_keeping_quotes_and_neighbours(
    previous: str, quote: str
) -> None:
    text = f"# header\nA=1\n{VAR}={quote}{previous}{quote}\nB='two'\n"
    result = migrate_text(text, IMAGE_IDENTITY_RULE)
    assert result.outcome is MigrationOutcome.MIGRATED
    assert result.previous == previous
    assert result.text == (
        f"# header\nA=1\n{VAR}={quote}{WORKSPACE_IMAGE_IDENTITY_REGEXP}{quote}\nB='two'\n"
    )
    assert migrate_text(result.text, IMAGE_IDENTITY_RULE).outcome is MigrationOutcome.CURRENT


def test_custom_identity_is_untouched() -> None:
    text = f"{VAR}='{CUSTOM}'\n"
    result = migrate_text(text, IMAGE_IDENTITY_RULE)
    assert result.outcome is MigrationOutcome.CUSTOM
    assert result.text == text


def test_commented_out_identity_is_left_alone() -> None:
    text = f"# {VAR}='{AGENTIC_PRIMITIVES_IDENTITY_REGEXP}'\n"
    result = migrate_text(text, IMAGE_IDENTITY_RULE)
    assert result.outcome is MigrationOutcome.ABSENT
    assert result.text == text


def test_main_migrates_identity_and_image_together_and_prints_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    old_image = WORKSPACE_IMAGE_RULE.previous[-1]
    env.write_text(
        f"SYN_WORKSPACE_DOCKER_IMAGE='{old_image}'\n{VAR}='{AGENTIC_PRIMITIVES_IDENTITY_REGEXP}'\n"
    )
    assert main([str(env)]) == 0
    out = capsys.readouterr().out
    assert VAR in out and AGENTIC_PRIMITIVES_IDENTITY_REGEXP in out
    assert env.read_text() == (
        f"SYN_WORKSPACE_DOCKER_IMAGE='{DEFAULT_WORKSPACE_IMAGE}'\n"
        f"{VAR}='{WORKSPACE_IMAGE_IDENTITY_REGEXP}'\n"
    )


def test_custom_identity_file_is_not_rewritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    env.write_text(f"{VAR}='{CUSTOM}'\n")
    before = env.stat().st_mtime_ns
    assert migrate_file(env, IMAGE_IDENTITY_RULE).outcome is MigrationOutcome.CUSTOM
    assert env.stat().st_mtime_ns == before
    main([str(env)])
    assert "custom signer identity; left unchanged" in capsys.readouterr().out


def test_stale_default_message_names_the_variable_only_for_previous_defaults() -> None:
    message = stale_default_message(AGENTIC_PRIMITIVES_IDENTITY_REGEXP, IMAGE_IDENTITY_RULE)
    assert message is not None
    assert message.startswith(f"{VAR} is ")
    assert WORKSPACE_IMAGE_IDENTITY_REGEXP in message
    assert stale_default_message(WORKSPACE_IMAGE_IDENTITY_REGEXP, IMAGE_IDENTITY_RULE) is None
    assert stale_default_message(CUSTOM, IMAGE_IDENTITY_RULE) is None


def test_env_example_ships_the_current_identity() -> None:
    example = (_REPO / ".env.example").read_text()
    assert f"{VAR}='{WORKSPACE_IMAGE_IDENTITY_REGEXP}'" in example


def test_every_shipped_example_identity_is_known() -> None:
    """Each identity .env.example ever carried on this branch is either current or listed."""
    log = subprocess.run(
        ["git", "-C", str(_REPO), "log", "--format=%H", "--", ".env.example"],
        capture_output=True,
        text=True,
        check=False,
    )
    if log.returncode != 0 or not log.stdout.strip():
        pytest.skip("git history unavailable (shallow or exported tree)")
    known = {WORKSPACE_IMAGE_IDENTITY_REGEXP, *PREVIOUS_DEFAULT_IMAGE_IDENTITY_REGEXPS}
    for commit in log.stdout.split():
        shown = subprocess.run(
            ["git", "-C", str(_REPO), "show", f"{commit}:.env.example"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in shown.stdout.splitlines():
            if line.startswith(f"{VAR}="):
                value = line.split("=", 1)[1].strip("'\"")
                assert value in known, f"{commit[:8]} shipped {value}"
