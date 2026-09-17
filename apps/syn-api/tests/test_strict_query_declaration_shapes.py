"""How ``reject_unknown_query_params`` decides what a route declares.

The fitness function in ``ci/fitness/api/test_unknown_query_params_rejected.py``
asserts the property over every route the app actually serves. It cannot cover
these three shapes, because no route uses them YET:

- ``Query(alias=...)``     -- the wire key differs from the parameter name
- ``Depends()``            -- a sub-dependency's parameters are declared too
- a model bound to ``Query()`` -- the MODEL'S fields are the keys, not the
  parameter's own name

Each is a normal thing to write, and each fails in the dangerous direction if
the mechanism gets it wrong: a VALID request refused as unknown. That is worse
than the bug #1313 fixed -- the caller is now blocked rather than misinformed
-- and it would appear the day someone adds a ``Depends()`` to a route, with
nothing in the existing suite to catch it.

These build a throwaway app rather than asserting on the helper directly, so
what is measured is what a caller experiences: the status code and body coming
back off the wire.
"""

from __future__ import annotations

import os
from typing import Annotated

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")

from fastapi import APIRouter, Depends, FastAPI, Query  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from syn_api.strict_query import (  # noqa: E402
    UNKNOWN_QUERY_PARAMETER,
    reject_unknown_query_params,
)

pytestmark = pytest.mark.unit


class WindowFilter(BaseModel):
    """A model bound to ``Query()`` -- ``after``/``before`` are the wire keys."""

    after: str | None = None
    before: str | None = None


def _paging(page: int = 1, page_size: int = 50) -> tuple[int, int]:
    """A sub-dependency. Its parameters are as declared as an endpoint's own."""
    return page, page_size


def _app() -> FastAPI:
    """An app wired exactly as ``create_app()`` wires the real one."""
    app = FastAPI(dependencies=[Depends(reject_unknown_query_params)])
    router = APIRouter()

    @router.get("/aliased")
    async def aliased(
        team: Annotated[str | None, Query(alias="team-id")] = None,
    ) -> dict[str, str]:
        return {"ok": "aliased"}

    @router.get("/nested")
    async def nested(
        paging: Annotated[tuple[int, int], Depends(_paging)],
        q: str | None = None,
    ) -> dict[str, str]:
        return {"ok": "nested"}

    @router.get("/model-bound")
    async def model_bound(window: Annotated[WindowFilter, Query()]) -> dict[str, str]:
        return {"ok": "model"}

    # Included through a sub-router, like every real route: include_router
    # passes route_class_override=type(route), which is exactly why the
    # mechanism is a global dependency and not a route class.
    app.include_router(router)
    return app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(_app())


def _unknown_keys(response: object) -> list[str]:
    """The keys a rejection names, or [] if it was not a rejection."""
    detail = response.json().get("detail")  # type: ignore[attr-defined]
    if not isinstance(detail, list):
        return []
    return [
        entry["loc"][1]
        for entry in detail
        if entry.get("type") == UNKNOWN_QUERY_PARAMETER
    ]


@pytest.mark.parametrize(
    ("path", "params"),
    [
        # The alias is the wire key, so the alias is what must be accepted.
        ("/aliased", {"team-id": "t1"}),
        # Declared by the sub-dependency, not by the endpoint signature.
        ("/nested", {"page": "2", "page_size": "10"}),
        ("/nested", {"page": "2", "q": "x"}),
        # The model's FIELDS are the keys.
        ("/model-bound", {"after": "2026-01-01", "before": "2026-02-01"}),
    ],
)
def test_declared_parameter_is_accepted(
    client: TestClient, path: str, params: dict[str, str]
) -> None:
    response = client.get(path, params=params)

    assert response.status_code == 200, (
        f"GET {path}?{params} was refused, but every key there is declared. "
        f"Refusing a valid request is the failure mode that matters most here. "
        f"Body: {response.text[:300]}"
    )


@pytest.mark.parametrize(
    ("path", "params", "expected_unknown"),
    [
        # The parameter NAME is not the wire key when an alias is set, so the
        # name must be refused and the alias accepted -- not the reverse.
        ("/aliased", {"team": "t1"}, ["team"]),
        ("/nested", {"page": "2", "nope": "1"}, ["nope"]),
        # The parameter's own name is not a key when a model is bound to it.
        ("/model-bound", {"window": "x"}, ["window"]),
        # Every offending key at once, so one response is enough to correct by.
        ("/nested", {"alpha": "1", "beta": "2"}, ["alpha", "beta"]),
    ],
)
def test_undeclared_parameter_is_refused(
    client: TestClient,
    path: str,
    params: dict[str, str],
    expected_unknown: list[str],
) -> None:
    response = client.get(path, params=params)

    assert response.status_code == 422, (
        f"GET {path}?{params} answered {response.status_code}; an undeclared "
        f"parameter must be refused, not dropped."
    )
    assert _unknown_keys(response) == expected_unknown


def test_accepted_list_expands_a_model_to_its_fields(client: TestClient) -> None:
    """The listing has to name what a caller can actually send.

    Naming the parameter (``window``) instead of its fields would send the
    caller straight back to a second 422 -- the one thing the error body is
    there to prevent.
    """
    response = client.get("/model-bound", params={"nope": "1"})

    entry = response.json()["detail"][0]
    assert entry["ctx"]["accepted"] == ["after", "before"]
    assert "after" in entry["msg"] and "before" in entry["msg"]


def test_accepted_list_includes_sub_dependency_parameters(
    client: TestClient,
) -> None:
    """A ``Depends()`` parameter is as sendable as an endpoint's own."""
    response = client.get("/nested", params={"nope": "1"})

    entry = response.json()["detail"][0]
    assert entry["ctx"]["accepted"] == ["page", "page_size", "q"]


def test_route_declaring_nothing_says_so(client: TestClient) -> None:
    """An empty accepted list must still read as an answer, not a blank."""
    app = FastAPI(dependencies=[Depends(reject_unknown_query_params)])

    @app.get("/bare")
    async def bare() -> dict[str, str]:
        return {"ok": "bare"}

    response = TestClient(app).get("/bare", params={"nope": "1"})

    assert response.status_code == 422
    entry = response.json()["detail"][0]
    assert entry["ctx"]["accepted"] == []
    assert "(none)" in entry["msg"]
