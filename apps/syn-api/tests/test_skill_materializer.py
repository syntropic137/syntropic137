"""Tests for SkillMaterializer (issue #772)."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest

from syn_adapters.storage.skill_storage.memory import InMemorySkillStorage
from syn_api.services.skill_materializer import (
    WORKSPACE_SKILL_ROOT,
    SkillMaterializer,
)
from syn_domain.contexts.orchestration._shared.resolved_skill import (
    ResolvedSkill,
)
from syn_domain.contexts.orchestration._shared.skill_errors import (
    SkillInvalidName,
)
from syn_domain.contexts.orchestration.ports.SkillStoragePort import (
    SkillFile,
)


def _resolved(name: str, sha: str) -> ResolvedSkill:
    return ResolvedSkill(
        skill_name=name,
        source_url=f"https://github.com/example/{name}",
        version="1.0.0",
        resolved_sha=sha,
        tree_storage_prefix=f"memory://skills/sha256-{sha}",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_for_workspace_returns_empty_when_no_skills() -> None:
    storage = InMemorySkillStorage()
    mat = SkillMaterializer(storage=storage)
    out = await mat.fetch_for_workspace(())
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_for_workspace_prefixes_paths_with_skill_root() -> None:
    storage = InMemorySkillStorage()
    files = [
        SkillFile(rel_path="SKILL.md", content=b"---\nname: hello\n---\nhi"),
        SkillFile(rel_path="scripts/greet.py", content=b"print('hi')"),
    ]
    await storage.upload_tree("sha-hello", files)

    mat = SkillMaterializer(storage=storage)
    out = await mat.fetch_for_workspace((_resolved("hello", "sha-hello"),))
    paths = sorted(p for p, _ in out)
    assert paths == [
        f"{WORKSPACE_SKILL_ROOT}/hello/SKILL.md",
        f"{WORKSPACE_SKILL_ROOT}/hello/scripts/greet.py",
    ]
    by_path = dict(out)
    assert by_path[f"{WORKSPACE_SKILL_ROOT}/hello/SKILL.md"] == b"---\nname: hello\n---\nhi"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_for_workspace_handles_multiple_skills_independently() -> None:
    storage = InMemorySkillStorage()
    await storage.upload_tree("sha-a", [SkillFile(rel_path="SKILL.md", content=b"a")])
    await storage.upload_tree("sha-b", [SkillFile(rel_path="SKILL.md", content=b"b")])

    mat = SkillMaterializer(storage=storage)
    out = await mat.fetch_for_workspace(
        (_resolved("alpha", "sha-a"), _resolved("beta", "sha-b")),
    )
    paths = sorted(p for p, _ in out)
    assert paths == [
        f"{WORKSPACE_SKILL_ROOT}/alpha/SKILL.md",
        f"{WORKSPACE_SKILL_ROOT}/beta/SKILL.md",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lru_cache_avoids_refetch_on_repeat_call() -> None:
    storage = InMemorySkillStorage()
    await storage.upload_tree("sha-cached", [SkillFile(rel_path="SKILL.md", content=b"x")])

    fetch_count = {"n": 0}
    real_fetch = storage.fetch_tree

    async def counting_fetch(sha256: str):
        fetch_count["n"] += 1
        return await real_fetch(sha256)

    storage.fetch_tree = counting_fetch  # type: ignore[method-assign]

    mat = SkillMaterializer(storage=storage)
    skill = _resolved("cached", "sha-cached")
    await mat.fetch_for_workspace((skill,))
    await mat.fetch_for_workspace((skill,))

    assert fetch_count["n"] == 1
    assert mat.cache_size() == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lru_cache_evicts_when_full() -> None:
    storage = InMemorySkillStorage()
    for i in range(3):
        await storage.upload_tree(
            f"sha-{i}",
            [SkillFile(rel_path="SKILL.md", content=str(i).encode())],
        )

    mat = SkillMaterializer(storage=storage, cache_size=2)
    await mat.fetch_for_workspace((_resolved("s0", "sha-0"),))
    await mat.fetch_for_workspace((_resolved("s1", "sha-1"),))
    await mat.fetch_for_workspace((_resolved("s2", "sha-2"),))

    # Cache holds only the two most recent entries (sha-1, sha-2).
    assert mat.cache_size() == 2


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_name",
    [
        "../etc/passwd",
        "..",
        "foo/bar",
        "foo\\bar",
        ".hidden",
        "",
        "with\x00null",
        "with\nnewline",
    ],
)
async def test_fetch_for_workspace_rejects_unsafe_skill_names(hostile_name: str) -> None:
    # Security: a skill name with path-traversal, separators, leading dot,
    # control characters, or emptiness must be rejected BEFORE any fetch.
    storage = InMemorySkillStorage()
    await storage.upload_tree("sha-x", [SkillFile(rel_path="SKILL.md", content=b"x")])
    fetch_count = {"n": 0}
    real_fetch = storage.fetch_tree

    async def counting_fetch(sha256: str):
        fetch_count["n"] += 1
        return await real_fetch(sha256)

    storage.fetch_tree = counting_fetch  # type: ignore[method-assign]

    skill = ResolvedSkill(
        skill_name=hostile_name,
        source_url="https://github.com/example/x",
        version="1.0.0",
        resolved_sha="sha-x",
        tree_storage_prefix="memory://skills/sha256-sha-x",
    )
    mat = SkillMaterializer(storage=storage)
    with pytest.raises(SkillInvalidName):
        await mat.fetch_for_workspace((skill,))
    # No fetch happened, so nothing was materialized.
    assert fetch_count["n"] == 0
