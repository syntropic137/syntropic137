"""The response models added for the desktop client are frozen and refuse unknown fields.

Every API boundary model is ``frozen=True, extra="forbid"`` (CLAUDE.md). A model
without it silently discards a misspelled field and stays mutable after it is
built, so a route can hand back something other than what it validated.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from syn_api.routes.workflows.queries import (
    PhaseLatestOutputResponse,
    WorkflowLatestOutputsResponse,
)
from syn_api.types import DeclaredSkillResponse, TokenTypeCostResponse

pytestmark = pytest.mark.unit

VALID: list[tuple[type[BaseModel], dict[str, object]]] = [
    (DeclaredSkillResponse, {"name": "review"}),
    (
        TokenTypeCostResponse,
        {
            "input_usd": Decimal(1),
            "output_usd": Decimal(1),
            "cache_creation_usd": Decimal(0),
            "cache_read_usd": Decimal(0),
            "basis": "rate_table",
        },
    ),
    (PhaseLatestOutputResponse, {"phase_id": "plan", "phase_name": "Plan"}),
    (WorkflowLatestOutputsResponse, {"workflow_id": "wf", "phases": []}),
]


@pytest.mark.parametrize(("model", "fields"), VALID, ids=lambda v: getattr(v, "__name__", ""))
def test_an_unknown_field_is_rejected(model: type[BaseModel], fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate({**fields, "not_a_field": 1})


@pytest.mark.parametrize(("model", "fields"), VALID, ids=lambda v: getattr(v, "__name__", ""))
def test_a_built_response_cannot_be_mutated(
    model: type[BaseModel], fields: dict[str, object]
) -> None:
    built = model.model_validate(fields)
    first = next(iter(fields))
    with pytest.raises(ValidationError, match="frozen_instance"):
        setattr(built, first, fields[first])
