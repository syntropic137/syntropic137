"""Argv elements must survive the trip to `sh -c` as separate arguments.

The adapter joins the command list into one string because the isolation
provider's contract is string-based, and the provider then runs it through
`sh -c`. A bare `" ".join(...)` silently reassociates the arguments:

    ["sh", "-c", "test -e /workspace/.setup/codex-auth.json"]
    -> sh -c test -e /workspace/.setup/codex-auth.json

which runs `test` with NO operands and always exits 1. Proven in a container:

    sh -c test -e /tmp/exists      -> exit 1   (the file exists)
    sh -c 'test -e /tmp/exists'    -> exit 0

The live victim is `_assert_codex_credential_removed`, a SECURITY check
documented to fail closed so a lingering staged credential is never reported
as cleared. Because the probe always exited nonzero, it always took the
"credential is gone" early return, and its fail-closed branch could not run.
"""

from __future__ import annotations

import shlex

import pytest

CODEX_AUTH = "/workspace/.setup/codex-auth.json"


def _joined(command: list[str]) -> str:
    """What the adapter now sends to the provider."""
    return shlex.join(command)


class TestQuotingSurvivesTheJoin:
    @pytest.mark.unit
    def test_a_shell_program_stays_one_argument(self) -> None:
        joined = _joined(["sh", "-c", f"test -e {CODEX_AUTH}"])

        assert joined == f"sh -c 'test -e {CODEX_AUTH}'"

    @pytest.mark.unit
    def test_the_old_join_produced_a_different_program(self) -> None:
        """Pins the difference, so nobody 'simplifies' this back."""
        command = ["sh", "-c", f"test -e {CODEX_AUTH}"]

        assert " ".join(command) != _joined(command)
        # The old form loses the quotes entirely, which is what made `test`
        # run with no operands.
        assert "'" not in " ".join(command)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "command",
        [
            ["echo", "hello"],
            ["rm", "-f", "/tmp/x"],
            ["python", "script.py"],
            ["apss-session-exporter", "--json"],
        ],
    )
    def test_simple_argv_is_unchanged(self, command: list[str]) -> None:
        """Only the broken cases differ; ordinary commands are byte-identical."""
        assert _joined(command) == " ".join(command)

    @pytest.mark.unit
    def test_a_multiline_program_survives(self) -> None:
        """The capture probe passes a whole script as one element.

        Under the bare join it arrived as `bash -c` followed by loose words,
        so bash exited with "option requires an argument" and the remainder
        was interpreted by the outer shell instead.
        """
        script = "for d in a b; do\n  echo $d\ndone\n"

        joined = _joined(["bash", "-c", script])

        assert joined.startswith("bash -c '")
        assert shlex.split(joined) == ["bash", "-c", script]

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "hostile",
        [
            "a; touch /tmp/pwned",
            "$(whoami)",
            "`id`",
            "x && y",
            "a | b",
            "'quoted'",
        ],
    )
    def test_metacharacters_cannot_escape_their_argument(self, hostile: str) -> None:
        """A path or filename containing shell syntax must stay data."""
        assert shlex.split(_joined(["echo", hostile])) == ["echo", hostile]
