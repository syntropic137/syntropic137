"""Refuse a query parameter no route declares (#1313).

An undeclared query parameter used to be dropped, not refused, so
``?definitely_not_a_param=1`` returned 200 and an UNFILTERED page. The caller
could not tell "this filter is not supported" from "this filter matched
everything", and the failure is directional: it always returns MORE rows than
were asked for, and always looks like it worked. An agent asking for one
execution's artifacts got every execution's artifacts with nothing to
distrust.

That is a class, not an endpoint. #1263 and #1306 were each closed by adding
the one missing parameter to the one route that was asked about, which fixes
the symptom and leaves every other route -- and every route added afterwards
-- exposed the same way. So this is registered ONCE, as a global dependency in
``create_app()``, and covers every route the app will ever serve including the
ones not written yet.

Why a dependency and not middleware or a route class:

- ASGI middleware cannot do it. ``scope["route"]`` is set during routing,
  which happens inside the app a middleware wraps, so by the time the matched
  route is readable the handler has already run and answered.
- A ``route_class`` cannot do it in one place. ``APIRouter.include_router``
  passes ``route_class_override=type(route)``, so a class set on the app's own
  router never reaches routes that arrive from an included router -- which is
  all of them here.

A global dependency is solved after the route is matched and before the
endpoint runs, which is exactly the window this check needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status
from fastapi.routing import APIRoute
from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi.dependencies.models import Dependant

UNKNOWN_QUERY_PARAMETER = "unknown_query_parameter"
"""``type`` discriminator on each error entry, mirroring Pydantic's own."""


class UnknownQueryParameterContext(BaseModel):
    """The accepted keys, machine-readable so a caller need not parse prose."""

    accepted: list[str]


class UnknownQueryParameterDetail(BaseModel):
    """One rejected key, shaped like the validation errors FastAPI emits.

    Same ``type``/``loc``/``msg``/``ctx`` quartet Pydantic produces, so a
    client already reading ``detail[].loc`` to find the offending field reads
    this one unchanged. That shape is the concrete reason for 422 over 400: a
    400 would have to invent a second error format for what is the same kind
    of failure -- the request named something the endpoint does not accept.
    """

    type: str = UNKNOWN_QUERY_PARAMETER
    loc: tuple[str, str]
    msg: str
    ctx: UnknownQueryParameterContext


def _declared_query_keys(dependant: Dependant) -> set[str]:
    """Every query key *dependant* and its sub-dependencies bind, by wire name.

    Three things make the wire name differ from the parameter name, and all
    three are silent if you get them wrong -- a valid request would be
    refused, which is worse than the bug being fixed:

    - ``Query(alias=...)`` renames the key, so ``alias`` is what arrives.
    - ``Depends()`` nests: a sub-dependency's parameters are just as declared
      as the endpoint's own, so the walk has to recurse.
    - A Pydantic model annotated with ``Query()`` binds its FIELDS, not the
      parameter's own name, so it expands rather than contributing one key.
    """
    keys: set[str] = set()

    for field in dependant.query_params:
        annotation = field.field_info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            keys.update(
                model_field.alias or name
                for name, model_field in annotation.model_fields.items()
            )
        else:
            keys.add(field.alias)

    for sub_dependant in dependant.dependencies:
        keys |= _declared_query_keys(sub_dependant)

    return keys


def reject_unknown_query_params(request: Request) -> None:
    """Fail the request with 422 if it carries a key its route does not declare.

    ``Request`` is imported at runtime on purpose. Under
    ``from __future__ import annotations`` FastAPI resolves this annotation to
    decide the parameter is the request object; behind ``TYPE_CHECKING`` it
    cannot, and silently binds ``request`` as a required QUERY parameter --
    which 422s every request to every route.

    Registered once, globally, in ``create_app()`` -- endpoints do not opt in
    and cannot opt out, which is the only arrangement that also covers the
    endpoint added next month.

    The body names every unknown key and lists the accepted ones, so a caller
    that guessed wrong can correct itself in one step instead of bisecting its
    own query string. All offending keys are reported at once for the same
    reason.
    """
    route = request.scope.get("route")
    if not isinstance(route, APIRoute):
        # Not a route whose contract we can read (plain Starlette routes such
        # as /docs and /openapi.json). Nothing is declared, so nothing can be
        # judged undeclared.
        return

    accepted = _declared_query_keys(route.dependant)
    unknown = sorted(set(request.query_params.keys()) - accepted)
    if not unknown:
        return

    accepted_listing = ", ".join(sorted(accepted)) if accepted else "(none)"
    context = UnknownQueryParameterContext(accepted=sorted(accepted))
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=[
            UnknownQueryParameterDetail(
                loc=("query", key),
                msg=(
                    f"Unknown query parameter '{key}'. "
                    f"Accepted query parameters: {accepted_listing}."
                ),
                ctx=context,
            ).model_dump()
            for key in unknown
        ],
    )
