"""Tests for POST /workflows/from-yaml.

Two layers of coverage:
- Service-level (``create_workflow_from_yaml``): round-trips YAML through
  the domain command builder into in-memory storage. Verifies ADR-058
  inference, name/id overrides, and field mapping.
- Endpoint-level (``create_workflow_from_yaml_endpoint``): content-type
  negotiation, size caps, UTF-8 handling, and error translation to
  HTTPException.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException
from starlette.requests import Request

if TYPE_CHECKING:
    from starlette.types import Message, Scope

# Ensure in-memory adapters for service-level tests (mirrors test_api_workflows.py).
os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.commands import (
    create_workflow_from_yaml,
    create_workflow_from_yaml_endpoint,
)
from syn_api.types import Ok

# ---------------------------------------------------------------------------
# Shared test-request builder (no TestClient needed — the endpoint reads
# request.body() and .headers, which Starlette happily serves from a Scope).
# ---------------------------------------------------------------------------


def _make_request(*, body: bytes, content_type: str | None = "application/yaml") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if content_type is not None:
        headers.append((b"content-type", content_type.encode("latin-1")))
    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/v1/workflows/from-yaml",
        "headers": headers,
        "query_string": b"",
    }
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.fixture(autouse=True)
def _reset_storage():
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


# ---------------------------------------------------------------------------
# Sample YAML fixtures
# ---------------------------------------------------------------------------


ZERO_REPO_YAML = """
id: heartbeat-wf
name: Heartbeat Workflow
description: A research workflow that needs no repo access
type: research
classification: simple

phases:
  - id: think
    name: Think
    order: 1
    prompt_template: "Do research."
"""


WITH_REPO_YAML = """
id: implementation-wf
name: Implementation Workflow
type: implementation
classification: standard

repository:
  url: https://github.com/acme/widgets
  ref: develop

phases:
  - id: plan
    name: Plan
    order: 1
    prompt_template: "Plan the change."
"""


EXPLICIT_NO_REPOS_YAML = """
id: explicit-no-repos-wf
name: Explicit Requires Repos False
type: custom
classification: standard
requires_repos: false

repository:
  url: https://github.com/acme/widgets
  ref: main

phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "Do work."
"""


PROMPT_FILE_YAML = """
id: prompt-file-wf
name: Uses External Prompt
type: custom
classification: standard

phases:
  - id: p1
    name: Phase
    order: 1
    prompt_file: shared-prompt.md
"""


# Round-trip fixture: covers all three historically-dropped field classes
# in one YAML. Picks non-default values so the test would fail if any
# field silently reverted to the defaults (as the pre-refactor CLI did).
ROUND_TRIP_YAML = """
id: round-trip-wf
name: Round Trip Workflow
type: implementation
classification: complex
requires_repos: false

repository:
  url: https://github.com/acme/widgets
  ref: release

phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "Do work."
"""


# ---------------------------------------------------------------------------
# Service-level (no HTTP layer)
# ---------------------------------------------------------------------------


async def test_service_creates_workflow_with_repo() -> None:
    result = await create_workflow_from_yaml(WITH_REPO_YAML)
    assert isinstance(result, Ok)
    outcome = result.value
    assert outcome.workflow_id == "implementation-wf"
    assert outcome.name == "Implementation Workflow"
    assert outcome.workflow_type == "implementation"


async def test_service_accepts_zero_repo_yaml() -> None:
    # ADR-058 #666: absent requires_repos + no repository must create successfully
    # (would fail if the shared builder forgot to apply the inference).
    result = await create_workflow_from_yaml(ZERO_REPO_YAML)
    assert isinstance(result, Ok)
    assert result.value.workflow_id == "heartbeat-wf"


async def test_service_honors_explicit_requires_repos_false() -> None:
    # ADR-058: explicit `requires_repos: false` wins even with a repo block.
    result = await create_workflow_from_yaml(EXPLICIT_NO_REPOS_YAML)
    assert isinstance(result, Ok)
    assert result.value.workflow_id == "explicit-no-repos-wf"


async def test_service_applies_name_override() -> None:
    result = await create_workflow_from_yaml(ZERO_REPO_YAML, name_override="Renamed On Install")
    assert isinstance(result, Ok)
    assert result.value.name == "Renamed On Install"


async def test_service_applies_id_override() -> None:
    result = await create_workflow_from_yaml(
        ZERO_REPO_YAML, workflow_id_override="custom-install-id"
    )
    assert isinstance(result, Ok)
    assert result.value.workflow_id == "custom-install-id"


async def test_service_rejects_prompt_file_reference() -> None:
    # There's no base_dir for an HTTP upload — `prompt_file:` must fail.
    with pytest.raises(ValueError, match="not resolved"):
        await create_workflow_from_yaml(PROMPT_FILE_YAML)


async def test_service_rejects_malformed_yaml() -> None:
    with pytest.raises(ValueError):
        await create_workflow_from_yaml("this is: not: valid: yaml: [unclosed")


# ---------------------------------------------------------------------------
# Endpoint-level (HTTP wrapper behavior)
# ---------------------------------------------------------------------------


async def test_endpoint_rejects_wrong_content_type() -> None:
    request = _make_request(body=WITH_REPO_YAML.encode(), content_type="application/json")
    with pytest.raises(HTTPException) as exc_info:
        await create_workflow_from_yaml_endpoint(request)
    assert exc_info.value.status_code == 415


async def test_endpoint_rejects_missing_content_type() -> None:
    request = _make_request(body=WITH_REPO_YAML.encode(), content_type=None)
    with pytest.raises(HTTPException) as exc_info:
        await create_workflow_from_yaml_endpoint(request)
    assert exc_info.value.status_code == 415


async def test_endpoint_accepts_all_yaml_content_types() -> None:
    for ct in ("application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"):
        request = _make_request(body=ZERO_REPO_YAML.encode(), content_type=ct)
        # Each iteration uses a fresh aggregate id per YAML — must reset between calls.
        response = await create_workflow_from_yaml_endpoint(
            request,
            workflow_id=f"ct-test-{ct.replace('/', '-')}",
        )
        assert response.status == "created"


async def test_endpoint_accepts_content_type_with_charset_suffix() -> None:
    request = _make_request(
        body=ZERO_REPO_YAML.encode(),
        content_type="application/yaml; charset=utf-8",
    )
    response = await create_workflow_from_yaml_endpoint(request, workflow_id="charset-suffix-test")
    assert response.status == "created"


async def test_endpoint_rejects_oversize_body() -> None:
    huge = b"x" * (1 * 1024 * 1024 + 1)
    request = _make_request(body=huge, content_type="application/yaml")
    with pytest.raises(HTTPException) as exc_info:
        await create_workflow_from_yaml_endpoint(request)
    assert exc_info.value.status_code == 413


async def test_endpoint_rejects_non_utf8_body() -> None:
    request = _make_request(body=b"\xff\xfe not utf-8", content_type="application/yaml")
    with pytest.raises(HTTPException) as exc_info:
        await create_workflow_from_yaml_endpoint(request)
    assert exc_info.value.status_code == 400
    assert "UTF-8" in exc_info.value.detail


async def test_endpoint_rejects_malformed_yaml_with_400() -> None:
    request = _make_request(
        body=b"this is: not: valid: yaml: [unclosed", content_type="application/yaml"
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_workflow_from_yaml_endpoint(request)
    assert exc_info.value.status_code == 400
    assert "Invalid workflow YAML" in exc_info.value.detail


async def test_endpoint_rejects_prompt_file_reference_with_400() -> None:
    request = _make_request(body=PROMPT_FILE_YAML.encode(), content_type="application/yaml")
    with pytest.raises(HTTPException) as exc_info:
        await create_workflow_from_yaml_endpoint(request)
    assert exc_info.value.status_code == 400
    # The underlying error message mentions that prompt_file was "not resolved".
    assert "not resolved" in exc_info.value.detail or "prompt_file" in exc_info.value.detail


async def test_endpoint_happy_path_returns_201_fields() -> None:
    request = _make_request(body=WITH_REPO_YAML.encode(), content_type="application/yaml")
    response = await create_workflow_from_yaml_endpoint(request)
    assert response.id == "implementation-wf"
    assert response.name == "Implementation Workflow"
    assert response.workflow_type == "implementation"
    assert response.status == "created"


async def test_endpoint_name_query_param_overrides_yaml_name() -> None:
    request = _make_request(body=ZERO_REPO_YAML.encode(), content_type="application/yaml")
    response = await create_workflow_from_yaml_endpoint(request, name="Renamed")
    assert response.name == "Renamed"


async def test_endpoint_workflow_id_query_param_overrides_yaml_id() -> None:
    request = _make_request(body=ZERO_REPO_YAML.encode(), content_type="application/yaml")
    response = await create_workflow_from_yaml_endpoint(request, workflow_id="custom-id")
    assert response.id == "custom-id"


async def test_endpoint_surfaces_handler_error_as_400() -> None:
    # Creating the same workflow twice must fail with Err → 400.
    request_a = _make_request(body=WITH_REPO_YAML.encode(), content_type="application/yaml")
    first = await create_workflow_from_yaml_endpoint(request_a)
    assert first.status == "created"

    request_b = _make_request(body=WITH_REPO_YAML.encode(), content_type="application/yaml")
    with pytest.raises(HTTPException) as exc_info:
        await create_workflow_from_yaml_endpoint(request_b)
    assert exc_info.value.status_code == 400


async def test_endpoint_round_trip_preserves_classification_repo_and_requires_repos() -> None:
    """Regression: under the pre-refactor CLI path, classification,
    repository.url, and requires_repos from the YAML were all silently
    dropped in favour of defaults/placeholders. This locks in that each
    round-trips through the endpoint's response."""
    request = _make_request(body=ROUND_TRIP_YAML.encode(), content_type="application/yaml")
    created = await create_workflow_from_yaml_endpoint(request)
    assert created.id == "round-trip-wf"
    assert created.classification == "complex"
    assert created.repository_url == "https://github.com/acme/widgets"
    assert created.requires_repos is False
