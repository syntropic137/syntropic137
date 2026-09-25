"""A workflow DEFINITION shows what its model alias resolves to.

``model`` stays the alias the author wrote; ``resolved_model`` and
``model_display`` say what it stands for, from the shared resolver. Run-time
surfaces are untouched: they carry the observed model (ADR-067 D9).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_api.routes.workflows.queries import _map_phases
from syn_api.types import PhaseDefinitionResponse
from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
    PhaseDefinitionDetail,
)
from syn_shared.agents import AliasResolutionBasis

pytestmark = pytest.mark.unit


def _served(model: str | None, provider: str | None = None) -> PhaseDefinitionResponse:
    """The phase as served: mapped, then round-tripped through its JSON."""
    (phase,) = _map_phases(
        [PhaseDefinitionDetail(id="p1", name="P1", model=model, provider=provider)]
    )
    return PhaseDefinitionResponse.model_validate_json(phase.model_dump_json())


def test_codex_alias_is_served_with_its_translation() -> None:
    served = _served("gpt-sol", provider="codex")
    assert served.model == "gpt-sol"
    assert served.resolved_model == "gpt-6-sol"
    assert served.resolution_basis is AliasResolutionBasis.TRANSLATED
    assert served.model_display == "gpt-sol → gpt-6-sol"


def test_claude_alias_is_served_with_its_expected_target() -> None:
    served = _served("opus", provider="claude")
    assert served.model == "opus"
    assert served.resolved_model == "claude-opus-5-5"
    assert served.resolution_basis is AliasResolutionBasis.EXPECTED
    assert served.model_display == "opus → claude-opus-5-5"


@pytest.mark.parametrize("model", ["claude-sonnet-5", "some-future-model"])
def test_concrete_or_unknown_model_has_no_resolution(model: str) -> None:
    served = _served(model)
    assert served.resolved_model is None
    assert served.resolution_basis is None
    assert served.model_display == model


@pytest.mark.parametrize(
    ("provider", "expected_display", "expected_target"),
    [
        ("codex", "default \u2192 gpt-sol \u2192 gpt-6-sol", "gpt-6-sol"),
        (None, "default \u2192 opus \u2192 claude-opus-5-5", "claude-opus-5-5"),
    ],
)
def test_unset_model_shows_the_default_execution_substitutes(
    provider: str | None, expected_display: str, expected_target: str
) -> None:
    served = _served(None, provider=provider)
    assert served.model is None
    assert served.resolved_model == expected_target
    assert served.model_display == expected_display


def test_wrong_provider_model_shows_what_execution_runs_instead() -> None:
    """A legacy codex phase storing `opus` runs the codex default, not Opus."""
    served = _served("opus", provider="codex")
    assert served.model == "opus"
    assert served.resolved_model == "gpt-6-sol"
    assert served.resolution_basis is AliasResolutionBasis.TRANSLATED
    assert served.model_display == "opus \u2192 gpt-sol \u2192 gpt-6-sol"


def test_display_agrees_with_the_execution_rule() -> None:
    from syn_shared.agents import resolve_phase_model

    for provider, model in [("codex", "opus"), ("claude", "gpt-sol"), ("codex", None)]:
        served = _served(model, provider=provider)
        assert served.model_display is not None
        assert resolve_phase_model(provider, model) in served.model_display


def test_resolved_model_can_never_hold_an_alias() -> None:
    with pytest.raises(ValidationError):
        PhaseDefinitionResponse(phase_id="p", name="p", resolved_model="opus")


def test_fields_are_in_the_openapi_contract() -> None:
    from syn_api.main import app

    phase = app.openapi()["components"]["schemas"]["PhaseDefinitionResponse"]["properties"]
    assert {"resolved_model", "resolution_basis", "model_display"} <= set(phase)
