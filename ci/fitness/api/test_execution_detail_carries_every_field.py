"""A field the read model has and the API response has must actually be passed.

Three defects in a row (#1011, #1013, #1015) were the same shape: a value
written correctly and dropped one hop later. The hop is a constructor call where
the field simply is not passed, so it silently takes its default - `False`, `[]`,
`None` - and pyright cannot see it, because a defaulted field is legal to omit.

This walks the AST of the execution query builders and fails when a name present
on BOTH the source read model and the destination response model is missing from
the call. It generalises: the next dropped field fails here without anyone
writing a test for it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_ROOT = Path(__file__).resolve().parents[3]
_QUERIES = _ROOT / "apps" / "syn-api" / "src" / "syn_api" / "routes" / "executions" / "queries.py"

#: Fields the destination deliberately does not take from the read model, with
#: the reason. Anything else common to both must be passed.
_NOT_FROM_THE_READ_MODEL: dict[str, str] = {
    "total_tokens": "recomputed from enriched Lane 2 cost data",
    "total_cost_usd": "Lane 2: enriched from execution_cost (#695)",
    "unpriced_observation_count": "Lane 2: comes from the cost enrichment",
    "phases": "mapped through _map_phase_to_response, not copied",
}


def _model_field_names(module: str, class_name: str) -> set[str]:
    import importlib

    model = getattr(importlib.import_module(module), class_name)
    fields = getattr(model, "model_fields", None)
    if fields is not None:
        return set(fields)
    return {f.name for f in model.__dataclass_fields__.values()}  # type: ignore[attr-defined]


def _kwargs_passed_to(call_name: str) -> set[str]:
    """Keyword names passed to the first `call_name(...)` in queries.py."""
    tree = ast.parse(_QUERIES.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == call_name
        ):
            return {kw.arg for kw in node.keywords if kw.arg}
    raise AssertionError(f"no call to {call_name}() found in {_QUERIES}")


@pytest.mark.parametrize(
    ("module", "class_name"),
    [
        ("syn_api.types", "ExecutionDetailFull"),
        ("syn_api.routes.executions.models", "ExecutionDetailResponse"),
    ],
)
def test_every_shared_field_is_actually_passed(module: str, class_name: str) -> None:
    source = _model_field_names(
        "syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail",
        "WorkflowExecutionDetail",
    )
    destination = _model_field_names(module, class_name)
    passed = _kwargs_passed_to(class_name)

    shared = (source & destination) - set(_NOT_FROM_THE_READ_MODEL)
    dropped = sorted(shared - passed)

    assert not dropped, (
        f"{class_name}(...) does not pass {dropped}, which exist on both "
        f"WorkflowExecutionDetail and {class_name}. A defaulted field omitted at a "
        f"constructor is invisible to pyright and reads as 'no data' downstream. "
        f"Pass it, or record in _NOT_FROM_THE_READ_MODEL why it must not come "
        f"from the read model."
    )
