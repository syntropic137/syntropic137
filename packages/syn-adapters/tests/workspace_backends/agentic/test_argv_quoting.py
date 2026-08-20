"""Argv must survive the adapter's join as separate arguments to `sh -c`.

These assert against the PRODUCTION adapters through a spy provider. An earlier
version of this file defined its own `_joined()` helper that called shlex.join
directly, so every test would have stayed green if the adapters reverted to
`" ".join(command)` the next day - it tested a reimplementation, not the code.

The defect: the provider runs the joined string through `sh -c`, so a bare join
reassociates argv.

    ["sh", "-c", "test -e /workspace/.setup/codex-auth.json"]
    -> sh -c test -e /workspace/.setup/codex-auth.json

which runs `test` with NO operands and always exits 1. Verified through the
provider's own shape against the pinned image:

    sh -c test -e /tmp/exists      exit 1   (the file EXISTS)
    sh -c 'test -e /tmp/exists'    exit 0
"""

from __future__ import annotations

import inspect
import shlex

import pytest

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter

CODEX_AUTH = "/workspace/.setup/codex-auth.json"


class _SpyProvider:
    """Records the exact string the adapter hands the provider."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def execute(self, _workspace: object, command: str, **_kw: object) -> object:
        self.commands.append(command)

        class _Result:
            exit_code = 0
            success = True
            timed_out = False
            stdout = ""
            stderr = ""
            duration_ms = 1.0

        return _Result()


def _adapter_with_spy() -> tuple[AgenticIsolationAdapter, _SpyProvider, object]:
    """A real adapter wired to a spy, with one workspace registered."""
    adapter = object.__new__(AgenticIsolationAdapter)
    spy = _SpyProvider()
    adapter._provider = spy  # type: ignore[attr-defined]

    class _Handle:
        isolation_id = "ws-1"

    adapter._workspaces = {"ws-1": object()}  # type: ignore[attr-defined]
    return adapter, spy, _Handle()


async def _sent(command: list[str]) -> str:
    adapter, spy, handle = _adapter_with_spy()
    await adapter.execute(handle, command)  # type: ignore[arg-type]
    assert spy.commands, "the adapter never reached the provider"
    return spy.commands[-1]


class TestTheAdapterQuotesWhatItSends:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_shell_program_arrives_as_one_argument(self) -> None:
        sent = await _sent(["sh", "-c", f"test -e {CODEX_AUTH}"])

        # The property that matters: `sh -c` receives the test expression as a
        # single argument, so `test` gets its operands.
        assert shlex.split(sent) == ["sh", "-c", f"test -e {CODEX_AUTH}"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_bare_join_would_have_produced_a_different_program(
        self,
    ) -> None:
        """Pins the regression, so a revert fails HERE rather than in prod."""
        command = ["sh", "-c", f"test -e {CODEX_AUTH}"]

        sent = await _sent(command)

        assert sent != " ".join(command)
        assert shlex.split(" ".join(command)) != command

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_multiline_script_survives(self) -> None:
        """The capture probe passes a whole script as one element.

        Under the bare join it arrived as `bash -c` followed by loose words:
        bash exits 2 with "option requires an argument" and the outer shell
        interprets the remainder.
        """
        script = "for d in a b; do\n  echo $d\ndone\n"

        sent = await _sent(["bash", "-c", script])

        assert shlex.split(sent) == ["bash", "-c", script]

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "command",
        [
            ["echo", "hello"],
            ["rm", "-f", "/tmp/x"],
            ["bash", "/workspace/.setup/setup.sh"],
            ["rm", "-rf", "/workspace/.cleanup"],
        ],
    )
    async def test_ordinary_argv_is_unchanged(self, command: list[str]) -> None:
        """Only the broken shapes differ, so this cannot be blamed for
        unrelated breakage. These are the real other call sites."""
        assert await _sent(command) == " ".join(command)

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "hostile",
        ["a; touch /tmp/pwned", "$(whoami)", "`id`", "x && y", "a | b", "'quoted'"],
    )
    async def test_metacharacters_stay_data(self, hostile: str) -> None:
        """A path containing shell syntax must not become syntax."""
        assert shlex.split(await _sent(["echo", hostile])) == ["echo", hostile]


class TestBothBackendsAgree:
    """Same port, same contract - the behaviour must not depend on backend."""

    @pytest.mark.unit
    def test_the_interactive_tmux_adapter_quotes_too(self) -> None:
        from syn_adapters.workspace_backends.interactive_tmux import adapter as tmux

        body = inspect.getsource(tmux)

        assert "shlex.join(command)" in body
        assert '" ".join(command)' not in body
