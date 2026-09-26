"""No run-time API surface may present a model ALIAS as the model (ADR-067 D9).

Aliases (opus, sonnet, haiku, fable, gpt-sol) are requests. Only workflow
DEFINITION responses may carry them as ``model``. Everything else carries the
harness-reported id (or null) and puts the alias in ``requested_model``.

Two guards:

1. Structural: every field whose name mentions ``model`` on every pydantic
   model the API serves must be typed ``ObservedModelId`` (or keyed by
   ``CostModelKey`` for a map), unless it is a definition field, a request
   field or a display string. A new ``agent_model: str`` fails here.
2. Behavioural: those types reject every alias.
"""

from __future__ import annotations

import types
import typing
from typing import TYPE_CHECKING

import pytest
from pydantic import AfterValidator, BaseModel, ValidationError

import syn_api.main  # noqa: F401 - imports every route module, registering all response models
from syn_api import model_identity
from syn_api.model_identity import (  # noqa: TC001 - pydantic resolves _Probe at runtime
    CostModelKey,
    ObservedModelId,
)
from syn_shared.agents import CodexModelAlias, ModelAlias

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_ALIASES = sorted({*ModelAlias, *CodexModelAlias})

#: (class name, field) pairs that legitimately carry an alias: workflow
#: DEFINITION surfaces and requests. Adding a run-time field here defeats the
#: whole guard - put the alias in `requested_model` instead.
_DEFINITION_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("PhaseDefinitionResponse", "model"),
        ("UpdatePhasePromptRequest", "model"),
    }
)


def _is_exempt_name(field: str) -> bool:
    return field == "requested_model" or field.endswith("_display") or "model" not in field


def _all_models() -> Iterator[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    stack: list[type[BaseModel]] = list(BaseModel.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
        if cls.__module__.startswith("syn_api"):
            yield cls


def _is_guarded(tp: object) -> bool:
    """True when ``tp`` (or every non-None member of it) carries the alias check."""
    if typing.get_origin(tp) is typing.Annotated:
        return any(
            isinstance(m, AfterValidator) and m.func is model_identity._reject_alias  # pyright: ignore[reportPrivateUsage]
            for m in getattr(tp, "__metadata__", ())
        )
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (typing.Union, types.UnionType):
        members = [a for a in args if a is not type(None)]
        return bool(members) and all(_is_guarded(a) for a in members)
    if origin in (dict, typing.Mapping) and args:
        return _is_guarded(args[0])
    if origin in (list, tuple, set, frozenset) and args:
        inner = args[0]
        return isinstance(inner, type) and issubclass(inner, BaseModel)
    return isinstance(tp, type) and issubclass(tp, BaseModel)


def _unguarded_fields() -> list[str]:
    offenders: list[str] = []
    for cls in _all_models():
        for name, info in cls.model_fields.items():
            if _is_exempt_name(name) or (cls.__name__, name) in _DEFINITION_FIELDS:
                continue
            guarded_by_metadata = any(
                isinstance(m, AfterValidator) and m.func is model_identity._reject_alias  # pyright: ignore[reportPrivateUsage]
                for m in info.metadata
            )
            if not (guarded_by_metadata or _is_guarded(info.annotation)):
                offenders.append(f"{cls.__module__}.{cls.__name__}.{name}: {info.annotation}")
    return sorted(offenders)


def test_every_runtime_model_field_rejects_aliases() -> None:
    offenders = _unguarded_fields()
    assert offenders == [], (
        "Run-time model fields must be typed ObservedModelId / dict[CostModelKey, ...] "
        "(ADR-067 D9); definition fields go in _DEFINITION_FIELDS:\n" + "\n".join(offenders)
    )


def test_definition_allowlist_has_no_stale_entries() -> None:
    present = {(cls.__name__, name) for cls in _all_models() for name in cls.model_fields}
    assert present >= _DEFINITION_FIELDS


class _Probe(BaseModel):
    model: ObservedModelId | None = None
    cost_by_model: dict[CostModelKey, str] = {}


@pytest.mark.parametrize("alias", _ALIASES)
def test_observed_model_rejects_alias(alias: str) -> None:
    with pytest.raises(ValidationError):
        _Probe(model=alias)


@pytest.mark.parametrize("alias", _ALIASES)
def test_cost_key_rejects_alias(alias: str) -> None:
    with pytest.raises(ValidationError):
        _Probe(cost_by_model={alias: "1"})


def test_explicit_ids_and_unknown_key_pass() -> None:
    probe = _Probe(
        model="claude-opus-5-5",
        cost_by_model={"gpt-6-sol": "1", "unattributed-model": "2"},
    )
    assert probe.model == "claude-opus-5-5"
