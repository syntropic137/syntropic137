"""Everything a phase holds while it runs, and how it gives it up.

WHAT THE PROCESSOR WAS CARRYING INSTEAD OF DISPATCHING. Thirteen maps keyed by
phase id lived on `WorkflowExecutionProcessor`, and six of its methods opened,
read and unwound them inline. Every one of those methods therefore knew that
per-phase state IS a set of parallel dicts: `_handle_run_agent` knew the auth
totals are a four-tuple in input/output/cache-creation/cache-read order,
`_finalize_phase` knew which five to pop and in which order relative to
teardown, and `_fail_execution` knew that two of them must be COPIED before the
first await because teardown empties them (#1036). None of that is a decision
the processor makes, and all of it had to be re-threaded by hand every time a
step moved - which is the cost the last three reworks kept paying (#1203).

WHY ONE OBJECT RATHER THAN ONE PER MAP. The maps are not independent. A
workspace, its context manager, its env, its command line, its session id and
its starting point are the same phase seen six ways, and they are only ever
correct together: a workspace popped without its context manager leaks a
container, a starting point outliving its workspace can only ever be paired
with the wrong one, and a session id cleared early times the phase to the end
of cleanup. Splitting them is what let those pairs drift; holding them here is
what makes the drift unrepresentable.

WHAT THIS DOES NOT DECIDE. It never talks to the aggregate, builds a command,
or judges whether a phase succeeded. It is asked to hold, to hand back, and to
let go - the caller decides when, and the ORDER in which it decides is
load-bearing on two paths that are documented at their call sites rather than
here: the unpushed-work guard must run before anything is popped (#1184), and a
failing phase's branches must be read before teardown (#1200). Those orderings
stay in the processor precisely so a reader of the completion path can see them
without opening this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import import (
    capture_and_import_phase,
    close_phase_workspaces,
    remember_leader_native_id,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    PhaseStartingPoints,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort
    from syn_domain.contexts.agent_sessions.import_ledger import ImportLedgerPort
    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import ObservedBranches
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
        StreamResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
        SessionLifecycleManager,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
        TokenAccumulator,
    )


@dataclass(frozen=True)
class PhaseLaunch:
    """What a phase needs handed back to it in order to run its agent.

    One object because the four were read one line after another from four
    different maps and are meaningless apart: a workspace with another phase's
    env would run the right container with the wrong credentials.
    """

    workspace: ManagedWorkspace
    agent_env: dict[str, str]
    claude_cmd: list[str]
    started_at: datetime
    session_manager: SessionLifecycleManager | None


@dataclass(frozen=True)
class PhaseHarvest:
    """What a completing phase leaves behind, taken and forgotten in one step.

    `auth_tokens` is the authoritative four-tuple from the harness result event
    - input, output, cache-creation, cache-read - or None when the phase never
    reported one. That ORDER is the reason this is a type and not four returns:
    it was written in one method and unpacked in another, and the two could
    only ever disagree silently.
    """

    started_at: datetime
    artifact_ids: list[str]
    auth_tokens: tuple[int, int, int, int] | None


@dataclass(frozen=True)
class PhaseTimings:
    """When each phase started and which session it ran under, frozen.

    A SNAPSHOT, NOT A VIEW (#1036). The failure path reads both maps AFTER
    awaiting teardown, and teardown clears them; reading late timed the phase
    to the end of cleanup and lost its session id entirely. Copied rather than
    merely read early because the failure path awaits in between and concurrent
    dispatches share the maps.
    """

    started_at: Mapping[str, datetime]
    session_ids: Mapping[str, str]


class PhaseRuntime:
    """The workspaces, sessions and tallies of the phases currently running."""

    def __init__(
        self,
        *,
        capture_port: SessionCapturePort | None,
        session_store: SessionStorePort | None,
        writer: ObservabilityRecorder | None,
        ledger: ImportLedgerPort | None,
        starting_points: PhaseStartingPoints | None = None,
    ) -> None:
        # None means capture is OFF, not broken: a deployment with no store
        # configured must behave identically to one from before this existed.
        self._capture_port = capture_port
        # Where a delegate's transcript is read back from. Optional because a
        # deployment without a session store simply imports no delegates; it
        # must never be a reason a phase fails.
        self._session_store = session_store
        self._writer = writer
        self._ledger = ledger

        self._workspaces: dict[str, ManagedWorkspace] = {}
        self._starting_points = starting_points or PhaseStartingPoints()
        self._workspace_cms: dict[str, AbstractAsyncContextManager[ManagedWorkspace]] = {}
        self._envs: dict[str, dict[str, str]] = {}
        self._cmds: dict[str, list[str]] = {}
        self._session_managers: dict[str, SessionLifecycleManager] = {}
        # Per-phase so `finalize` can attribute the capture.
        self._session_ids: dict[str, str] = {}
        #: The id each phase's own harness announced on its stream, which is
        #: what the delegate import subtracts from the sweep.
        #:
        #: Keyed by (execution_id, phase_id), NOT phase_id alone. The processor
        #: that owns this runtime is shared across concurrent dispatches, so two
        #: runs of the same workflow share a phase id. A phase-only key lets one
        #: run read the OTHER run's leader, and a leader id absent from this
        #: run's sweep takes the refusal path: no delegate imported, only a log
        #: line. Popped on success so a completed phase leaves nothing behind.
        self._leader_native_ids: dict[tuple[str, str], str] = {}
        self._tokens: dict[str, TokenAccumulator] = {}
        self._auth_tokens: dict[str, tuple[int, int, int, int]] = {}
        self._artifact_ids: dict[str, list[str]] = {}
        self._said: dict[str, str] = {}  # last agent message, for #1195 recovery
        self._started_at: dict[str, datetime] = {}

    # ── while a phase is being provisioned ────────────────────────────────

    def begin(
        self,
        phase_id: str,
        *,
        session_manager: SessionLifecycleManager,
        started_at: datetime,
    ) -> None:
        """Take charge of a phase whose session has opened but has no workspace yet."""
        self._session_managers[phase_id] = session_manager
        self._started_at[phase_id] = started_at

    def attach_workspace(
        self,
        phase_id: str,
        *,
        workspace: ManagedWorkspace,
        workspace_cm: AbstractAsyncContextManager[ManagedWorkspace],
        agent_env: dict[str, str],
        claude_cmd: list[str],
    ) -> None:
        """Hold the container this phase will run in, and how to close it again."""
        self._workspaces[phase_id] = workspace
        self._workspace_cms[phase_id] = workspace_cm
        self._envs[phase_id] = agent_env
        self._cmds[phase_id] = claude_cmd

    async def record_starting_point(self, phase_id: str) -> None:
        """Read where this phase's repositories stand, before its agent runs.

        Separate from `attach_workspace` because it is the only step here that
        talks to the workspace, and the only one whose timing is a domain
        decision rather than bookkeeping: after the agent has run, "where was
        this ref" is no longer a fact anyone can read (#1200).
        """
        workspace = self._workspaces.get(phase_id)
        if workspace is not None:
            await self._starting_points.record(phase_id, workspace)

    # ── while its agent runs ──────────────────────────────────────────────

    def launch(self, phase_id: str, *, session_id: str) -> PhaseLaunch:
        """What this phase runs with, and the session it runs under from now on.

        Raises KeyError for a phase that holds no workspace: reaching the agent
        without one means the to-do list dispatched RUN_AGENT before
        PROVISION_WORKSPACE, which is a broken projection and not something to
        paper over with a default.
        """
        self._session_ids[phase_id] = session_id
        return PhaseLaunch(
            workspace=self._workspaces[phase_id],
            agent_env=self._envs[phase_id],
            claude_cmd=self._cmds[phase_id],
            started_at=self._started_at.get(phase_id, datetime.now(UTC)),
            session_manager=self._session_managers.get(phase_id),
        )

    def remember_leader(
        self, phase_id: str, *, execution_id: str, stream_result: StreamResult
    ) -> None:
        """Note the id this phase's own harness announced, for the delegate sweep."""
        remember_leader_native_id(self._leader_native_ids, (execution_id, phase_id), stream_result)

    def record_agent_run(self, phase_id: str, result: AgentExecutionResult) -> None:
        """Keep what the agent produced until the phase reports or dies."""
        self._tokens[phase_id] = result.tokens
        self._said[phase_id] = result.stream_result.last_agent_message or ""
        # The authoritative totals from the harness result event, which are the
        # only ones that include cache tokens.
        self._auth_tokens[phase_id] = (
            result.command.input_tokens,
            result.command.output_tokens,
            result.command.cache_creation_tokens,
            result.command.cache_read_tokens,
        )

    def workspace_for(self, phase_id: str) -> ManagedWorkspace | None:
        """This phase's workspace, or None once it has been finalised."""
        return self._workspaces.get(phase_id)

    def take_last_message(self, phase_id: str) -> str | None:
        """What the agent said last, read once and forgotten (#1195)."""
        return self._said.pop(phase_id, None)

    def record_artifacts(self, phase_id: str, artifact_ids: list[str]) -> None:
        """Hold what this phase collected until it reports."""
        self._artifact_ids[phase_id] = artifact_ids

    # ── when a phase completes ────────────────────────────────────────────

    @property
    def live_workspaces(self) -> Mapping[str, ManagedWorkspace]:
        """The workspaces that still exist, for a caller that must inspect one.

        Read-only and deliberately narrow: the unpushed-work guard is handed
        this and the to-do item and needs nothing else (#1184).
        """
        return self._workspaces

    def harvest(self, phase_id: str) -> PhaseHarvest:
        """Take everything a completing phase accumulated, and stop holding it."""
        self._tokens.pop(phase_id, None)
        return PhaseHarvest(
            started_at=self._started_at.pop(phase_id, datetime.now(UTC)),
            artifact_ids=self._artifact_ids.pop(phase_id, []),
            auth_tokens=self._auth_tokens.pop(phase_id, None),
        )

    async def finalize(
        self,
        phase_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        total_tokens: int,
        duration_seconds: float,
    ) -> None:
        """Close this phase's session and give up everything it was holding."""
        session_mgr = self._session_managers.pop(phase_id, None)
        if session_mgr is not None:
            await session_mgr.complete_success(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
                total_tokens=total_tokens,
                duration_seconds=duration_seconds,
                source="processor",
            )

        workspace = self._workspaces.pop(phase_id, None)
        self._starting_points.forget(phase_id)
        session_id = self._session_ids.pop(phase_id, "")
        self._envs.pop(phase_id, None)
        self._cmds.pop(phase_id, None)
        workspace_cm = self._workspace_cms.pop(phase_id, None)

        # BEFORE teardown: once the container is gone so is the spool, and a
        # later probe cannot tell "stored" from "lost forever".
        await capture_and_import_phase(
            self._capture_port,
            workspace,
            session_store=self._session_store,
            writer=self._writer,
            leader_native_ids=self._leader_native_ids,
            session_id=session_id,
            phase_id=phase_id,
            ledger=self._ledger,
        )

        if workspace_cm is not None:
            await workspace_cm.__aexit__(None, None, None)

    # ── when the execution ends ───────────────────────────────────────────

    def timings(self) -> PhaseTimings:
        """Freeze when each phase started and which session it ran under.

        MUST be taken before the caller's first await on a terminal path; see
        `PhaseTimings` for what reading it late cost (#1036).
        """
        return PhaseTimings(started_at=dict(self._started_at), session_ids=dict(self._session_ids))

    async def observe(self, phase_id: str | None) -> ObservedBranches | None:
        """Where a dying phase's branches stand, or None when nobody looked."""
        return await self._starting_points.observe(phase_id)

    async def report_cancelled(self, reason: str) -> None:
        """Close every open session as cancelled."""
        for _pid, mgr in list(self._session_managers.items()):
            await mgr.complete_cancelled(reason=reason)

    async def report_failed(self, error_message: str) -> None:
        """Close every open session as failed, carrying the same account of why."""
        for _pid, mgr in list(self._session_managers.items()):
            await mgr.complete_failure(error_message=error_message)

    async def abandon_all(self, context: str) -> None:
        """Probe, import and tear down every phase still holding a workspace.

        Both terminal paths cleared exactly this set after closing workspaces;
        they differ only in how they complete their sessions, which is why that
        step is the caller's and this one is not.
        """
        await close_phase_workspaces(
            context,
            workspace_cms=self._workspace_cms,
            workspaces=self._workspaces,
            session_ids=self._session_ids,
            leader_native_ids=self._leader_native_ids,
            capture_port=self._capture_port,
            session_store=self._session_store,
            writer=self._writer,
            ledger=self._ledger,
        )
        self._session_managers.clear()
        self._workspaces.clear()
        self._starting_points.forget_all()
        self._envs.clear()
        self._cmds.clear()

    @property
    def is_idle(self) -> bool:
        """True when no phase is holding anything - the postcondition of `abandon_all`."""
        return not (
            self._workspaces
            or self._workspace_cms
            or self._envs
            or self._cmds
            or self._session_managers
            or self._session_ids
        )
