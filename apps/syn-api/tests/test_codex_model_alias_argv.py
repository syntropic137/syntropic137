"""`gpt-sol` reaches codex as `--model gpt-6-sol` (R2).

Codex has no alias feature: `codex exec --model gpt-sol` names a model that
does not exist. The platform alias is stored and requested as written and
translated here, at the last moment, so the argv is the only place the
concrete slug appears.
"""

from __future__ import annotations

import pytest

from syn_api._codex_command import _build_codex_command
from syn_shared.agents import CodexModelAlias, ModelAlias, ModelId

pytestmark = pytest.mark.unit


def _model_flag(cmd: list[str]) -> str | None:
    if "--model" not in cmd:
        return None
    return cmd[cmd.index("--model") + 1]


def test_gpt_sol_is_sent_as_gpt_6_sol() -> None:
    cmd = _build_codex_command("p", CodexModelAlias.GPT_SOL)
    assert _model_flag(cmd) == ModelId.GPT_6_SOL
    assert CodexModelAlias.GPT_SOL not in cmd


def test_every_codex_alias_is_translated() -> None:
    for alias in CodexModelAlias:
        assert _model_flag(_build_codex_command("p", alias)) != alias


def test_a_concrete_slug_is_forwarded_unchanged() -> None:
    assert _model_flag(_build_codex_command("p", ModelId.GPT_5_6_SOL)) == ModelId.GPT_5_6_SOL


def test_a_claude_alias_is_still_never_forwarded() -> None:
    assert _model_flag(_build_codex_command("p", ModelAlias.OPUS)) is None


def test_the_prompt_stays_last() -> None:
    cmd = _build_codex_command("do it", CodexModelAlias.GPT_SOL)
    assert cmd[-1] == "do it"
