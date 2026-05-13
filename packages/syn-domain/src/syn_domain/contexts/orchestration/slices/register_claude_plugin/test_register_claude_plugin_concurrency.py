# See ADR-066: concurrency tests use the in-memory storage and registration
# repository directly; no fetcher exists in this layer after the #726 Phase A
# redesign.
"""Concurrency safety for RegisterClaudePluginHandler (issue #726).

Two parallel ``handle()`` calls for the same ``(source_url, version)`` must
collapse into exactly one registration. The handler relies on
``ExpectedVersion.NoStream`` semantics (``save_new`` raises
``StreamAlreadyExistsError`` on collision) to enforce first-writer-wins;
this test exercises that path explicitly.
"""

from __future__ import annotations

import asyncio
import json
import os

# WHY: the in-memory adapters this test wires up assert non-production env.
os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from event_sourcing import StreamAlreadyExistsError

from syn_adapters.storage.claude_plugin_storage.memory import InMemoryClaudePluginStorage
from syn_adapters.storage.in_memory_claude_plugin_repositories import (
    InMemoryClaudePluginRegistrationRepository,
)
from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
    ClaudePluginFile,
)
from syn_domain.contexts.orchestration.slices.register_claude_plugin import (
    RegisterClaudePluginHandler,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
        ClaudePluginRegistrationAggregate,
    )


class _BarrierRepository(InMemoryClaudePluginRegistrationRepository):
    """Repository that pauses inside ``save_new`` until released.

    WHY: a real concurrent collision in an asyncio test needs both tasks to
    reach the dict-presence check before either commits. We open the gate by
    awaiting a ``release`` event mid-call, so two ``save_new`` tasks both see
    the empty store, then race to the dict write.
    """

    def __init__(self) -> None:
        super().__init__()
        self.save_new_calls: int = 0
        self.successful_save_news: int = 0
        self.release = asyncio.Event()

    async def save_new(self, aggregate: ClaudePluginRegistrationAggregate) -> None:
        self.save_new_calls += 1
        await self.release.wait()
        try:
            await super().save_new(aggregate)
        except StreamAlreadyExistsError:
            raise
        else:
            self.successful_save_news += 1


def _files() -> list[ClaudePluginFile]:
    return [
        ClaudePluginFile(
            rel_path=".claude-plugin/plugin.json",
            content=json.dumps({"name": "raceme", "version": "1.0.0"}).encode("utf-8"),
        ),
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_register_collapses_to_one_registration() -> None:
    """Two concurrent ``handle()`` calls collide; one wins, one re-uses it."""
    storage = InMemoryClaudePluginStorage()
    repo = _BarrierRepository()
    handler = RegisterClaudePluginHandler(storage=storage, repo=repo)

    async def _race() -> object:
        return await handler.handle(
            source_url="https://github.com/example/raceme",
            version="1.0.0",
            name="raceme",
            manifest={"name": "raceme", "version": "1.0.0"},
            files=_files(),
        )

    task_a = asyncio.create_task(_race())
    task_b = asyncio.create_task(_race())

    # Park both tasks at the barrier inside save_new.
    while repo.save_new_calls < 2:
        await asyncio.sleep(0.005)

    # Open the gate. Exactly one save_new will commit; the other sees
    # StreamAlreadyExistsError and falls back to ``get_by_id``.
    repo.release.set()

    result_a = await task_a
    result_b = await task_b

    assert repo.successful_save_news == 1, "exactly one writer must commit the aggregate"
    # Both callers receive the same lock entry data (winner's record).
    assert result_a == result_b
    # The store holds exactly one entry for this stream id.
    assert len(repo._store) == 1
