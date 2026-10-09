"""The trend response models are frozen and refuse unknown fields (#1800 review nit).

Every API boundary model is ``frozen=True, extra="forbid"`` (CLAUDE.md): an
unknown field is a contract drift to fail on, not one to drop silently.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from syn_api.types import (
    DefinitionChangeResponse,
    EvalTrendPointResponse,
    EvalTrendResponse,
    PhaseDurationResponse,
    TrendDefinition,
    WorkflowTrendPointResponse,
    WorkflowTrendResponse,
)

pytestmark = pytest.mark.unit

_MODELS: list[type[BaseModel]] = [
    DefinitionChangeResponse,
    TrendDefinition,
    EvalTrendPointResponse,
    EvalTrendResponse,
    PhaseDurationResponse,
    WorkflowTrendPointResponse,
    WorkflowTrendResponse,
]


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
def test_a_trend_model_rejects_an_unknown_field(model: type[BaseModel]) -> None:
    with pytest.raises(ValidationError) as raised:
        model.model_validate({"not_a_field": 1})

    assert ("extra_forbidden", ("not_a_field",)) in {
        (e["type"], tuple(e["loc"])) for e in raised.value.errors()
    }


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
def test_a_trend_model_is_frozen(model: type[BaseModel]) -> None:
    assert model.model_config.get("frozen") is True
    assert model.model_config.get("extra") == "forbid"


def test_a_phase_duration_cannot_be_reassigned() -> None:
    duration = PhaseDurationResponse(phase_id="p", phase_name="P", duration_seconds=1.0)

    with pytest.raises(ValidationError):
        duration.duration_seconds = 2.0  # pyright: ignore[reportAttributeAccessIssue]  # the point
