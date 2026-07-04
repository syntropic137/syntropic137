# See ADR-066: route tests drive POST /skills/registrations (inline tree
# upload). No git or fetcher is involved -- the test composes the file
# payload itself. Mirrors test_claude_plugins_routes.py (issue #726).
"""Tests for the ``/skills`` HTTP routes (issue #772)."""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING

# Tests use the in-memory wiring path (InMemoryAdapter guards everywhere).
os.environ.setdefault("APP_ENVIRONMENT", "test")

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest
from fastapi import HTTPException

from syn_api._wiring import reset_skill_singletons
from syn_api.routes.skills import register_skill_endpoint
from syn_api.types import RegisterSkillRequest, SkillFilePayload


def _b64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _skill_md(name: str = "code-review") -> bytes:
    return (
        f"---\nname: {name}\ndescription: Review diffs for correctness bugs.\n---\n\n"
        "# Skill\n\nInstructions here.\n"
    ).encode()


def _skill_files(name: str = "code-review") -> list[SkillFilePayload]:
    """Build the inline file payload for a minimal, valid skill tree."""
    return [
        SkillFilePayload(rel_path="SKILL.md", content_base64=_b64(_skill_md(name))),
    ]


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
    reset_skill_singletons()
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
    reset_skill_singletons()


# ---------------------------------------------------------------------------
# Registration route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_registrations_persists_lock_entry() -> None:
    response = await register_skill_endpoint(
        RegisterSkillRequest(
            source_url="https://github.com/example/alpha",
            version="1.0.0",
            skill_name="alpha",
            files=_skill_files("alpha"),
        )
    )
    assert response.skill_name == "alpha"
    assert response.version == "1.0.0"
    assert response.resolved_sha
    assert response.tree_storage_prefix


@pytest.mark.asyncio
async def test_post_registrations_idempotent_on_resubmit() -> None:
    body = RegisterSkillRequest(
        source_url="https://github.com/example/idem",
        version="2.0.0",
        skill_name="idem",
        files=_skill_files("idem"),
    )
    first = await register_skill_endpoint(body)
    second = await register_skill_endpoint(body)
    assert first == second


@pytest.mark.asyncio
async def test_post_registrations_missing_manifest_returns_422() -> None:
    body = RegisterSkillRequest(
        source_url="https://github.com/example/no-manifest",
        version="1.0.0",
        skill_name="no-manifest",
        files=[
            SkillFilePayload(rel_path="README.md", content_base64=_b64(b"hello")),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        await register_skill_endpoint(body)
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error_code"] == "not_a_skill"


@pytest.mark.asyncio
async def test_post_registrations_bad_base64_returns_400() -> None:
    body = RegisterSkillRequest(
        source_url="https://github.com/example/bad-b64",
        version="1.0.0",
        skill_name="bad-b64",
        files=[
            SkillFilePayload(rel_path="SKILL.md", content_base64="!!!not base64!!!"),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        await register_skill_endpoint(body)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Hostile tree paths (mirrors issue #726 review): rejected before hashing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_path",
    [
        "../evil",
        "../AGENTS.md",
        "foo/../../CLAUDE.md",
        "/abs/path.md",
        "back\\slash.md",
    ],
)
async def test_post_registrations_rejects_hostile_rel_path(hostile_path: str) -> None:
    body = RegisterSkillRequest(
        source_url="https://github.com/example/hostile",
        version="1.0.0",
        skill_name="hostile",
        files=[
            *_skill_files("hostile"),
            SkillFilePayload(rel_path=hostile_path, content_base64=_b64(b"evil")),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        await register_skill_endpoint(body)
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error_code"] == "skill_invalid_path"


# ---------------------------------------------------------------------------
# Upload limits (mirrors issue #726 review)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_registrations_rejects_oversized_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import syn_api.routes.skills as routes_module

    monkeypatch.setattr(routes_module, "MAX_SKILL_TREE_BYTES", 64)
    body = RegisterSkillRequest(
        source_url="https://github.com/example/too-big",
        version="1.0.0",
        skill_name="too-big",
        files=[
            *_skill_files("too-big"),
            SkillFilePayload(rel_path="big.bin", content_base64=_b64(b"x" * 128)),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        await register_skill_endpoint(body)
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_post_registrations_rejects_too_many_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import syn_api.routes.skills as routes_module

    monkeypatch.setattr(routes_module, "MAX_SKILL_TREE_FILES", 1)
    body = RegisterSkillRequest(
        source_url="https://github.com/example/too-many",
        version="1.0.0",
        skill_name="too-many",
        files=[
            *_skill_files("too-many"),
            SkillFilePayload(rel_path="a.md", content_base64=_b64(b"a")),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        await register_skill_endpoint(body)
    assert exc_info.value.status_code == 413
