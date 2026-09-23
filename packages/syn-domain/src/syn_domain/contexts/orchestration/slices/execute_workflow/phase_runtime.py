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
load-bearing on three paths that are documented at their call sites rather
than here: the unpushed-work guard must run before anything is popped (#1184),
a failing phase's branches must be read before teardown (#1200), and a dying
phase's work must be pushed out of its container before that same teardown
(#1231). Those orderings stay in the processor precisely so a reader of any one
path can see them without opening this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.artifacts import AgentIdentity
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseUsage,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.branch_observation import (
    PhaseStartingPoints,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    SavedWork,
    describe_observed_branches,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import import (
    capture_and_import_phase,
    close_phase_workspaces,
    remember_leader_native_id,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    save_unpushed_work,
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
        #: What each phase spent, in input/output/cache-creation/cache-read
        #: order, as `FinalUsage.resolve` settled it: the harness's own terminal
        #: totals when it reported them, and the deltas observed while it ran
        #: when it was killed before reporting. So "auth" is the USUAL case, not
        #: the only one - a timed-out phase's entry is an estimate, and that
        #: estimate is the whole of what is known about what it cost (#1262).
        #:
        #: Written by `record_agent_run`, which runs BEFORE the exit-status
        #: check that fails the phase, so an entry exists here for every phase
        #: whose agent ran at all - including every one that then died.
        #:
        #: Keyed by (execution_id, phase_id), NOT phase_id alone, for the reason
        #: `_leader_native_ids` above is: two concurrent runs of the same
        #: workflow share a phase id, so a phase-only key lets one run report
        #: the OTHER run's spend. That is worse here than a wrong leader, which
        #: only costs an import - these counts are the whole basis for telling a
        #: stalled phase from one that needed a bigger budget (#1262), and a
        #: number attributed to the wrong execution reads as measurement.
        #:
        #: TAKEN, never merely read: `harvest` pops the entry on the success
        #: path and `usage_for` pops it on the failure path, which between them
        #: are every way a phase ends. `abandon_all` clears nothing here on
        #: purpose - it runs AFTER `usage_for` on the failure path, so clearing
        #: it there would erase the counts the run is on its way out to report.
        self._auth_tokens: dict[tuple[str, str], tuple[int, int, int, int]] = {}
        self._artifact_ids: dict[str, list[str]] = {}
        #: The model each phase's harness announced on its own stream (#1284).
        #: Held here rather than re-read at collection time because the stream
        #: is gone by then; absent means the harness announced nothing.
        #:
        #: NOTE: keyed by phase id alone, so two concurrent runs of the same
        #: workflow overwrite each other, and a restart loses it entirely -
        #: the same two hazards that moved `last_agent_message` onto the event
        #: stream in #1300.
        #:
        #: Still open, and deliberately. `_auth_tokens` above was re-keyed
        #: because its reader was being written at the same time, so the right
        #: signature cost nothing; this one is not the same shape. EVERY
        #: remaining map on this object is keyed by phase alone - `_workspaces`,
        #: `_envs`, `_cmds`, `_session_ids`, `_tokens`, `_artifact_ids`,
        #: `_started_at` - and `finalize`, which clears them, is not given an
        #: execution id at all. Re-keying this field alone would close one
        #: instance of the class and leave the rest open while looking settled.
        #: Tracked as #1311, with the concurrency it needs under #865.
        self._announced_models: dict[str, str] = {}
        #: What each phase's definition declares about repository changes,
        #: recorded when its workspace is attached because that is the only
        #: frame that has both (#1231). Read by `save_unpushed_work` on the
        #: terminal paths, which are handed a phase id and no definition.
        #:
        #: Written by `attach_workspace` in the same breath as the workspace, so
        #: a phase that HAS a container has an entry here. The reader still
        #: needs a value for the gap that cannot happen, and takes the strict
        #: one (True): judging a workspace strictly saves work that might not
        #: have been the phase's, and judging it leniently drops work that was.
        #: Only the second is unrecoverable, so the default goes the other way.
        self._delivers_repo_changes: dict[str, bool] = {}
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
        delivers_repo_changes: bool,
    ) -> None:
        """Hold the container this phase will run in, and how to close it again.

        ``delivers_repo_changes`` is the phase's own declaration, taken HERE
        because this is the moment the workspace it describes starts existing,
        and because the paths that need it later have no phase definition to
        ask: `_fail_execution` and `_cancel_execution` are handed an exception
        and a phase id (#1231). Recording it beside the container is what lets
        `save_unpushed_work` below judge a dying workspace by exactly the rule
        the completion gate judges a finishing one by, without either caller
        having to know the rule exists.

        Required rather than defaulted, for the reason it is required on
        `refuse_to_complete_unsaved_phase`: a hop that forgot it would silently
        restore #1308, and a default would make forgetting invisible.
        """
        self._workspaces[phase_id] = workspace
        self._workspace_cms[phase_id] = workspace_cm
        self._envs[phase_id] = agent_env
        self._cmds[phase_id] = claude_cmd
        self._delivers_repo_changes[phase_id] = delivers_repo_changes

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

    def record_agent_run(
        self,
        phase_id: str,
        *,
        execution_id: str,
        result: AgentExecutionResult,
    ) -> None:
        """Keep what the agent produced until the phase reports or dies."""
        self._tokens[phase_id] = result.tokens
        # What the agent SAID is deliberately not held here. It is the salvage
        # input (#1195, #1300) and is read by a LATER to-do item, so anything
        # this object remembers about it is lost to a restart in between. It
        # rides `AgentExecutionCompletedCommand` onto the event stream instead
        # and is read back off the aggregate.
        announced = result.stream_result.announced_model
        if announced is not None:
            self._announced_models[phase_id] = announced
        # The authoritative totals from the harness result event, which are the
        # only ones that include cache tokens.
        # From the resolved usage rather than the completion command, because a
        # cancelled run has no command and still spent what it spent (#1341).
        self._auth_tokens[execution_id, phase_id] = (
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.usage.cache_creation,
            result.usage.cache_read,
        )

    def workspace_for(self, phase_id: str) -> ManagedWorkspace | None:
        """This phase's workspace, or None once it has been finalised."""
        return self._workspaces.get(phase_id)

    def agent_for(self, phase_id: str, *, provider: str | None) -> AgentIdentity:
        """Who ran this phase: the harness launched, and the model it announced.

        ``provider`` is the caller's because the platform CHOSE it - it picked
        the binary and started it, so there is no observation to make. The
        model is this runtime's because only the stream ever said it, and the
        stream is gone by the time artifacts are collected.

        A phase whose harness announced nothing yields a None model rather than
        the configured one. That is the point: the requested model wearing the
        name of the one that ran would read as proof and not be any (#1284).
        """
        return AgentIdentity(provider=provider, model=self._announced_models.get(phase_id))

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

    def harvest(self, execution_id: str, phase_id: str) -> PhaseHarvest:
        """Take everything a completing phase accumulated, and stop holding it.

        ``execution_id`` names WHOSE phase this is, which `phase_id` alone does
        not: concurrent runs of one workflow share phase ids, so the counts are
        held per run. It is the caller's to-do item's, so it always belongs to
        the run doing the completing. The other fields here are still keyed by
        phase alone and so are still shared - that is #1311, not this.
        """
        self._tokens.pop(phase_id, None)
        return PhaseHarvest(
            started_at=self._started_at.pop(phase_id, datetime.now(UTC)),
            artifact_ids=self._artifact_ids.pop(phase_id, []),
            auth_tokens=self._auth_tokens.pop((execution_id, phase_id), None),
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
        self._announced_models.pop(phase_id, None)
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

    def usage_for(self, execution_id: str, phase_id: str | None) -> PhaseUsage:
        """What THIS run's phase had spent, for a caller about to report it.

        ``execution_id`` is half the identity of the answer and not context.
        Concurrent dispatches share this object, and two runs of one workflow
        share phase ids like "implement", so a phase-only question has no single
        true answer: it returns whichever run recorded last. The caller always
        has the id - it is the failing run's own - so asking with it costs a
        parameter and removes the case entirely.

        TAKES the entry rather than reading it, the way `harvest` does on the
        success path. Between them those are every way a phase ends, so nothing
        is left behind for a processor that outlives the run - and since the
        failure path never harvests, a read that left the entry in place would
        make this map grow for the life of the process. One read per phase is
        what the counts are for: this is the last frame in which anything can
        ask (#1262).

        MUST still be called before the caller's first await on a terminal path,
        for the reason `timings` must be. A frozen `PhaseUsage` rather than the
        live accumulator is what makes that a snapshot instead of a promise.

        Zeros for a phase whose agent never ran - it spent nothing, and there is
        no "unknown" to distinguish; see `PhaseUsage`.
        """
        inp, out, cache_creation, cache_read = self._auth_tokens.pop(
            (execution_id, phase_id or ""), (0, 0, 0, 0)
        )
        return PhaseUsage(
            input_tokens=inp,
            output_tokens=out,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
        )

    async def save_unpushed_work(self, phase_id: str | None, *, execution_id: str) -> SavedWork:
        """Push a dying phase's unsaved work out of its container (#1231).

        MUST be called before `abandon_all`, for the reason `observe` must be:
        once teardown has run, work that was only in that workspace is not
        somewhere else, it is nowhere. That ordering is the whole of this
        method's contract and it is documented at the two call sites, beside
        the teardown it has to precede.

        The caller says which phase died and which execution it belonged to.
        Which container that is, what the phase declared about repository
        changes, and what it means for there to be no container at all are
        decided here: a phase with no workspace is holding nothing that dying
        could erase, which is `SavedWork()` - the same silence a workspace that
        was genuinely clean produces, because for a caller deciding what to
        tell an operator the two really are one answer.
        """
        workspace = self._workspaces.get(phase_id) if phase_id is not None else None
        if phase_id is None or workspace is None:
            return SavedWork()
        return await save_unpushed_work(
            workspace,
            execution_id=execution_id,
            phase_id=phase_id,
            delivers_repo_changes=self._delivers_repo_changes.get(phase_id, True),
        )

    async def observe(self, phase_id: str | None) -> ObservedBranches | None:
        """Where a dying phase's branches stand, or None when nobody looked."""
        return await self._starting_points.observe(phase_id)

    async def describe_work(self, phase_id: str | None) -> str | None:
        """The same reading as `observe`, in the words an operator reads.

        Two callers need this fact and they need it in two shapes: a failing
        execution stores the structured `ObservedBranches` on its event, and a
        SALVAGED phase - which does not fail, so never reaches that path -
        needs it as prose to put in the artifact it recovered (#1300). Saying
        it here rather than at either call site keeps one answer to "where does
        this phase's work stand", and keeps the collector from ever learning
        what a remote or a starting point is.
        """
        observed = await self.observe(phase_id)
        return describe_observed_branches(observed) if observed is not None else None

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
        self._delivers_repo_changes.clear()

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
