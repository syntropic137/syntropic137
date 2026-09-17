"""A response field the DTO does not carry is advertised and always fake.

`SessionCostResponse` declared `workspace_id`, `compute_cost_usd`,
`tokens_by_tool` and `cost_by_tool_tokens`. `SessionCostData` declared none of
them, so `_session_cost_to_api` had nothing to pass and pydantic filled in
`None`, `0`, `{}`, `{}` on every response - forever, and silently. The OpenAPI
spec advertised four real fields; the CLI generated types for them; they were
never anything but defaults (#1041).

This is a bug class, not a bug. The identical thing happened one field-set over
on `ExecutionCostData` first (see the module docstring of `test_api_costs.py`:
"An execution reported 0 cache reads while its own session reported 144,640"),
was fixed with a unit test on that one mapper, and then recurred on the session
side because nothing measured the SHAPE. Any DTO can lose a field the next time
either side gains one, and the failure mode is a plausible-looking default
rather than an error.

So the two tests below are about the mapping chain itself, not about four
fields:

`test_the_dto_declares_every_field_its_response_declares` compares field sets.
It fails the moment a response model grows a field the DTO cannot carry -
including a field nobody has written a mapper line for yet.

`test_no_response_field_is_left_at_its_default` is the stronger one, because
field parity alone does not mean the value moves: a mapper can declare the
field on both sides and still forget to pass it, which is precisely what a
hand-written constructor call invites. It pushes a source read model with
EVERY field set to a distinctive non-default value through the real mapper
chain and asserts that nothing arrives at its declared default. A field
dropped at either hop lands on its default and names itself.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_api.routes.costs import (
    ExecutionCostResponse,
    SessionCostResponse,
    _execution_cost_to_api,
    _session_cost_to_api,
    execution_cost_to_data,
    session_cost_to_data,
)
from syn_api.types import ExecutionCostData, SessionCostData
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import (
    CostField,
    SessionCost,
)
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pydantic import BaseModel

os.environ.setdefault("APP_ENVIRONMENT", "test")

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Chain:
    """One read model -> DTO -> response chain, end to end.

    Holds the two real mapper functions rather than a description of them, so
    the tests exercise production code and cannot drift from it.
    """

    name: str
    source: object
    """A read model instance with every field set to a non-default value."""

    to_data: Callable[..., BaseModel]
    to_api: Callable[..., BaseModel]
    dto: type[BaseModel]
    response: type[BaseModel]

    #: Response fields the DTO deliberately does not carry, each with a reason.
    #: An empty mapping is the healthy state - "not carried" is exactly the bug
    #: this file exists to catch, so every entry here has to be argued for.
    exempt: Mapping[str, str] = dataclasses.field(default_factory=dict)

    def through_the_chain(self) -> BaseModel:
        return self.to_api(self.to_data(self.source))


#: Distinctive, non-default values for every field. Nothing here is a default:
#: a field asserted in its default direction would pass with its mapper line
#: deleted, which is the tautology this whole file exists to avoid.
_SESSION = SessionCost(
    session_id="sess-1041",
    execution_id="exec-1041",
    workflow_id="wf-1041",
    phase_id="implement",
    workspace_id="ws-1041",
    total_cost_usd=Decimal("1.234567"),
    token_cost_usd=Decimal("1.134567"),
    compute_cost_usd=Decimal("0.1"),
    input_tokens=16229,
    output_tokens=1535,
    cache_creation_tokens=4096,
    cache_read_tokens=144640,
    tool_calls=10,
    turns=7,
    duration_ms=36000.0,
    cost_by_model={"claude-opus-5": Decimal("1.134567")},
    cost_by_tool={"Bash": Decimal("0.05")},
    tokens_by_tool={"Bash": 512},
    cost_by_tool_tokens={"Bash": Decimal("0.0031")},
    agent_model="claude-opus-5",
    unpriced_observation_count=3,
    #: A PROPER SUBSET of the default (which is every member). A fixture using
    #: the full set would pass with the mapper line deleted, and the empty set
    #: is not reachable today - no producer measures all three.
    unmeasured_fields=frozenset({CostField.TOKENS_BY_TOOL}),
    is_finalized=True,
    started_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
    completed_at=datetime(2026, 9, 17, 10, 30, tzinfo=UTC),
)

_EXECUTION = ExecutionCost(
    execution_id="exec-1041",
    workflow_id="wf-1041",
    session_count=2,
    session_ids=["sess-a", "sess-b"],
    total_cost_usd=Decimal("2.469134"),
    token_cost_usd=Decimal("2.269134"),
    compute_cost_usd=Decimal("0.2"),
    input_tokens=32458,
    output_tokens=3070,
    cache_creation_tokens=8192,
    cache_read_tokens=289280,
    tool_calls=20,
    turns=14,
    duration_ms=72000.0,
    cost_by_phase={"implement": Decimal("2.269134")},
    cost_by_model={"claude-opus-5": Decimal("2.269134")},
    cost_by_tool={"Bash": Decimal("0.1")},
    models_by_phase={"implement": ["claude-opus-5"]},
    unpriced_by_phase={"implement": 3},
    unpriced_observation_count=3,
    is_complete=True,
    started_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
    completed_at=datetime(2026, 9, 17, 10, 30, tzinfo=UTC),
)


_CHAINS: tuple[_Chain, ...] = (
    _Chain(
        name="session",
        source=_SESSION,
        to_data=session_cost_to_data,
        to_api=_session_cost_to_api,
        dto=SessionCostData,
        response=SessionCostResponse,
    ),
    _Chain(
        name="execution",
        source=_EXECUTION,
        to_data=execution_cost_to_data,
        to_api=_execution_cost_to_api,
        dto=ExecutionCostData,
        response=ExecutionCostResponse,
    ),
)

_CHAIN_IDS = tuple(c.name for c in _CHAINS)


def _fields_at_their_default(model: BaseModel) -> list[str]:
    """Fields whose value is indistinguishable from the declared default.

    This is the whole signal: a value that never arrived and a value that
    happens to equal the default look identical on the wire, which is why the
    fixtures above set nothing to a default.
    """
    stuck: list[str] = []
    for name, info in type(model).model_fields.items():
        if info.is_required():
            continue
        default = info.get_default(call_default_factory=True)
        value = getattr(model, name)
        if type(value) is type(default) and value == default:
            stuck.append(name)
    return stuck


def test_every_mapper_in_the_module_is_registered_as_a_chain() -> None:
    """A chain nobody registered is a chain nobody tests.

    The tests below only measure what `_CHAINS` lists, so a third DTO ->
    response mapper added to `costs.py` would be covered by nothing while this
    file still reads as coverage - a gate whose number cannot move is the
    failure mode this repo has been bitten by before (#1188). Discovering the
    mappers from the module instead of trusting the list makes adding one
    fail here until it is registered.
    """
    import syn_api.routes.costs as costs_module

    in_module = {
        name
        for name in dir(costs_module)
        if name.endswith("_to_api") and callable(getattr(costs_module, name))
    }
    registered = {c.to_api.__name__ for c in _CHAINS}

    assert in_module == registered, (
        f"unregistered DTO -> response mappers in costs.py: "
        f"{sorted(in_module - registered)}. Add each to _CHAINS with a source "
        f"fixture, or it is tested by nothing."
    )


@pytest.mark.parametrize("chain", _CHAINS, ids=_CHAIN_IDS)
def test_the_fixture_covers_every_field_on_the_read_model(chain: _Chain) -> None:
    """A new field on the read model fails HERE first.

    Without this, the round-trip below silently stops covering whatever was
    added - the same silence, one level up.
    """
    unset = [
        f.name
        for f in dataclasses.fields(chain.source)  # type: ignore[arg-type]
        if getattr(chain.source, f.name) == _default_of(f)
    ]
    assert not unset, (
        f"{chain.name}: fixture leaves {unset} at the read model default, so a "
        f"mapper that drops them would still pass"
    )


def _default_of(f: dataclasses.Field[object]) -> object:
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:
        return f.default_factory()
    return object()  # required field: never equal to anything


@pytest.mark.parametrize("chain", _CHAINS, ids=_CHAIN_IDS)
def test_the_dto_declares_every_field_its_response_declares(chain: _Chain) -> None:
    """Structural: the response may not advertise what the DTO cannot carry.

    Fails when either side gains a field the other lacks, which is the moment
    the defect is introduced rather than the moment someone notices a zero.
    """
    missing = set(chain.response.model_fields) - set(chain.dto.model_fields)
    unjustified = sorted(missing - set(chain.exempt))

    assert not unjustified, (
        f"{chain.name}: {chain.response.__name__} declares {unjustified}, which "
        f"{chain.dto.__name__} does not carry. The API will advertise these "
        f"fields and serve their defaults forever (#1041). Add them to the DTO "
        f"and both mappers, or record a reason in the chain's `exempt`."
    )


@pytest.mark.parametrize("chain", _CHAINS, ids=_CHAIN_IDS)
def test_no_response_field_is_left_at_its_default(chain: _Chain) -> None:
    """Behavioural: parity is not delivery.

    A mapper can declare a field on both sides and still not pass it. Every
    field here came off a source object that set it to something distinctive,
    so anything sitting on its default was dropped at one of the two hops.
    """
    response = chain.through_the_chain()

    stuck = sorted(set(_fields_at_their_default(response)) - set(chain.exempt))

    assert not stuck, (
        f"{chain.name}: {sorted(stuck)} arrived at the default despite the "
        f"source setting every field. Dropped by {chain.to_data.__name__} or "
        f"{chain.to_api.__name__}."
    )


class TestTheFourFieldsThatWereActuallyDropped:
    """One case per dropped field, so a regression names itself.

    The generic tests above catch the class; these say what broke (#1041).
    """

    @staticmethod
    def _response() -> SessionCostResponse:
        result = _session_cost_to_api(session_cost_to_data(_SESSION))
        assert isinstance(result, SessionCostResponse)
        return result

    def test_workspace_id_reaches_the_api(self) -> None:
        assert self._response().workspace_id == "ws-1041"

    def test_compute_cost_usd_reaches_the_api(self) -> None:
        assert self._response().compute_cost_usd == Decimal("0.1")

    def test_tokens_by_tool_reaches_the_api(self) -> None:
        assert self._response().tokens_by_tool == {"Bash": 512}

    def test_cost_by_tool_tokens_reaches_the_api(self) -> None:
        """Stringified like its Decimal-valued siblings, not left as Decimal."""
        assert self._response().cost_by_tool_tokens == {"Bash": "0.0031"}
