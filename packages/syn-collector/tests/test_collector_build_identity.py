"""The collector must name the build it is running, and name it correctly (#1380).

The same defect the API had, on the service deployed beside it: ``create_app``
passed ``version="0.1.0"`` to FastAPI, so ``openapi.json`` named a build that
had not been current since the package was created, and ``/health`` reported
only ``status``. A wrong version served over HTTP is worse than none — a client
reading it is misled rather than blocked — and the only remaining way to
identify a running collector was ``docker inspect`` over SSH.

Compared against ``importlib.metadata.version("syn-collector")`` rather than a
literal, because a literal in a test is the same mistake as a literal in the
source: it passes for every release it has drifted through.

Asserted on the serialized payload and on ``app.openapi()``, not on
``collector_version()``, since the way this realistically breaks is the value
being computed correctly and lost at the response model or at the one argument
that is passed once at app construction.
"""

from __future__ import annotations

from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient

from syn_collector.collector.service import create_app
from syn_collector.collector.store import InMemoryObservabilityStore

#: The running release, by the only definition that cannot drift.
INSTALLED = version("syn-collector")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(store=InMemoryObservabilityStore()))


@pytest.mark.unit
def test_health_reports_the_installed_release(client: TestClient) -> None:
    assert client.get("/health").json()["version"] == INSTALLED


@pytest.mark.unit
def test_openapi_info_version_is_the_installed_release() -> None:
    """The half that was wrong rather than absent."""
    app = create_app(store=InMemoryObservabilityStore())

    assert app.openapi()["info"]["version"] == INSTALLED


@pytest.mark.unit
def test_health_and_openapi_cannot_disagree(client: TestClient) -> None:
    """Equal to each other AND to the package: equality alone would still hold
    if both went back to sharing one constant, which is the arrangement that
    produced the bug."""
    app = create_app(store=InMemoryObservabilityStore())

    assert client.get("/health").json()["version"] == app.openapi()["info"]["version"] == INSTALLED
