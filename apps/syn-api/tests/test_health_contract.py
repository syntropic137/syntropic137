"""/health publishes a closed, fully declared schema — and one that matches its producers.

WHY THIS FILE EXISTS. The first cut of #1380 typed the new ``build`` block and
left ``HealthResponse`` on ``extra="allow"``. That produced
``additionalProperties: true`` in ``openapi.json`` and an ``[key: string]:
unknown`` index signature in the generated CLI types: the endpoint was "typed"
while every field `syn health` actually reads — ``subscription``,
``codex_auth``, ``degraded_reasons``, ``warnings`` — was invisible to every
generated consumer, and a probe could change shape without the API-drift check
seeing anything. An open model is a contract that says nothing, which is the
same failure as the ``"0.5.1"`` literal one layer up: present, and therefore
trusted, and therefore worse than absent.

THE SECOND RISK THIS PINS is the price of closing it. The ``subscription`` block
is FLAT on the wire, so ``ReadModelLag``'s fields had to be restated on
``SubscriptionHealth`` to be visible in the schema — and a restatement is a
second home that drifts the first time someone adds a lag signal. Same for the
status vocabulary, which ``read_path_health`` owns. Both are asserted against
their producers here, so the drift fails CI instead of quietly dropping a field
from the payload.
"""

from __future__ import annotations

import typing

import pytest

from syn_adapters.subscriptions.read_model_lag import ReadModelLag
from syn_api.main import create_app
from syn_api.services.read_path_health import _ReadPathStatus
from syn_api.types import HealthResponse, SubscriptionHealth

#: Field names on ``SubscriptionHealth`` that come from the service's own status
#: rather than from a lag measurement. Everything else on it must be a
#: ``ReadModelLag`` field — see ``test_the_flat_lag_fields_match_read_model_lag``.
_SERVICE_STATUS_FIELDS = frozenset({"status", "running", "projection_count", "realtime_enabled"})


def _schema(name: str) -> dict:
    """One component schema out of the live OpenAPI document."""
    return create_app().openapi()["components"]["schemas"][name]


@pytest.mark.unit
def test_health_forbids_undeclared_fields() -> None:
    """The model refuses what it did not declare, at runtime and not only on paper."""
    assert HealthResponse.model_config["extra"] == "forbid"
    assert SubscriptionHealth.model_config["extra"] == "forbid"


@pytest.mark.unit
def test_the_published_schema_is_closed() -> None:
    """``additionalProperties: true`` is what an open model puts in the spec.

    Asserted on the generated document rather than on ``model_config``, because
    the spec is what ``openapi-typescript`` reads and therefore what decides
    whether the CLI can see these fields at all.
    """
    for name in ("HealthResponse", "SubscriptionHealth", "BuildInfo"):
        assert _schema(name).get("additionalProperties") is not True, name


@pytest.mark.unit
def test_every_field_health_reports_is_named_in_the_schema() -> None:
    """The blocks the CLI and the deploy runbook read, visible to a generated client.

    Named one by one rather than compared to ``model_fields``: a list derived
    from the model would agree with the model however wrong the model was, and
    the defect was a model that described less than the endpoint sent.
    """
    properties = _schema("HealthResponse")["properties"]

    assert set(properties) >= {
        "status",
        "mode",
        "build",
        "degraded_reasons",
        "subscription",
        "codex_auth",
        "warnings",
    }


@pytest.mark.unit
def test_the_flat_lag_fields_match_read_model_lag() -> None:
    """``SubscriptionHealth`` restates ``ReadModelLag``; the restatement must stay honest.

    The block is flat on the wire, so the lag fields cannot simply be a nested
    ``ReadModelLag`` reference. Add a signal there and this fails until it is
    published here too — which is the whole reason the duplication is allowed.
    """
    restated = set(SubscriptionHealth.model_fields) - _SERVICE_STATUS_FIELDS

    assert restated == set(ReadModelLag.model_fields)


@pytest.mark.unit
def test_the_status_vocabulary_covers_every_verdict() -> None:
    """``read_path_health`` decides these words; /health only publishes them.

    ``unknown`` is /health's own addition — the probe failed and there is no
    verdict — so the assertion is containment, not equality.
    """
    published = set(typing.get_args(SubscriptionHealth.model_fields["status"].annotation))

    assert set(typing.get_args(_ReadPathStatus)) <= published
    assert "unknown" in published
