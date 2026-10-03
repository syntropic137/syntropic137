"""SYN_DEFAULT_CLAUDE_MODEL / SYN_DEFAULT_CODEX_MODEL (ADR-004)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_shared.agents import (
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_CODEX_MODEL,
    CodexModelAlias,
    ModelAlias,
    PhaseModelDefaults,
)
from syn_shared.settings.config import Settings

pytestmark = pytest.mark.unit


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in ("SYN_DEFAULT_CLAUDE_MODEL", "SYN_DEFAULT_CODEX_MODEL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]  # pydantic-settings init kwarg


def test_unset_gives_the_static_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = _settings(monkeypatch).phase_model_defaults
    assert defaults == PhaseModelDefaults()
    assert (defaults.claude, defaults.codex) == (DEFAULT_CLAUDE_MODEL, DEFAULT_CODEX_MODEL)
    assert (defaults.claude, defaults.codex) == (ModelAlias.OPUS, CodexModelAlias.GPT_SOL)


def test_env_overrides_both(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = _settings(
        monkeypatch,
        SYN_DEFAULT_CLAUDE_MODEL=f"  {ModelAlias.SONNET} ",
        SYN_DEFAULT_CODEX_MODEL="gpt-5.6-terra",
    ).phase_model_defaults
    assert defaults.claude == ModelAlias.SONNET
    assert defaults.codex == "gpt-5.6-terra"


@pytest.mark.parametrize("claude_model", [str(ModelAlias.HAIKU), "claude-opus-5-5"])
def test_a_claude_model_is_refused_as_the_codex_default(
    monkeypatch: pytest.MonkeyPatch, claude_model: str
) -> None:
    """Codex would drop it and run gpt-sol anyway: refuse at startup instead."""
    with pytest.raises(ValidationError, match="SYN_DEFAULT_CODEX_MODEL"):
        _settings(monkeypatch, SYN_DEFAULT_CODEX_MODEL=claude_model)


def test_a_codex_alias_is_refused_as_the_claude_default(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="SYN_DEFAULT_CLAUDE_MODEL"):
        _settings(monkeypatch, SYN_DEFAULT_CLAUDE_MODEL=CodexModelAlias.GPT_SOL)


@pytest.mark.parametrize("key", ["SYN_DEFAULT_CLAUDE_MODEL", "SYN_DEFAULT_CODEX_MODEL"])
def test_blank_is_refused(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    with pytest.raises(ValidationError):
        _settings(monkeypatch, **{key: "   "})


def test_for_provider_routes_codex_and_everything_else() -> None:
    defaults = PhaseModelDefaults(claude="c", codex="x")
    assert defaults.for_provider("codex") == "x"
    assert defaults.for_provider("claude") == "c"
    assert defaults.for_provider(None) == "c"
