"""Fitness function: no route accepts a query parameter it does not declare.

An undeclared query parameter used to be dropped, not refused, so a filter
that does not exist read as a filter that matched everything -- 200 and an
UNFILTERED page, with nothing in the response for the caller to distrust
(#1313). The failure is directional: it always returns MORE than was asked
for, and always looks like it worked.

WHY THIS IS A FITNESS FUNCTION AND NOT A TEST BESIDE THE FIX. #1263 and #1306
were each the same defect, and each was closed by adding the one missing
parameter to the one endpoint that was asked about. Both left every other
route exposed, and neither could have caught the next endpoint added. What
makes this a whole-codebase property rather than a behavioural assertion about
one code path is that the subject is "every route, including the ones not
written yet" -- so the test DISCOVERS its own subjects from the live app
rather than listing them. Add a route with this defect and this fails without
anyone remembering to extend it. That is the whole point; a hand-maintained
list would have the same half-life as the two fixes above.

WHY THIS ONE BOOTS THE APP. Every other fitness function here is static AST or
regex analysis over source files. This one cannot be: the property is
"the running app answers 4xx", and whether a parameter is declared is decided
by FastAPI's dependency graph at route-construction time, not by anything
visible in a source file. Reading the source could only re-implement
``get_dependant`` and would drift from it silently -- which is the failure mode
this gate exists to prevent, one level up. ``APP_ENVIRONMENT=test`` selects the
in-memory adapters, so no external service is needed.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")

from fastapi import FastAPI  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from syn_api.main import create_app  # noqa: E402
from syn_api.strict_query import UNKNOWN_QUERY_PARAMETER  # noqa: E402

pytestmark = [pytest.mark.architecture, pytest.mark.unit]

#: A parameter no endpoint could plausibly declare. The literal from the
#: issue's reproduction, kept verbatim so a reader can match the two.
INVENTED_PARAM = "definitely_not_a_param"

#: Stand-in for any path parameter. The value never has to resolve: a global
#: dependency is solved BEFORE the endpoint body runs, so the rejection does
#: not depend on the entity existing. That independence is what lets this gate
#: cover every route without fixtures or a database.
_PATH_PARAM_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"

#: Routes whose presence proves discovery actually worked. A discovery bug that
#: returned an empty or truncated list would make every assertion below vacuous
#: -- a green check over nothing, which is the failure this file is guarding
#: against in the first place. These are the list endpoints named in #1313 and
#: its two predecessors.
_MUST_BE_DISCOVERED = frozenset(
    {
        "/artifacts",
        "/sessions",
        "/executions",
        "/workflows",
        "/organizations",
        "/systems",
        "/repos",
        "/skills",
        "/metrics",
        "/triggers",
    }
)


def _concrete_url(path_template: str) -> str:
    """A requestable URL for *path_template*, path parameters filled in."""
    url = path_template
    while "{" in url:
        start = url.index("{")
        end = url.index("}", start)
        url = url[:start] + _PATH_PARAM_PLACEHOLDER + url[end + 1 :]
    return url


def _get_routes(app: FastAPI) -> list[APIRoute]:
    """Every GET route the app serves, as (path, route) discovered live."""
    return sorted(
        (
            route
            for route in app.routes
            if isinstance(route, APIRoute) and "GET" in (route.methods or set())
        ),
        key=lambda route: route.path,
    )


def _advertised_query_params(app: FastAPI) -> dict[str, set[str]]:
    """Query parameter names the OpenAPI spec publishes, per GET path.

    The independent second opinion this gate compares the error body against.
    ``parameters`` may be absent entirely for a route that declares none, which
    is a legitimate answer and means the empty set, not a missing entry.
    """
    spec = app.openapi()
    advertised: dict[str, set[str]] = {}
    for path, operations in spec.get("paths", {}).items():
        operation = operations.get("get")
        if operation is None:
            continue
        advertised[path] = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
        }
    return advertised


_APP = create_app()
_ROUTES = _get_routes(_APP)
_ROUTE_PATHS = [route.path for route in _ROUTES]
_ADVERTISED_QUERY_PARAMS = _advertised_query_params(_APP)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(_APP)


def test_discovery_found_the_documented_list_endpoints() -> None:
    """Guard the guard: an empty discovery would pass every test below."""
    missing = _MUST_BE_DISCOVERED - set(_ROUTE_PATHS)
    assert not missing, (
        f"Route discovery did not find {sorted(missing)}. Either these endpoints "
        f"were removed (update _MUST_BE_DISCOVERED) or discovery is broken, in "
        f"which case every assertion in this file is passing over nothing."
    )


@pytest.mark.parametrize("path", _ROUTE_PATHS)
def test_get_route_rejects_an_invented_query_parameter(
    client: TestClient, path: str
) -> None:
    """Every GET route refuses a parameter it does not declare.

    Not just the list endpoints: the defect is that an undeclared parameter is
    dropped, and nothing about that is specific to a route returning a
    collection. Covering every GET route is the same assertion with no
    carve-out for the routes nobody has filed an issue about yet.
    """
    response = client.get(_concrete_url(path), params={INVENTED_PARAM: "1"})

    assert response.status_code == 422, (
        f"GET {path} answered {response.status_code} to ?{INVENTED_PARAM}=1. "
        f"An undeclared parameter must be refused, not dropped -- dropping it "
        f"returns an unfiltered page that looks like a filtered one (#1313)."
    )


@pytest.mark.parametrize("path", _ROUTE_PATHS)
def test_rejection_names_the_unknown_key_and_lists_the_accepted_ones(
    client: TestClient, path: str
) -> None:
    """The body has to be enough to correct the request in one step.

    Naming the bad key without listing the accepted ones leaves a caller
    guessing a second time; listing the accepted ones without naming the bad
    key leaves them diffing their own query string. An agent needs both, from
    one response.
    """
    response = client.get(_concrete_url(path), params={INVENTED_PARAM: "1"})
    detail = response.json()["detail"]

    entries = [e for e in detail if e.get("type") == UNKNOWN_QUERY_PARAMETER]
    assert entries, f"GET {path}: no {UNKNOWN_QUERY_PARAMETER} entry in {detail}"

    entry = entries[0]
    assert entry["loc"] == ["query", INVENTED_PARAM], (
        f"GET {path}: loc must point at the offending key, got {entry['loc']}"
    )
    assert INVENTED_PARAM in entry["msg"], (
        f"GET {path}: message does not name the unknown key: {entry['msg']}"
    )

    # Checked against the OpenAPI spec rather than against the enforcement's
    # own view of the route. Comparing the mechanism to itself would pass
    # however wrong both were; the spec is built by a different FastAPI code
    # path and is the published contract -- it is what generates the CLI's
    # types. If the two disagree, either the error is lying to the caller or
    # the spec is, and both are defects worth failing over.
    advertised = _ADVERTISED_QUERY_PARAMS[path]
    assert entry["ctx"]["accepted"] == sorted(advertised), (
        f"GET {path}: the accepted list in the error, "
        f"{entry['ctx']['accepted']}, disagrees with the query parameters the "
        f"OpenAPI spec advertises for this route, {sorted(advertised)}."
    )
    for key in advertised:
        assert key in entry["msg"], (
            f"GET {path}: accepted parameter '{key}' is missing from the "
            f"message, so a caller cannot correct itself from it: {entry['msg']}"
        )


@pytest.mark.parametrize(
    ("path", "params"),
    [
        # Values a route declares. If the mechanism mis-read the dependency
        # graph it would refuse these, which is a worse bug than the one being
        # fixed -- so these are the negative control, not padding.
        ("/artifacts", {"execution_id": "e1", "limit": "5"}),
        ("/artifacts", {"session_id": "s1", "artifact_type": "log"}),
        ("/sessions", {"execution_id": "e1", "statuses": "running"}),
        ("/executions", {"page": "2", "page_size": "10", "q": "x"}),
        ("/workflows", {"include_archived": "true", "order_by": "name"}),
        ("/repos", {"organization_id": "o1", "unassigned": "true"}),
    ],
)
def test_declared_parameters_are_not_refused(
    client: TestClient, path: str, params: dict[str, str]
) -> None:
    """A parameter the route DOES declare must still be accepted."""
    response = client.get(path, params=params)

    assert response.status_code != 422, (
        f"GET {path}?{params} was refused as unknown, but every key there is "
        f"declared. Body: {response.text[:400]}"
    )
