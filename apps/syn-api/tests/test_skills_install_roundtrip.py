# See ADR-066: this test drives the two application seams that must agree on
# skill identity - registration (POST /skills/registrations) and run-time
# resolution (SkillResolutionService). It asserts identity agreement at the
# service level; the full path through a stored template and a live workspace
# is covered by the end-to-end validation runbook.
"""Install-to-run round trip for declared skills (issue #772).

WHY this test exists: registration and resolution key on the same triple
``(source_url, version, skill_name)`` but compute it in different places -
the CLI preflight at install time, and ``SkillResolutionService`` from the
stored template at run time. Nothing else in the suite asserts those two
agree, and if they disagree the failure appears only at execution, as
``SkillNotRegistered``, after the user has committed to a run.

It also pins the content-addressed identity decision for bundled skills: the
version segment carries the tree hash, so editing a bundled skill yields a
different identity rather than silently resolving to the previously stored
tree (``RegisterSkillHandler`` returns an existing aggregate before hashing).
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import TYPE_CHECKING

os.environ.setdefault("APP_ENVIRONMENT", "test")

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest

from syn_api._wiring import reset_skill_singletons
from syn_api.routes.skills import register_skill_endpoint
from syn_api.types import RegisterSkillRequest, SkillFilePayload

_SOURCE_URL = "https://github.com/example/fixture-plugin"
_SKILL_NAME = "repo-conventions"


def _skill_md(body: str) -> bytes:
    return (
        f"---\nname: {_SKILL_NAME}\ndescription: Use when the task touches this repo.\n---\n\n"
        f"{body}\n"
    ).encode()


def _tree_hash(files: list[tuple[str, bytes]]) -> str:
    """Mirror RegisterSkillHandler._compute_tree_sha over (rel_path, content)."""
    hasher = hashlib.sha256()
    for rel_path, content in sorted(files, key=lambda pair: pair[0]):
        hasher.update(rel_path.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(content)
        hasher.update(b"\x00")
    return hasher.hexdigest()


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


async def _register_bundled(body: str) -> tuple[str, str]:
    """Register a bundled skill under its tree hash; return (version, sha)."""
    files = [("SKILL.md", _skill_md(body))]
    version = f"sha256-{_tree_hash(files)}"
    response = await register_skill_endpoint(
        RegisterSkillRequest(
            source_url=_SOURCE_URL,
            version=version,
            skill_name=_SKILL_NAME,
            files=[
                SkillFilePayload(
                    rel_path=rel_path,
                    content_base64=base64.b64encode(content).decode("ascii"),
                )
                for rel_path, content in files
            ],
        )
    )
    return version, response.resolved_sha


def test_tree_hash_matches_the_cli_implementation() -> None:
    """The CLI pins bundled skills by hashing the tree; both sides must agree.

    The CLI computes this in ``hashSkillTree`` (skill-ref.ts) and asserts the
    same constant in ``tests/packages/skill-ref.test.ts``. If the two drift,
    the version a skill registers under stops describing its content: the
    install-time cache check never hits, and run-time resolution looks up an
    identity that was never stored.
    """
    assert (
        _tree_hash([("SKILL.md", b"# hi")])
        == "1bba9894d50ccaf28bd7e2ace4e4103ffc6667734088ffb87796efd74df15b04"
    )


@pytest.mark.asyncio
async def test_a_registered_skill_resolves_for_the_phase_that_declares_it() -> None:
    """The install-time identity is the one run-time resolution looks up.

    This is the end-to-end claim: if it holds, a workflow declaring a skill
    runs without any out-of-band registration step.
    """
    from syn_api._wiring import get_skill_resolution_service
    from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef

    version, _ = await _register_bundled("Prefer small focused modules.")

    # The ref as it appears in the stored template after install rewrites the
    # bundled path into a pinned, content-addressed reference.
    ref = SkillRef(
        skill_name=_SKILL_NAME,
        source_url=_SOURCE_URL,
        version=version,
    )

    service = await get_skill_resolution_service()
    resolved = await service.resolve_for_phase(workflow_skills=[ref], phase_skills=[])

    assert len(resolved) == 1
    assert resolved[0].skill_name == _SKILL_NAME
    assert resolved[0].version == version
    assert resolved[0].tree_storage_prefix


@pytest.mark.asyncio
async def test_editing_a_bundled_skill_changes_its_identity() -> None:
    """Content-addressed version: an edit must not resolve to the old tree.

    RegisterSkillHandler short-circuits on an existing aggregate BEFORE
    hashing the submitted files, so a fixed version literal (e.g. "bundled")
    would silently keep serving the previous content. Putting the tree hash
    in the version is what makes an edit a different registration.
    """
    first_version, first_sha = await _register_bundled("Prefer small focused modules.")
    second_version, second_sha = await _register_bundled("Prefer tiny focused modules.")

    assert first_version != second_version
    assert first_sha != second_sha


@pytest.mark.asyncio
async def test_an_unregistered_skill_fails_resolution_rather_than_running_skill_less() -> None:
    from syn_api._wiring import get_skill_resolution_service
    from syn_domain.contexts.orchestration import SkillNotRegistered
    from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef

    ref = SkillRef(
        skill_name=_SKILL_NAME,
        source_url=_SOURCE_URL,
        version="sha256-0000000000000000000000000000000000000000000000000000000000000000",
    )

    service = await get_skill_resolution_service()
    with pytest.raises(SkillNotRegistered):
        await service.resolve_for_phase(workflow_skills=[ref], phase_skills=[])
