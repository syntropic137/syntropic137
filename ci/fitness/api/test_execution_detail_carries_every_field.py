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
_ROUTES = _ROOT / "apps" / "syn-api" / "src" / "syn_api" / "routes" / "executions"

#: Fields the destination deliberately does not take from the read model, keyed
#: by "<destination>.<field>" so an exception cannot silently apply to a model it
#: was never meant for. Each entry is asserted to be in the intersection it
#: claims to except: the first version of this list had four entries, three of
#: which were not on the source model at all and so excepted nothing.
_NOT_FROM_THE_READ_MODEL: dict[str, str] = {
    "ExecutionDetailFull.phases": "mapped through _map_phase_to_response, not copied",
    "ExecutionDetailResponse.phases": "mapped through _map_phase_to_response, not copied",
}


def _model_field_names(module: str, class_name: str) -> set[str]:
    import importlib

    model = getattr(importlib.import_module(module), class_name)
    fields = getattr(model, "model_fields", None)
    if fields is not None:
        return set(fields)
    return {f.name for f in model.__dataclass_fields__.values()}  # type: ignore[attr-defined]


def _called_name(func: ast.expr) -> str | None:
    """The constructor name, whether called bare or attribute-qualified."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _kwargs_passed_to(call_name: str) -> set[str]:
    """Keywords common to EVERY `call_name(...)` across the executions routes.

    Every call, not the first: a second construction site that drops a field
    while the first still passes it was the obvious way to defeat the earlier
    version of this check. Intersecting means one careless site fails the gate.

    Attribute-qualified calls count, so `models.ExecutionDetailFull(...)` cannot
    hide, and `**kwargs` fails loudly rather than being read as "passes nothing".
    """
    sites: list[set[str]] = []
    for path in sorted(_ROUTES.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _called_name(node.func) != call_name:
                continue
            if any(kw.arg is None for kw in node.keywords):
                raise AssertionError(
                    f"{path.name}:{node.lineno} builds {call_name} with **kwargs; this "
                    f"gate cannot see which fields that passes, so it cannot certify it"
                )
            sites.append({kw.arg for kw in node.keywords if kw.arg})
    if not sites:
        raise AssertionError(f"no call to {call_name}() found under {_ROUTES}")
    return set.intersection(*sites)


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

    excepted = {
        field
        for key, _ in _NOT_FROM_THE_READ_MODEL.items()
        for model, field in [key.split(".", 1)]
        if model == class_name
    }
    for key in _NOT_FROM_THE_READ_MODEL:
        model, field = key.split(".", 1)
        if model == class_name:
            assert field in (source & destination), (
                f"{key} excepts a field that is not on both WorkflowExecutionDetail "
                f"and {class_name}, so it excepts nothing and hides nothing. Remove it."
            )

    shared = (source & destination) - excepted
    dropped = sorted(shared - passed)

    assert not dropped, (
        f"{class_name}(...) does not pass {dropped}, which exist on both "
        f"WorkflowExecutionDetail and {class_name}. A defaulted field omitted at a "
        f"constructor is invisible to pyright and reads as 'no data' downstream. "
        f"Pass it, or record in _NOT_FROM_THE_READ_MODEL why it must not come "
        f"from the read model."
    )
