"""The control API must say that `state` is a pre-signal reading (#1062).

Pause, resume, cancel and inject all queue a signal and return immediately. The
controller fills `ControlResult.new_state` from a state machine it read *before*
enqueueing, and the route maps that straight onto `ControlResponse.state`. So a
successful cancel of a live execution answers `state: "running"`, and a read
issued straight afterwards answers `running` too.

That is correct behaviour and a dishonest interface. #1062 was filed after a
session nearly reported two executions as refusing to cancel on the strength of
one post-cancel read.

The fix is a contract, not a value, so this guards the artifact the contract
travels in: the OpenAPI schema. That schema is what Fumadocs renders on the API
page and what `openapi-typescript` turns into the CLI and dashboard types, so a
description that fails to reach it reaches no consumer at all. Asserting on
`ControlResponse.model_fields` instead would pass on a description FastAPI never
published - a docstring, say.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI

from syn_api.routes.executions.control import router

pytestmark = pytest.mark.unit

CONTROL_OPERATIONS = [
    "/executions/{execution_id}/pause",
    "/executions/{execution_id}/resume",
    "/executions/{execution_id}/cancel",
    "/executions/{execution_id}/inject",
]


@dataclass(frozen=True)
class PublishedContract:
    """The prose the control router actually publishes, keyed as a client meets it."""

    state_description: str
    operation_descriptions: dict[str, str]


@pytest.fixture(scope="module")
def contract() -> PublishedContract:
    """Read the spec FastAPI generates from the router, not the committed copy.

    The committed `apps/syn-docs/openapi.json` is downstream of this and already
    has its own drift gate (`just codegen-check`); reading it here would test the
    generator's last run rather than the source of truth.
    """
    app = FastAPI()
    app.include_router(router)
    spec = app.openapi()

    state_property = spec["components"]["schemas"]["ControlResponse"]["properties"]["state"]
    return PublishedContract(
        state_description=str(state_property.get("description", "")),
        operation_descriptions={
            path: str(spec["paths"][path]["post"].get("description", ""))
            for path in CONTROL_OPERATIONS
        },
    )


def test_state_is_documented_as_the_reading_taken_before_the_signal(
    contract: PublishedContract,
) -> None:
    """Without a description the field is published as a bare string named
    `state`, which every client reads as the command's outcome."""
    description = contract.state_description

    assert description, (
        "ControlResponse.state has no description, so the OpenAPI spec, the "
        "generated API docs page and both generated TypeScript clients all "
        "present it as an unqualified `state` (#1062)"
    )
    assert "before" in description.lower(), (
        f"the description must say the value is read BEFORE the signal is "
        f"queued, otherwise it does not close #1062; got: {description!r}"
    )


@pytest.mark.parametrize("path", CONTROL_OPERATIONS)
def test_each_control_operation_declares_that_it_is_asynchronous(
    contract: PublishedContract, path: str
) -> None:
    """A caller lands on one operation's anchor, not on the schema page, so each
    must stand alone - and all four share the defect, not cancel alone."""
    description = contract.operation_descriptions[path]

    assert "asynchronous" in description.lower(), (
        f"POST {path} does not tell the caller it is asynchronous; its docstring "
        f"is the only prose on the generated docs page. Got: {description!r}"
    )
