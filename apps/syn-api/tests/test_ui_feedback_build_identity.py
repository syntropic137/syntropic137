"""The vendored ui-feedback service reports one version from one source (#1389).

``ui_feedback`` carried three literal "0.1.0"s beside ``pyproject.toml``:
``__version__``, ``FastAPI(version=...)`` and the ``GET /`` payload. They
agreed, but four homes for one fact drift the first time a bump misses one, and
#1385 made this service's build something an operator reads. Every surface
that exposes a version must now say what the installed distribution says.

Lives in syn-api's tests because syn-api installs and mounts ui-feedback-api
and its own ``tests/`` directory is not collected by CI.
"""

from __future__ import annotations

import errno
import importlib
import importlib.metadata
from email.errors import MessageError
from typing import TYPE_CHECKING

import pytest
import ui_feedback
import ui_feedback.main as ui_feedback_main
from fastapi.testclient import TestClient
from ui_feedback import version as version_module

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

INSTALLED = importlib.metadata.version(version_module.PACKAGE_NAME)
_REAL_VERSION = importlib.metadata.version


@pytest.mark.unit
def test_service_version_is_the_installed_distribution() -> None:
    assert version_module.service_version() == INSTALLED


@pytest.mark.unit
def test_openapi_info_version_is_the_installed_distribution() -> None:
    assert ui_feedback_main.app.version == INSTALLED
    assert ui_feedback_main.app.openapi()["info"]["version"] == INSTALLED


@pytest.mark.unit
def test_root_payload_version_is_the_installed_distribution() -> None:
    """Through a real request; no lifespan runs, so no storage is built."""
    body = TestClient(ui_feedback_main.app).get("/").json()

    assert body["version"] == INSTALLED


@pytest.mark.unit
def test_package_carries_no_second_version_home() -> None:
    """Nothing read ``ui_feedback.__version__``; it was removed, not re-derived."""
    assert not hasattr(ui_feedback, "__version__")


#: Any ordinary failure of the metadata read, not only the missing package.
METADATA_FAILURES: list[Callable[[str], Exception]] = [
    lambda name: importlib.metadata.PackageNotFoundError(name),
    lambda name: PermissionError(errno.EACCES, "Permission denied", f"/{name}.dist-info"),
    lambda name: MessageError(f"malformed METADATA for {name}"),
]


@pytest.fixture(
    params=METADATA_FAILURES, ids=["PackageNotFoundError", "PermissionError", "MessageError"]
)
def metadata_unavailable(request: pytest.FixtureRequest) -> Iterator[None]:
    make_failure: Callable[[str], Exception] = request.param

    def unreadable(name: str) -> str:
        if name == version_module.PACKAGE_NAME:
            raise make_failure(name)
        return _REAL_VERSION(name)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(version_module, "version", unreadable)
        yield
    importlib.reload(ui_feedback_main)


@pytest.mark.unit
def test_unreadable_metadata_reports_unknown_not_a_plausible_release(
    metadata_unavailable: None,
) -> None:
    assert version_module.service_version() is None
    reloaded = importlib.reload(ui_feedback_main)

    assert reloaded.app.version == version_module.UNKNOWN_VERSION
    assert TestClient(reloaded.app).get("/").json()["version"] == version_module.UNKNOWN_VERSION
