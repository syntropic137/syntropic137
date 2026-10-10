"""Retired Claude models never run, and aliases reach the CLI as explicit ids.

Owner directive 2026-10-10: never run Sonnet 4.5 again. The pinned
claude-code (2.1.293) resolves ``sonnet`` to ``claude-sonnet-4-5`` on Bedrock,
Vertex, Foundry and Mantle, so the platform translates every alias itself and
refuses retired ids at install, at phase edit, at startup and at launch.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_shared.agents import (
    CLAUDE_MODEL_ALIAS_TARGETS,
    AgentProvider,
    ModelAlias,
    ModelId,
    PhaseModelDefaults,
    RetiredModelError,
    claude_model_pin_env,
    is_retired_claude_model,
    normalize_phase_model,
    resolve_claude_model,
    resolve_phase_model,
)

pytestmark = pytest.mark.unit

RETIRED = [
    ModelId.CLAUDE_SONNET_4_5,
    ModelId.CLAUDE_OPUS_4_5,
    ModelId.CLAUDE_SONNET_4,
    ModelId.CLAUDE_OPUS_4,
    ModelId.CLAUDE_SONNET_3_5,
    ModelId.CLAUDE_HAIKU_3_5,
    ModelId.CLAUDE_OPUS_3,
    ModelId.CLAUDE_HAIKU_3,
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-1",
    "claude-3-7-sonnet",
    "claude-sonnet-4-20250514[1m]",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
]

ALLOWED = [
    ModelId.CLAUDE_SONNET_5_5,
    ModelId.CLAUDE_OPUS_5_5,
    ModelId.CLAUDE_SONNET_5,
    ModelId.CLAUDE_FABLE_5,
    ModelId.CLAUDE_HAIKU_4_5,
    "claude-haiku-4-5",
    "claude-opus-5-5[1m]",
    "some-future-model",
]


@pytest.mark.parametrize("model", RETIRED)
def test_retired(model: str) -> None:
    assert is_retired_claude_model(model)
    with pytest.raises(RetiredModelError, match=str(model).replace("[", r"\[")):
        resolve_claude_model(model)


@pytest.mark.parametrize("model", ALLOWED)
def test_allowed(model: str) -> None:
    assert not is_retired_claude_model(model)
    assert resolve_claude_model(model) == model


@pytest.mark.parametrize(
    ("alias", "target"),
    [
        ("sonnet", "claude-sonnet-5-5"),
        ("opus", "claude-opus-5-5"),
        ("haiku", "claude-haiku-4-5-20251001"),
        ("fable", "claude-fable-5"),
    ],
)
def test_alias_resolves_to_an_explicit_id(alias: str, target: str) -> None:
    resolved = resolve_claude_model(alias)
    assert resolved == target
    assert type(resolved) is str


@pytest.mark.parametrize("model", [ModelId.CLAUDE_SONNET_4_5, "claude-sonnet-4-5"])
@pytest.mark.parametrize("provider", [None, AgentProvider.CLAUDE])
def test_install_and_edit_refuse_a_declared_retired_model(model: str, provider: str | None) -> None:
    with pytest.raises(RetiredModelError):
        normalize_phase_model(provider, model, PhaseModelDefaults())


def test_install_refuses_a_retired_operator_default() -> None:
    defaults = PhaseModelDefaults(claude=ModelId.CLAUDE_SONNET_4_5)
    with pytest.raises(RetiredModelError):
        normalize_phase_model(AgentProvider.CLAUDE, None, defaults)


def test_codex_phase_is_not_judged_by_the_claude_deny_list() -> None:
    model, defaulted = normalize_phase_model(
        AgentProvider.CODEX, "gpt-6-luna", PhaseModelDefaults()
    )
    assert (model, defaulted) == ("gpt-6-luna", False)


def test_execution_still_loads_a_past_retired_model() -> None:
    """History must replay: a run that used Sonnet 4.5 is still displayable."""
    assert resolve_phase_model(AgentProvider.CLAUDE, ModelId.CLAUDE_SONNET_4_5) == (
        ModelId.CLAUDE_SONNET_4_5
    )


def test_settings_refuse_a_retired_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_shared.settings.config import Settings

    monkeypatch.setenv("SYN_DEFAULT_CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
    with pytest.raises(ValidationError, match="retired"):
        Settings()


def test_pin_env_pins_every_alias_and_the_default_session_model() -> None:
    env = claude_model_pin_env()
    assert env == {
        "ANTHROPIC_MODEL": "claude-opus-5-5",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-5-5",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5-5",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5-20251001",
        "ANTHROPIC_DEFAULT_FABLE_MODEL": "claude-fable-5",
    }
    assert set(ModelAlias) == set(CLAUDE_MODEL_ALIAS_TARGETS)
