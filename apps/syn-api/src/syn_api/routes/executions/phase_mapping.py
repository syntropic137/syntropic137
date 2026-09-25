"""Turning a stored phase record into the two phase models the API serves.

Split out of ``queries.py`` (#1262), which had grown past the 750-line fitness
threshold. The seam is not arbitrary: everything here answers one question -
given a phase as the projection stored it, what does a caller get told about
it - and nothing here is a route. ``queries.py`` keeps the endpoints, the
list/summary path and the cost enrichment, and calls into this.

The three Lane 2 lookups (tool operations, session cost, capture rows) all
fail soft, because none of them is domain truth: a phase whose telemetry is
unreachable is still reported, with the enrichment absent rather than the
read failed.

Absent has to LOOK absent, though, and that is the harder half. Two of the
three say so in their return type - ``None`` for "nobody could tell us", ``[]``
for "we looked and there was nothing" - because the values they carry have real
meanings at zero and at empty, so a soft failure answering zero is read as a
measurement. Tool operations were the one that did not, and a phase whose
timeline could not be read was served as a phase that did nothing: the stall
verdict, invented out of an outage (#1332).
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple

from syn_adapters.workspace_backends.agentic.capture_observation import (
    SESSION_CAPTURE_OBSERVATION,
    read_agent_session_ids,
)
from syn_api.model_identity import cost_by_observed_model, observed_model_of
from syn_api.types import (
    BranchObservationInfo,
    PhaseExecution,
    ToolOperation,
)
from syn_shared.display import resolve_duration_seconds

from .models import (
    PhaseExecutionInfo,
    PhaseOperationInfo,
)
from .phase_activity import summarize_phase_activity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_adapters.projections.manager import ProjectionManager
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        PhaseExecutionDetail,
    )

logger = logging.getLogger(__name__)


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO datetime string, handling trailing 'Z' safely."""
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Failed to parse datetime from value %r", value)
        return None


def _parse_dt(value: datetime | str | None) -> datetime | None:
    """Normalise a datetime-or-string field to datetime."""
    if value is None:
        return None
    return _parse_iso(value) if isinstance(value, str) else value


async def _load_phase_operations(
    manager: ProjectionManager,
    session_id: str,
) -> list[ToolOperation] | None:
    """This session's timeline rows, or ``None`` if Lane 2 could not be read.

    THREE-VALUED, for the same reason ``_load_agent_session_ids`` below is:
    ``[]`` is a timeline that was read and held nothing, ``None`` is a
    timeline nobody could read. Returning ``[]`` for both was #1332's defect -
    a phase whose telemetry was unreachable reported no operations and no
    push, which is exactly what a stalled phase reports, so the feature built
    to tell a timeout from a stall manufactured the stall verdict out of its
    own outage. Wrong in the expensive direction: "stalled" is the reading
    that says do not pay for this run again.

    Failing soft is still right - a phase whose telemetry is unreachable is
    reported, not failed - but soft is not the same as silent.
    """
    try:
        tool_data = await manager.session_tools.get(session_id)
    except Exception:
        logger.exception("Failed to load tool ops for session %s", session_id)
        return None
    # `None` from the projection is its own "could not read", not an empty
    # timeline, and collapsing it here would undo the distinction one hop
    # after it was made.
    if tool_data is None:
        return None
    return [ToolOperation.model_validate(op, from_attributes=True) for op in tool_data]


class _SessionCostData(NamedTuple):
    cache_creation: int
    cache_read: int
    agent_model: str | None
    """What the harness REPORTED, or None. Never an alias (ADR-067 D9)."""
    requested_model: str | None
    """What the session asked for, as its usage rows recorded it."""
    cost_by_model: dict[str, Decimal]


async def _load_session_cost(
    manager: ProjectionManager, session_id: str, phase: PhaseExecutionDetail
) -> _SessionCostData:
    """Load session cost enrichment data (cache tokens, model info)."""
    cache_creation = phase.cache_creation_tokens
    cache_read = phase.cache_read_tokens
    agent_model: str | None = None
    requested_model: str | None = None
    cost_by_model: dict[str, Decimal] = {}
    try:
        sc = await manager.session_cost.get_session_cost(session_id)
        if sc is not None:
            if cache_creation == 0 and cache_read == 0:
                cache_creation = sc.cache_creation_tokens
                cache_read = sc.cache_read_tokens
            # A cost record stored before ADR-067 may still name the alias as
            # its model; it is served as the request it was, not as what ran.
            recorded = observed_model_of(sc.agent_model, sc.requested_model)
            agent_model = recorded.observed
            requested_model = recorded.requested
            cost_by_model = cost_by_observed_model(sc.cost_by_model)
    except Exception:
        logger.debug("Failed to load session cost for %s", session_id, exc_info=True)
    return _SessionCostData(cache_creation, cache_read, agent_model, requested_model, cost_by_model)


async def _phase_cost(
    manager: ProjectionManager,
    phase: PhaseExecutionDetail,
    configured_models: Mapping[str, str | None] | None,
) -> _SessionCostData:
    """The phase's Lane 2 cost enrichment, its request filled from the definition.

    The configured model stands in for ``requested_model`` only when no usage
    row recorded one - never for the observed model.
    """
    if phase.session_id:
        sc = await _load_session_cost(manager, phase.session_id, phase)
    else:
        sc = _SessionCostData(phase.cache_creation_tokens, phase.cache_read_tokens, None, None, {})
    if sc.requested_model is None and configured_models:
        sc = sc._replace(requested_model=configured_models.get(phase.workflow_phase_id))
    return sc


async def load_configured_models(
    manager: ProjectionManager, workflow_id: str
) -> dict[str, str | None] | None:
    """Each phase's CONFIGURED model from the workflow definition, by phase id.

    Only a fallback for ``requested_model``, used when a phase has no usage
    row saying what it asked for - a phase still pending, or one that ended
    before its first turn. It is the definition as it stands NOW, which is
    what the run requested unless the workflow was edited since, so it never
    stands in for the observed model. Fails soft: the definition is context,
    not the run's truth. ``None`` means the definition could not be read,
    ``{}`` that there is no definition to read.
    """
    try:
        workflow = await manager.workflow_detail.get_by_id(workflow_id)
        if workflow is None:
            return {}
        return {
            p.id: p.model if isinstance(p.model, str) and p.model else None for p in workflow.phases
        }
    except Exception:
        logger.debug("Failed to load workflow definition %s", workflow_id, exc_info=True)
        return None


async def _load_agent_session_ids(execution_id: str) -> dict[str, list[str] | None] | None:
    """Which agent-native session ids each of this execution's phases produced.

    Keyed by the phase's ``session_id`` - the uuid4 the HOST assigns per phase
    run. The values are the ids the AGENTS chose for themselves, which is a
    disjoint namespace: the host never passes its id to the agent, so nothing
    else in the system relates the two, and without this an execution cannot be
    traced to the transcripts it produced (#1185).

    A phase maps to MANY, because one phase yields several whenever it
    delegates - a codex phase handing work to claude, a subagent, a resumed
    thread.

    THREE-VALUED, and the caller must keep it that way. ``[]`` means the
    exporter looked and confirmed none; a MISSING KEY means nobody could tell
    us, which is what ``dict.get`` already returns as ``None``. Collapsing the
    two turns a version skew, or a telemetry outage, into a reported loss.

    Lane 2, so it fails soft: an unreachable event store answers "we cannot
    tell you" for every phase rather than failing a read of the domain truth,
    which is in Lane 1 and unaffected.
    """
    try:
        from syn_api._wiring import get_event_store_instance

        # ONE query for the whole execution, not one per phase.
        #
        # ENVELOPE WARNING: `query_by_execution` FLATTENS the payload to the top
        # level, where `query`/`query_recent_by_types` nest it under `data`. So
        # the row IS the payload here, and passing `row["data"]` would read an
        # absent key on every row - the same misreading that once made every
        # healthy capture row report as UNKNOWN. Flattening is lossless for this
        # payload because the write path strips the envelope's own key names
        # from it (`RESERVED_OBSERVATION_KEYS`, then `_EXCLUDED_KEYS`), so a
        # stored payload cannot shadow `session_id`.
        rows = await get_event_store_instance().query_by_execution(
            execution_id, event_type=SESSION_CAPTURE_OBSERVATION
        )
    except Exception:
        logger.debug("Failed to load capture observations for %s", execution_id, exc_info=True)
        return None

    by_session: dict[str, list[str] | None] = {}
    for row in rows:
        session_id = row.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            continue
        # Rows arrive newest first, so the first one wins: a phase re-probed
        # after a retry is described by its most recent verdict.
        if session_id not in by_session:
            by_session[session_id] = read_agent_session_ids(row)
    return by_session


async def _map_phase_detail(
    phase: PhaseExecutionDetail,
    manager: ProjectionManager,
    agent_sessions: dict[str, list[str] | None] | None,
    configured_models: Mapping[str, str | None] | None = None,
) -> PhaseExecution:
    """Map a domain phase to an API PhaseExecution.

    ``agent_sessions`` is the execution-wide capture lookup from
    ``_load_agent_session_ids``, passed in rather than fetched here so the
    query runs once per execution instead of once per phase.
    """
    # A phase with no session id has no timeline to read, which is "we cannot
    # see", not "it did nothing" - the same statement an unreachable query
    # makes, and it must not arrive as an idle phase either.
    ops = await _load_phase_operations(manager, phase.session_id) if phase.session_id else None

    sc = await _phase_cost(manager, phase, configured_models)

    duration_seconds = resolve_duration_seconds(
        phase.status,
        started_at=phase.started_at,
        completed_at=phase.completed_at,
        recorded_seconds=phase.duration_seconds,
    )

    return PhaseExecution(
        phase_id=phase.workflow_phase_id,
        name=phase.name,
        status=phase.status,
        session_id=phase.session_id,
        artifact_id=phase.artifact_id,
        error_message=phase.error_message,
        deliverable_recovered=phase.deliverable_recovered,
        # None stays None: nothing observed a status is not a clean exit (#1319).
        exit_code=phase.exit_code,
        input_tokens=phase.input_tokens,
        output_tokens=phase.output_tokens,
        cache_creation_tokens=sc.cache_creation,
        cache_read_tokens=sc.cache_read,
        cost_usd=Decimal("0"),  # Lane 2: enriched via _enrich_costs from execution_cost (#695)
        duration_seconds=duration_seconds,
        started_at=_parse_dt(phase.started_at),
        completed_at=_parse_dt(phase.completed_at),
        model=sc.agent_model,
        requested_model=sc.requested_model,
        cost_by_model=sc.cost_by_model,
        # `.get` on purpose: a phase with no capture row is "not reported",
        # which is None - never [], which would claim a confirmed empty sweep.
        agent_session_ids=(
            agent_sessions.get(phase.session_id)
            if agent_sessions is not None and phase.session_id
            else None
        ),
        # None stays None for the same reason it does above: it means nothing
        # read this phase's workspace, which is not the same statement as an
        # empty list's "read it, and no branch had moved" (#1200).
        observed_branches=(
            None
            if phase.observed_branches is None
            else [
                BranchObservationInfo(
                    repo=w.repo,
                    branch=w.branch,
                    remote=w.remote,
                    remote_commit=w.remote_commit,
                    remote_commit_at_phase_start=w.remote_commit_at_phase_start,
                    unpushed_commits=w.unpushed_commits,
                )
                for w in phase.observed_branches
            ]
        ),
        # The rows themselves stay a plain list: `activity.telemetry_available`
        # below is the one place that says whether this list is short because
        # nothing happened or because nothing could be read, and a second
        # representation of that fact is a second thing to keep in agreement.
        operations=ops or [],
        # Summarised here, where `ops` are still the projection dataclasses
        # that know how to identify a call. One hop later they are the API
        # model and that rule is gone (#1262). `ops` is passed WHOLE, `None`
        # included: `or []` here would hand the summary an empty timeline and
        # get back the stall reading that #1332 is about.
        activity=summarize_phase_activity(phase, ops, elapsed_seconds=duration_seconds),
    )


def _map_phase_to_response(phase: PhaseExecution) -> PhaseExecutionInfo:
    """Map an API PhaseExecution to an HTTP response model."""
    operations = [
        PhaseOperationInfo(
            operation_id=op.observation_id,
            operation_type=op.operation_type,
            timestamp=str(op.timestamp) if op.timestamp else None,
            tool_name=op.tool_name,
            tool_use_id=op.tool_use_id,
            # `None` here means the row carries no verdict (a tool that has
            # only started), NOT that it went fine. It is rendered True
            # because the dashboard reads this field as a strict boolean and
            # would paint every in-flight operation red otherwise. What
            # changed in #1196 is that a row which DID fail no longer arrives
            # as None: `read_verdict` settles it to False upstream, so this
            # default can no longer swallow a failure.
            success=op.success if op.success is not None else True,
            error_message=op.error_message,
        )
        for op in (phase.operations or [])
    ]
    return PhaseExecutionInfo(
        phase_id=phase.phase_id,
        name=phase.name,
        status=phase.status,
        session_id=phase.session_id,
        artifact_id=phase.artifact_id,
        error_message=phase.error_message,
        deliverable_recovered=phase.deliverable_recovered,
        # Passed through for the reason spelled out below: this constructor
        # re-lists every field by hand and is the hop that drops one (#1319).
        exit_code=phase.exit_code,
        input_tokens=phase.input_tokens,
        output_tokens=phase.output_tokens,
        cache_creation_tokens=phase.cache_creation_tokens,
        cache_read_tokens=phase.cache_read_tokens,
        total_tokens=phase.input_tokens
        + phase.output_tokens
        + phase.cache_creation_tokens
        + phase.cache_read_tokens,
        duration_seconds=phase.duration_seconds,
        cost_usd=Decimal(str(phase.cost_usd)),
        unpriced_observation_count=phase.unpriced_observation_count,
        started_at=str(phase.started_at) if phase.started_at else None,
        completed_at=str(phase.completed_at) if phase.completed_at else None,
        model=phase.model,
        requested_model=phase.requested_model,
        cost_by_model={k: str(v) for k, v in phase.cost_by_model.items()},
        # Same model, passed through rather than rebuilt: this constructor is
        # the hop that has dropped a field twice (#891, #1176), and a phase
        # whose branch nobody knows about is exactly the thing this field
        # exists to stop being invisible (#1200).
        observed_branches=phase.observed_branches,
        # Passed through verbatim, None included: this constructor re-lists
        # every field by hand and is exactly the hop that drops one (#891,
        # #1176). `or []` here would erase the not-reported/confirmed-none
        # distinction the field exists to carry.
        agent_session_ids=phase.agent_session_ids,
        operations=operations,
        # Same model, forwarded whole rather than rebuilt field by field -
        # this constructor is the hop that has dropped a field twice (#891,
        # #1176), and the readings that tell a timed-out phase from a stalled
        # one are worth nothing if one of the four goes missing here (#1262).
        activity=phase.activity,
    )
