"""A Skill call's name survives the real TimescaleDB round trip whole (#1269).

The unit tests for skill use build `ToolOperation`s by hand, so they never
prove the name reaches SQL and comes back. This drives the production write
path - `ObservabilityCollector.record_tool_started` -> `AgentEventStore`
`record_observation` -> `store_write.insert_one` - into a real TimescaleDB,
reads it back through `SessionToolsProjection` (`session_tools_dispatch`), and
summarises it with the same function the API uses.

The preview is deliberately built so the skill name is NOT inside its first
500 characters: a long ``args`` precedes ``skill``. If the name were ever read
out of the preview again, or cut on write, the full name could not come back.

Uses the shared `test_infrastructure` fixture (ADR-034): test-stack on port
15432, else testcontainers.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Realistic and long: owner/repo/skill@40-char sha, 90+ characters.
_SKILL = (
    "syntropic137/software-leverage-points/principles-and-patterns"
    "@7e48aad9c7186bb03b8b0df899f56b7cd3b2a454"
)


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


@pytest.mark.integration
class TestSkillNameSurvivesTimescaleDB:
    async def test_full_skill_name_round_trips_and_one_call_counts_once(self, event_store):
        from syn_adapters.projections import SessionToolsProjection
        from syn_adapters.projections.session_tools import call_identity
        from syn_api.routes.executions.phase_skill_use import summarize_skill_use
        from syn_api.types import PhaseStartConfig, PinnedSkillInfo
        from syn_domain.contexts.orchestration import SKILL_TOOL_NAME
        from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
            ObservabilityCollector,
        )
        from syn_shared.agents import AgentProvider

        session_id = f"skill-rt-{uuid4()}"
        collector = ObservabilityCollector(
            writer=event_store,
            session_id=session_id,
            execution_id=f"exec-{uuid4()}",
            phase_id="implement",
            workspace_id=None,
            requested_model="opus",
        )
        tool_input = {"args": "x" * 600, "skill": _SKILL}
        preview = json.dumps(tool_input)[:500]
        assert _SKILL not in preview, "precondition: the name must be cut from the preview"

        tool_use_id = f"toolu_{uuid4().hex}"
        await collector.record_tool_started(
            tool_name=SKILL_TOOL_NAME,
            tool_use_id=tool_use_id,
            input_preview=preview,
            skill_name=_SKILL,
        )
        await collector.record_tool_completed(
            tool_name=SKILL_TOOL_NAME,
            tool_use_id=tool_use_id,
            success=True,
            output_preview="loaded",
        )

        ops = await SessionToolsProjection(pool=event_store.pool).get(session_id)

        skill_ops = [op for op in ops if op.tool_name == SKILL_TOOL_NAME]
        assert len(skill_ops) == 2, [op.operation_type for op in ops]
        starts = [op for op in skill_ops if op.skill_name is not None]
        assert len(starts) == 1
        assert starts[0].skill_name == _SKILL
        assert len(starts[0].skill_name) == len(_SKILL)
        assert len({call_identity(op) for op in skill_ops}) == 1

        pinned = PhaseStartConfig(
            provider=AgentProvider.CLAUDE.value,
            skills=[
                PinnedSkillInfo(
                    name=_SKILL,
                    version="7e48aad9c7186bb03b8b0df899f56b7cd3b2a454",
                    resolved_sha="0" * 64,
                    source_url="https://github.com/syntropic137/software-leverage-points",
                )
            ],
        )
        use = summarize_skill_use(pinned, ops)
        assert use.status == "observed"
        assert use.declared == [_SKILL]
        assert [(s.name, s.count) for s in use.invoked] == [(_SKILL, 1)]
