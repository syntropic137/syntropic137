# See ADR-066: route tests drive the new POST /claude-plugins/registrations
# (inline tree upload) followed by POST /claude-plugins/global. No git or
# fetcher is involved -- the test composes the file payload itself.
"""Tests for the ``/claude-plugins`` HTTP routes (issue #726, Phase A redesign).

Exercises the route layer end-to-end against in-memory adapters: storage,
repos, and projections all run in-process. Verifies typed-error mapping,
idempotency, and that workflow installs reject any reference to an
unregistered plugin without leaving partial state behind.
"""

from __future__ import annotations

import base64
import json
import os
from typing import TYPE_CHECKING

# Tests use the in-memory wiring path (InMemoryAdapter guards everywhere).
os.environ.setdefault("APP_ENVIRONMENT", "test")

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from syn_api._wiring import reset_claude_plugin_singletons
from syn_api.routes.claude_plugins import (
    add_global_claude_plugin_endpoint,
    list_claude_plugins_endpoint,
    list_global_claude_plugins_endpoint,
    register_claude_plugin_endpoint,
    remove_global_claude_plugin_endpoint,
    show_claude_plugin_endpoint,
)
from syn_api.routes.workflows.commands import create_workflow_from_yaml_endpoint
from syn_api.types import (
    AddGlobalClaudePluginRequest,
    ClaudePluginFileEntry,
    RegisterClaudePluginRequest,
)


def _b64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _plugin_files(name: str) -> list[ClaudePluginFileEntry]:
    """Build the inline file payload for a minimal plugin."""
    manifest = json.dumps({"name": name, "version": "1.0.0"}).encode("utf-8")
    return [
        ClaudePluginFileEntry(
            rel_path=".claude-plugin/plugin.json",
            content_b64=_b64(manifest),
        ),
    ]


def _manifest(name: str) -> dict[str, object]:
    return {"name": name, "version": "1.0.0"}


async def _register(source_url: str, version: str, name: str) -> None:
    """Convenience: register a plugin via the new endpoint."""
    await register_claude_plugin_endpoint(
        RegisterClaudePluginRequest(
            source_url=source_url,
            version=version,
            name=name,
            manifest=_manifest(name),
            files=_plugin_files(name),
        )
    )


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Reset singletons + projection store between tests for isolation."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage
    from syn_adapters.storage.event_store_client import reset_event_store_client
    from syn_adapters.storage.repositories import reset_repositories

    reset_storage()
    reset_event_store_client()
    reset_repositories()
    reset_projection_manager()
    reset_claude_plugin_singletons()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_event_store_client()
    reset_repositories()
    reset_projection_manager()
    reset_claude_plugin_singletons()


# ---------------------------------------------------------------------------
# Registration route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_registrations_persists_lock_entry() -> None:
    response = await register_claude_plugin_endpoint(
        RegisterClaudePluginRequest(
            source_url="https://github.com/example/alpha",
            version="1.0.0",
            name="alpha",
            manifest=_manifest("alpha"),
            files=_plugin_files("alpha"),
        )
    )
    assert response.name == "alpha"
    assert response.version == "1.0.0"
    assert response.sha256

    # Lock projection now contains the entry.
    listing = await list_claude_plugins_endpoint()
    assert listing.total == 1
    assert listing.plugins[0].name == "alpha"


@pytest.mark.asyncio
async def test_post_registrations_idempotent_on_resubmit() -> None:
    body = RegisterClaudePluginRequest(
        source_url="https://github.com/example/idem",
        version="2.0.0",
        name="idem",
        manifest=_manifest("idem"),
        files=_plugin_files("idem"),
    )
    first = await register_claude_plugin_endpoint(body)
    second = await register_claude_plugin_endpoint(body)
    assert first == second


@pytest.mark.asyncio
async def test_post_registrations_missing_manifest_returns_422() -> None:
    body = RegisterClaudePluginRequest(
        source_url="https://github.com/example/no-manifest",
        version="1.0.0",
        name="no-manifest",
        manifest={},
        files=[
            ClaudePluginFileEntry(rel_path="README.md", content_b64=_b64(b"hello")),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        await register_claude_plugin_endpoint(body)
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error_code"] == "not_a_claude_plugin"


@pytest.mark.asyncio
async def test_post_registrations_bad_base64_returns_400() -> None:
    body = RegisterClaudePluginRequest(
        source_url="https://github.com/example/bad-b64",
        version="1.0.0",
        name="bad-b64",
        manifest=_manifest("bad-b64"),
        files=[
            ClaudePluginFileEntry(
                rel_path=".claude-plugin/plugin.json",
                content_b64="!!!not base64!!!",
            ),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        await register_claude_plugin_endpoint(body)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Global registry routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_global_requires_prior_registration() -> None:
    body = AddGlobalClaudePluginRequest(name="missing", version="1.0.0")
    with pytest.raises(HTTPException) as exc_info:
        await add_global_claude_plugin_endpoint(body)
    assert exc_info.value.status_code == 404
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error_code"] == "claude_plugin_not_registered"


@pytest.mark.asyncio
async def test_post_global_after_register_succeeds() -> None:
    await _register("https://github.com/example/beta", "2.0.0", "beta")

    response = await add_global_claude_plugin_endpoint(
        AddGlobalClaudePluginRequest(name="beta", version="2.0.0")
    )
    assert response.name == "beta"
    assert response.source_url == "https://github.com/example/beta"
    assert response.version == "2.0.0"
    assert response.resolved_sha
    # WHY (#726): the projection sync runs before the response is built so
    # ``added_at`` matches subsequent GET /global responses.
    assert response.added_at is not None


@pytest.mark.asyncio
async def test_remove_global_unknown_returns_404() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await remove_global_claude_plugin_endpoint("does-not-exist")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_global_add_remove_list_cycle() -> None:
    await _register("https://github.com/example/beta", "2.0.0", "beta")
    await add_global_claude_plugin_endpoint(
        AddGlobalClaudePluginRequest(name="beta", version="2.0.0")
    )

    listing = await list_global_claude_plugins_endpoint()
    assert listing.total == 1
    assert listing.plugins[0].name == "beta"

    removed = await remove_global_claude_plugin_endpoint("beta")
    assert removed.status == "removed"

    # WHY (#726): DELETE flushes the projection sync before returning so the
    # subsequent GET reflects the removal immediately.
    listing_after = await list_global_claude_plugins_endpoint()
    assert listing_after.total == 0


# ---------------------------------------------------------------------------
# Lock projection routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lock_list_reflects_registered_plugins() -> None:
    await _register("https://github.com/example/gamma", "3.0.0", "gamma")

    listing = await list_claude_plugins_endpoint()
    assert listing.total == 1
    entry = listing.plugins[0]
    assert entry.name == "gamma"
    assert entry.version == "3.0.0"
    assert entry.tree_storage_prefix


@pytest.mark.asyncio
async def test_show_returns_lock_entry() -> None:
    await _register("https://github.com/example/delta", "4.0.0", "delta")

    entry = await show_claude_plugin_endpoint("delta", "4.0.0")
    assert entry.name == "delta"
    assert entry.version == "4.0.0"


@pytest.mark.asyncio
async def test_show_unknown_returns_404() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await show_claude_plugin_endpoint("ghost", "0.0.0")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# from-yaml integration: unregistered plugin must NOT register the workflow
# ---------------------------------------------------------------------------


def _yaml_request(body: bytes) -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/yaml")]
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {  # type: ignore[arg-type]
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/api/v1/workflows/from-yaml",
            "headers": headers,
            "query_string": b"",
        },
        receive,
    )


_YAML_WITH_BAD_PLUGIN = """
id: bad-plugin-wf
name: Bad Plugin Workflow
type: custom
classification: standard
claude_plugins:
  - example/nonexistent@9.9.9

phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "do nothing"
"""


_YAML_WITH_VALID_PLUGIN = """
id: valid-plugin-wf
name: Valid Plugin Workflow
type: custom
classification: standard
claude_plugins:
  - example/eps@5.0.0

phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "hello"
"""


@pytest.mark.asyncio
async def test_from_yaml_unregistered_plugin_returns_422_and_no_workflow_registered() -> None:
    request = _yaml_request(_YAML_WITH_BAD_PLUGIN.encode("utf-8"))
    with pytest.raises(HTTPException) as exc_info:
        await create_workflow_from_yaml_endpoint(request)
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error_code"] == "claude_plugin_not_registered"

    # The lock projection must remain empty -- no partial state.
    lock_listing = await list_claude_plugins_endpoint()
    assert lock_listing.total == 0


@pytest.mark.asyncio
async def test_from_yaml_with_pre_registered_plugin_succeeds() -> None:
    # Pre-register the plugin via the new endpoint before posting the YAML.
    await _register("https://github.com/example/eps", "5.0.0", "eps")

    request = _yaml_request(_YAML_WITH_VALID_PLUGIN.encode("utf-8"))
    response = await create_workflow_from_yaml_endpoint(request)
    assert response.status == "created"

    lock_listing = await list_claude_plugins_endpoint()
    assert lock_listing.total == 1
    assert lock_listing.plugins[0].name == "eps"
