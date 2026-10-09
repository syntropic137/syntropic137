"""A phase's skill USE reaches the execution detail response (#1269).

Declaring a skill installs it; only an invocation shows the agent used it. The
fact is put in where the system records it - a claude stream-json line,
through the real `EventStreamProcessor` and the real timeline converter - and
read out of the model an API client receives, because every hop in between
re-lists its fields by hand and has dropped one before (#891, #1176, #1300).

WHERE THE STREAM LINE COMES FROM. No recorded stream with a `Skill` call exists
in this repo or in agentic-workspace, and the CLI in the workspace that wrote
this could not record one (not logged in). So the line is the REAL recorded
`Read` tool_use from agentic-workspace's
`claude-cli/fixtures/recordings/v2.0.74_claude-sonnet-4-5_file-read.jsonl`,
verbatim except for `name` and `input`, which are swapped to the shape #1269's
2026-09-16 comment observed from a live claude run:
`tool_use: Skill {'skill': 'architecture'}`. Envelope, ids and nesting are the
recording's own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projections.session_tools import GIT_EVENT_TYPES, SUBAGENT_TOOL_NAMES
from syn_adapters.projections.session_tools_dispatch import to_operation
from syn_api.routes.executions.models import ExecutionDetailResponse
from syn_api.routes.executions.phase_mapping import _map_phase_detail, _map_phase_to_response
from syn_api.types import ExecutionSkillUseSummary, PhaseStartConfig, PinnedSkillInfo
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from syn_adapters.projections.session_tools import ToolOperation
    from syn_api.routes.executions.models import PhaseExecutionInfo
    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )

pytestmark = pytest.mark.unit

SESSION_ID = "sess-1269"
PHASE_ID = "implement"

#: Declared on the phase. Two, so "declared, not invoked" has something to name.
DECLARED = ("architecture", "principles-and-patterns")


def _recorded_tool_use(tool_use_id: str, name: str, tool_input: Mapping[str, str]) -> str:
    """The recording's `Read` line with only `name` and `input` swapped (see module doc)."""
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-5-20250929",
                "id": f"msg_{tool_use_id}",
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}
                ],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 333,
                    "cache_read_input_tokens": 17713,
                    "output_tokens": 79,
                    "service_tier": "standard",
                },
                "context_management": None,
            },
            "parent_tool_use_id": None,
            "session_id": "221751c1-866a-467d-8adb-c2616eee0748",
            "uuid": f"uuid-{tool_use_id}",
        }
    )


@dataclass
class _Recorder:
    """The observability port, keeping each observation as the store would."""

    rows: list[tuple[str, str]] = field(default_factory=list)
    """(event type, payload as JSON) - JSON, because that is what is stored."""

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: object,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        kind = observation_type.value if hasattr(observation_type, "value") else observation_type
        self.rows.append((str(kind), json.dumps(data, default=str)))


class _Workspace:
    async def interrupt(self) -> bool:
        return True


async def _stream(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


async def _timeline(*lines: str) -> list[ToolOperation]:
    """Drive the lines through the processor, then convert as the reader does."""
    recorder = _Recorder()
    proc = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=recorder,
        controller=None,
        execution_id="exec-1269",
        phase_id=PHASE_ID,
        session_id=SESSION_ID,
        workspace_id="ws-1269",
        agent_model="claude-sonnet",
    )
    await proc.process_stream(_stream(*lines), _Workspace())
    when = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    ops = [
        to_operation(when, json.loads(payload), kind, SUBAGENT_TOOL_NAMES, GIT_EVENT_TYPES)
        for kind, payload in recorder.rows
    ]
    return [op for op in ops if op is not None]


class _Manager:
    def __init__(self, ops: list[ToolOperation]) -> None:
        self.session_tools = self
        self._ops = ops

    async def get(self, session_id: str) -> list[ToolOperation] | None:
        return self._ops if session_id == SESSION_ID else None


def _pins(provider: str) -> PhaseStartConfig:
    return PhaseStartConfig(
        provider=provider,
        allowed_tools=["Read", "Bash", "Skill"],
        skills=[
            PinnedSkillInfo(
                name=name,
                version="7e48aad",
                resolved_sha=f"sha-{name}",
                source_url="syntropic137/software-leverage-points",
            )
            for name in DECLARED
        ],
    )


async def _as_client_sees_it(ops: list[ToolOperation], provider: str) -> PhaseExecutionInfo:
    phase = PhaseExecutionDetail(
        workflow_phase_id=PHASE_ID, name="Implement", status="completed", session_id=SESSION_ID
    )
    mapped = await _map_phase_detail(
        phase,
        _Manager(ops),  # pyright: ignore[reportArgumentType]
        None,
        start_configs={PHASE_ID: _pins(provider)},
    )
    # Through JSON, as a client receives it, so the computed field is included.
    return type(_map_phase_to_response(mapped)).model_validate_json(
        _map_phase_to_response(mapped).model_dump_json()
    )


@pytest.mark.asyncio
async def test_an_invoked_skill_appears_on_its_phase() -> None:
    ops = await _timeline(
        _recorded_tool_use("toolu_a", "Read", {"file_path": "/workspace/pyproject.toml"}),
        _recorded_tool_use("toolu_b", "Skill", {"skill": "architecture"}),
        _recorded_tool_use("toolu_c", "Skill", {"skill": "architecture"}),
    )

    use = (await _as_client_sees_it(ops, "claude")).skill_use

    assert use.status == "observed"
    assert use.declared == list(DECLARED)
    assert [(s.name, s.count) for s in use.invoked] == [("architecture", 2)]
    assert use.declared_not_invoked == ["principles-and-patterns"]


@pytest.mark.asyncio
async def test_a_skill_named_after_a_long_argument_is_still_identified() -> None:
    # The input preview is cut at 500 characters. With `args` first, the cut
    # falls before `skill`, so a name read back from the preview is lost; the
    # skill has to be recorded whole, as its own field.
    long_args = {"args": "x" * 520, "skill": "architecture"}
    ops = await _timeline(_recorded_tool_use("toolu_long", "Skill", long_args))
    assert '"skill"' not in (ops[0].input_preview or "")  # the shape this guards

    use = (await _as_client_sees_it(ops, "claude")).skill_use

    assert [(s.name, s.count) for s in use.invoked] == [("architecture", 1)]
    assert use.declared_not_invoked == ["principles-and-patterns"]


@pytest.mark.asyncio
async def test_no_skill_call_reads_declared_not_invoked_rather_than_missing() -> None:
    ops = await _timeline(
        _recorded_tool_use("toolu_a", "Read", {"file_path": "/workspace/pyproject.toml"}),
    )

    use = (await _as_client_sees_it(ops, "claude")).skill_use

    assert use.status == "observed"
    assert use.declared == list(DECLARED)
    assert use.invoked == []
    assert use.declared_not_invoked == list(DECLARED)


@pytest.mark.asyncio
async def test_codex_reports_not_observable_never_zero() -> None:
    use = (await _as_client_sees_it([], "codex")).skill_use

    assert use.status == "not_observable"
    assert use.declared == list(DECLARED)
    assert use.declared_not_invoked == []


@pytest.mark.asyncio
async def test_unreadable_timeline_is_unavailable_not_unused() -> None:
    phase = PhaseExecutionDetail(
        workflow_phase_id=PHASE_ID, name="Implement", status="completed", session_id="elsewhere"
    )
    mapped = await _map_phase_detail(
        phase,
        _Manager([]),  # pyright: ignore[reportArgumentType]
        None,
        start_configs={PHASE_ID: _pins("claude")},
    )

    assert mapped.skill_use.status == "unavailable"
    assert _map_phase_to_response(mapped).skill_use.declared_not_invoked == []


# --- What a client RENDERS (feedback 01308bcf) ---------------------------------
# The dashboard prints these strings verbatim, so they are asserted on the
# response a client receives, after the real phase mapping and through JSON.


@pytest.mark.asyncio
async def test_codex_status_is_explained_and_never_reads_as_zero() -> None:
    use = (await _as_client_sees_it([], "codex")).skill_use

    assert use.status_display == "not observable: codex has no Skill tool"
    assert use.summary_display == ("2 skills declared; use not observable: codex has no Skill tool")
    assert "0" not in use.summary_display


@pytest.mark.asyncio
async def test_observed_summary_counts_declared_skills_invoked() -> None:
    ops = await _timeline(_recorded_tool_use("toolu_b", "Skill", {"skill": "architecture"}))

    use = (await _as_client_sees_it(ops, "claude")).skill_use

    assert use.summary_display == "1 of 2 declared skills invoked"


@pytest.mark.asyncio
async def test_unreadable_pins_explain_unavailable() -> None:
    phase = PhaseExecutionDetail(
        workflow_phase_id=PHASE_ID, name="Implement", status="completed", session_id=SESSION_ID
    )
    mapped = await _map_phase_detail(
        phase,
        _Manager([]),  # pyright: ignore[reportArgumentType]
        None,
        start_configs={},
    )
    use = _map_phase_to_response(mapped).skill_use

    assert use.status_display == "unavailable: no record for this run"
    assert use.summary_display == "skill use unavailable: no record for this run"


async def _execution_sees(*phases: PhaseExecutionInfo) -> ExecutionSkillUseSummary:
    response = ExecutionDetailResponse.model_construct(phases=list(phases))
    return ExecutionSkillUseSummary.model_validate(
        json.loads(response.model_dump_json(include={"phases", "skill_use"}))["skill_use"]
    )


@pytest.mark.asyncio
async def test_execution_summary_never_calls_a_codex_declared_skill_unused() -> None:
    # architecture: invoked on claude. principles-and-patterns: declared on
    # both, not invoked on claude, but the codex phase may have used it.
    ops = await _timeline(_recorded_tool_use("toolu_b", "Skill", {"skill": "architecture"}))
    claude = await _as_client_sees_it(ops, "claude")
    codex = await _as_client_sees_it([], "codex")

    summary = await _execution_sees(claude, codex)

    assert summary.declared == list(DECLARED)
    assert [(s.name, s.count) for s in summary.invoked] == [("architecture", 1)]
    assert summary.never_invoked == []
    assert summary.not_known == ["principles-and-patterns"]
    assert summary.summary_display == (
        "2 skills declared · 1 invoked · 1 use unknown"
    )


async def _blind_review(start_configs: dict[str, PhaseStartConfig]) -> PhaseExecutionInfo:
    phase = PhaseExecutionDetail(
        workflow_phase_id="review", name="Review", status="completed", session_id=SESSION_ID
    )
    mapped = await _map_phase_detail(
        phase,
        _Manager([]),  # pyright: ignore[reportArgumentType]
        None,
        start_configs=start_configs,
    )
    return _map_phase_to_response(mapped)


@pytest.mark.asyncio
async def test_a_blind_phase_declaring_other_skills_still_hides_use_of_these() -> None:
    # The codex phase declares only `types`, but an agent can invoke a skill
    # its phase never declared, so it may have used either of claude's.
    claude = await _as_client_sees_it([], "claude")
    codex_pins = _pins("codex").model_copy(
        update={
            "skills": [
                PinnedSkillInfo(
                    name="types", version="v1", resolved_sha="sha-types", source_url="x/y"
                )
            ]
        }
    )
    codex = await _blind_review({"review": codex_pins})

    summary = await _execution_sees(claude, codex)

    assert summary.never_invoked == []
    assert summary.not_known == [*DECLARED, "types"]
    assert "never invoked" not in summary.summary_display


@pytest.mark.asyncio
async def test_a_phase_with_no_pins_still_hides_use_of_every_skill() -> None:
    claude = await _as_client_sees_it([], "claude")
    unread = await _blind_review({})

    summary = await _execution_sees(claude, unread)

    assert unread.skill_use.status == "unavailable"
    assert summary.never_invoked == []
    assert summary.not_known == list(DECLARED)


@pytest.mark.asyncio
async def test_execution_summary_names_a_skill_no_observed_phase_invoked() -> None:
    claude = await _as_client_sees_it([], "claude")

    summary = await _execution_sees(claude)

    assert summary.never_invoked == list(DECLARED)
    assert summary.summary_display == "2 skills declared · 0 invoked · 2 never invoked"


@pytest.mark.asyncio
async def test_execution_summary_of_codex_only_run_counts_nothing() -> None:
    summary = await _execution_sees(await _as_client_sees_it([], "codex"))

    assert summary.summary_display == "2 skills declared; use not observable on any phase"
