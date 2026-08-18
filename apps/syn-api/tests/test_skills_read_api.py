# See ADR-066: these routes read the existing skill_lock projection and do no
# I/O beyond it. No second read path is introduced (issue #826).
"""Tests for the skills read API: list and detail (issue #826).

WHY these endpoints exist: registrations accumulate automatically on every
``syn workflow install``, and until now nothing could answer "what is
registered?". The only lookup required knowing the full
``(source_url, version, skill_name)`` triple, which is precisely what someone
debugging a ``SkillNotRegistered`` failure does not have.
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING

os.environ.setdefault("APP_ENVIRONMENT", "test")

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest
from fastapi import HTTPException

from syn_api._wiring import reset_skill_singletons
from syn_api.routes.skills import (
    get_skill_detail,
    get_skill_storage_stats,
    list_skills,
    register_skill_endpoint,
)
from syn_api.types import RegisterSkillRequest, SkillFilePayload

# CI runs only `pytest -m unit` and `pytest -m integration`; an unmarked test is
# collected locally and never runs in CI. These use in-memory adapters only.
pytestmark = pytest.mark.unit


def _skill_files(name: str, body: str = "Instructions.") -> list[SkillFilePayload]:
    content = (
        f"---\nname: {name}\ndescription: Use when {name} is relevant.\n---\n\n{body}\n"
    ).encode()
    return [
        SkillFilePayload(
            rel_path="SKILL.md",
            content_base64=base64.b64encode(content).decode("ascii"),
        )
    ]


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
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


async def _register(name: str, version: str = "v1.0.0", body: str = "Instructions.") -> None:
    await register_skill_endpoint(
        RegisterSkillRequest(
            source_url=f"https://github.com/example/{name}",
            version=version,
            skill_name=name,
            files=_skill_files(name, body),
        )
    )


@pytest.mark.asyncio
async def test_list_is_empty_before_anything_is_registered() -> None:
    response = await list_skills()

    assert response.skills == []
    assert response.total == 0


@pytest.mark.asyncio
async def test_list_returns_what_was_registered() -> None:
    await _register("alpha")
    await _register("beta")

    response = await list_skills()

    assert response.total == 2
    assert sorted(s.skill_name for s in response.skills) == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_list_carries_the_fields_needed_to_debug_a_missing_skill() -> None:
    """The triple plus the sha is what makes a SkillNotRegistered actionable."""
    await _register("alpha")

    entry = (await list_skills()).skills[0]

    assert entry.skill_name == "alpha"
    assert entry.source_url == "https://github.com/example/alpha"
    assert entry.version == "v1.0.0"
    assert entry.resolved_sha
    assert entry.resolved_sha_display == entry.resolved_sha[:12]
    assert entry.registered_at is not None


@pytest.mark.asyncio
async def test_detail_returns_every_registration_of_that_name() -> None:
    """A name is not unique: the same skill can be pinned at several versions."""
    await _register("alpha", version="v1.0.0", body="First.")
    await _register("alpha", version="v2.0.0", body="Second.")

    detail = await get_skill_detail("alpha")

    assert detail.skill_name == "alpha"
    assert sorted(r.version for r in detail.registrations) == ["v1.0.0", "v2.0.0"]


@pytest.mark.asyncio
async def test_detail_for_an_unknown_name_is_404_not_an_empty_success() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_skill_detail("never-registered")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_storage_route_is_not_shadowed_by_the_detail_route() -> None:
    """`/skills/storage` must not be captured by `/skills/{skill_name}`.

    FastAPI matches routes in declaration order, so a `{skill_name}` route
    declared before the literal ones would swallow them and return a 404 for a
    skill named "storage" instead of the stats.
    """
    stats = await get_skill_storage_stats()

    assert stats.object_count == 0
