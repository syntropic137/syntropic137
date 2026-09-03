"""`just` must be able to execute a shebang recipe in the workspace (#1042).

`/tmp` is mounted `noexec` by the isolation layer, deliberately. `just` writes a
shebang recipe to a temp file and runs it, so every shebang recipe - including
`qa-ci`, the gate the verify phase is told to run - failed with
`Permission denied (os error 13)`. A phase could spend an hour of model time and
then be unable to certify its own work.

Verified in a live workspace before writing this:

    $ just shebang-recipe                        -> Permission denied (os error 13)
    $ TMPDIR=/workspace/.tmp just shebang-recipe -> SHEBANG_RAN_OK
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.agentic.adapter import (
    _EXECUTABLE_TMPDIR,
    _WORKSPACE_CACHE_ENV,
    _with_executable_tmpdir,
)

pytestmark = pytest.mark.unit


class TestTmpdirIsSet:
    def test_an_empty_environment_gets_a_tmpdir(self) -> None:
        assert _with_executable_tmpdir({})["TMPDIR"] == _EXECUTABLE_TMPDIR

    def test_it_does_not_point_at_tmp(self) -> None:
        """The whole point: /tmp is noexec, so TMPDIR must not resolve there."""
        tmpdir = _with_executable_tmpdir({})["TMPDIR"]
        assert not tmpdir.startswith("/tmp"), f"{tmpdir} is under the noexec mount"

    def test_other_variables_survive(self) -> None:
        out = _with_executable_tmpdir({"FOO": "bar", "BAZ": "qux"})
        assert out["FOO"] == "bar"
        assert out["BAZ"] == "qux"
        assert out["TMPDIR"] == _EXECUTABLE_TMPDIR


class TestCallerWins:
    """A default, not a policy - a phase that sets TMPDIR keeps it."""

    def test_a_caller_supplied_tmpdir_is_not_overwritten(self) -> None:
        assert _with_executable_tmpdir({"TMPDIR": "/workspace/mine"})["TMPDIR"] == "/workspace/mine"

    @pytest.mark.parametrize("empty", ["", None])
    def test_an_empty_tmpdir_is_replaced(self, empty: str | None) -> None:
        """An empty value is not a choice; it would leave `just` broken."""
        env: dict[str, str] = {} if empty is None else {"TMPDIR": empty}
        assert _with_executable_tmpdir(env)["TMPDIR"] == _EXECUTABLE_TMPDIR


class TestNoSideEffects:
    def test_the_input_dict_is_not_mutated(self) -> None:
        """Callers pass a config's own dict; mutating it would leak across phases."""
        original = {"FOO": "bar"}
        _with_executable_tmpdir(original)
        assert "TMPDIR" not in original


class TestToolCachesAreOffTheTmpfs:
    """`$HOME` is a 128 MB tmpfs, and it is where every tool caches (#1133).

    A real verify phase died there, mid-gate, having already redirected TMPDIR:

        the workspace's 128 MiB /home/agent tmpfs ran out of space
        error: recipe `lint` failed on line 932 with exit code 1

    A prompt-level `export` is not enough: it lasts one shell, and the command
    that fills the disk is usually a dependency install run before the command
    carrying the export. So it belongs in the environment the workspace is
    given, next to TMPDIR.
    """

    @pytest.mark.parametrize("key", sorted(_WORKSPACE_CACHE_ENV))
    def test_every_cache_variable_is_set(self, key: str) -> None:
        assert _with_executable_tmpdir({})[key] == _WORKSPACE_CACHE_ENV[key]

    @pytest.mark.parametrize("key", sorted(_WORKSPACE_CACHE_ENV))
    def test_no_cache_lands_under_home_or_tmp(self, key: str) -> None:
        """The two small tmpfs mounts are exactly what these exist to avoid."""
        value = _with_executable_tmpdir({})[key]
        assert not value.startswith("/home"), f"{key}={value} is on the 128 MB tmpfs"
        assert not value.startswith("/tmp"), f"{key}={value} is on the 256 MB tmpfs"

    @pytest.mark.parametrize("key", sorted(_WORKSPACE_CACHE_ENV))
    def test_a_caller_supplied_value_wins(self, key: str) -> None:
        """A default, not a policy - the same contract TMPDIR already has."""
        assert _with_executable_tmpdir({key: "/somewhere/else"})[key] == "/somewhere/else"

    def test_an_empty_string_is_not_a_choice(self) -> None:
        """`FOO=` is how a variable gets unset by accident, not how it gets chosen."""
        assert _with_executable_tmpdir({"UV_CACHE_DIR": ""})["UV_CACHE_DIR"] == (
            _WORKSPACE_CACHE_ENV["UV_CACHE_DIR"]
        )
