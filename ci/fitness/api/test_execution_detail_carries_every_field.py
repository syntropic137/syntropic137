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
_ROUTES_ROOT = _ROOT / "apps" / "syn-api" / "src" / "syn_api" / "routes"

#: (route path under routes/, source read model, destination response models).
#: Declared rather than inferred, because "which response model corresponds to
#: which read model" is not mechanically derivable. The drift guard below is what
#: stops this table going stale: a route module that consumes a read model and is
#: absent from here fails the suite.
_PAIRS: tuple[tuple[str, tuple[str, str], tuple[tuple[str, str], ...]], ...] = (
    (
        "executions",
        (
            "syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail",
            "WorkflowExecutionDetail",
        ),
        (
            ("syn_api.types", "ExecutionDetailFull"),
            ("syn_api.routes.executions.models", "ExecutionDetailResponse"),
        ),
    ),
)

#: Route modules that import a read model but carry no source-to-response pair
#: worth gating, with the reason. #1033 was exactly this class living in
#: sessions.py while the gate watched only executions, so an unexplained absence
#: here is a gap rather than a non-case.
_NO_PAIR: dict[str, str] = {
    "sessions.py": "TODO(#1040): SessionSummary -> SessionDetail -> SessionResponse is the same shape and belongs here; adding it needs its own exception review",
    "costs.py": "Lane 2 cost read models are enriched, not copied field-for-field",
    "workflows/queries.py": "WorkflowDetail maps through per-phase builders, not a flat copy",
}

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


def _kwargs_passed_to(call_name: str, route_dir: str) -> set[str]:
    """Keywords common to EVERY `call_name(...)` across the executions routes.

    Every call, not the first: a second construction site that drops a field
    while the first still passes it was the obvious way to defeat the earlier
    version of this check. Intersecting means one careless site fails the gate.

    Attribute-qualified calls count, so `models.ExecutionDetailFull(...)` cannot
    hide, and `**kwargs` fails loudly rather than being read as "passes nothing".
    """
    sites: list[set[str]] = []
    for path in sorted((_ROUTES_ROOT / route_dir).glob("*.py")):
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
        raise AssertionError(f"no call to {call_name}() found under routes/{route_dir}")
    return set.intersection(*sites)


_PARAMS = [
    (route_dir, source, dest_mod, dest_cls)
    for route_dir, source, dests in _PAIRS
    for dest_mod, dest_cls in dests
]


@pytest.mark.parametrize(
    ("route_dir", "source", "module", "class_name"),
    _PARAMS,
    ids=[f"{r}:{c}" for r, _, _, c in _PARAMS],
)
def test_every_shared_field_is_actually_passed(
    route_dir: str,
    source: tuple[str, str],
    module: str,
    class_name: str,
) -> None:
    source_fields = _model_field_names(*source)
    destination = _model_field_names(module, class_name)
    passed = _kwargs_passed_to(class_name, route_dir)

    excepted = {
        field
        for key in _NOT_FROM_THE_READ_MODEL
        for model, field in [key.split(".", 1)]
        if model == class_name
    }
    for key in _NOT_FROM_THE_READ_MODEL:
        model, field = key.split(".", 1)
        if model == class_name:
            assert field in (source_fields & destination), (
                f"{key} excepts a field that is not on both {source[1]} and "
                f"{class_name}, so it excepts nothing and hides nothing. Remove it."
            )

    dropped = sorted((source_fields & destination) - excepted - passed)

    assert not dropped, (
        f"{class_name}(...) in routes/{route_dir} does not pass {dropped}, which "
        f"exist on both {source[1]} and {class_name}. A defaulted field omitted at "
        f"a constructor is invisible to pyright and reads as 'no data' downstream. "
        f"Pass it, or record in _NOT_FROM_THE_READ_MODEL why it must not come from "
        f"the read model."
    )


def test_no_route_consuming_a_read_model_is_unwatched() -> None:
    """A route that maps a read model to a response must be gated or excused.

    #1033 was this exact defect class living in sessions.py while this gate
    watched only executions. The gate generalised the failure and not the scope,
    which is a quieter version of the mistake it exists to catch. So the scope is
    now itself asserted: a new route module that consumes a read model fails here
    until someone decides whether it needs gating.
    """
    watched = {route_dir for route_dir, _, _ in _PAIRS}
    consumers: list[str] = []
    for path in sorted(_ROUTES_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if "read_models" not in path.read_text():
            continue
        rel = path.relative_to(_ROUTES_ROOT)
        if rel.parts[0] in watched:
            continue
        consumers.append(rel.as_posix())

    unexplained = sorted(set(consumers) - set(_NO_PAIR))
    assert not unexplained, (
        f"these route modules consume a read model and are neither gated by _PAIRS "
        f"nor excused in _NO_PAIR: {unexplained}. Add the source-to-response pair, "
        f"or record why the mapping is not a flat copy."
    )

    stale = sorted(set(_NO_PAIR) - set(consumers))
    assert not stale, (
        f"_NO_PAIR excuses modules that no longer consume a read model: {stale}. "
        f"An excuse for a case that cannot arise hides nothing; remove it."
    )
