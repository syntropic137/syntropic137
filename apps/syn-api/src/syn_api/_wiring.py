"""Internal composition root - wires adapters to domain handlers.

Consolidates the duplicated factory-call patterns from CLI and dashboard
into a single location. All v1 module functions use these helpers to
obtain properly-configured domain handlers and projections.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_adapters.control import ExecutionController
    from syn_adapters.control.commands import ControlSignal
    from syn_adapters.control.ports import SignalQueuePort
    from syn_adapters.conversations.minio import MinioConversationStorage
    from syn_adapters.events.store import AgentEventStore
    from syn_adapters.projections.realtime import RealTimeProjection
    from syn_adapters.storage.claude_plugin_storage.memory import InMemoryClaudePluginStorage
    from syn_adapters.storage.claude_plugin_storage.minio import MinioClaudePluginStorage
    from syn_adapters.storage.repositories import RepositoryAdapter
    from syn_adapters.storage.skill_storage.memory import InMemorySkillStorage
    from syn_adapters.storage.skill_storage.minio import MinioSkillStorage
    from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService
    from syn_api.services.claude_plugin_materializer import ClaudePluginMaterializer
    from syn_api.services.claude_plugin_resolution_service import ClaudePluginResolutionService
    from syn_api.services.skill_materializer import SkillMaterializer
    from syn_api.services.skill_resolution_service import SkillResolutionService
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.agent_sessions import ImportLedgerPort
    from syn_domain.contexts.github.services import WebhookHealthTracker
    from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
        _BudgetChecker,
        _ExecutionService,
    )
    from syn_domain.contexts.github.slices.event_pipeline.dedup_port import DedupPort
    from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHAStore
    from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
    from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
        ClaudePluginRegistrationAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_global_claude_plugin_registry.GlobalClaudePluginRegistryAggregate import (
        GlobalClaudePluginRegistryAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )
    from syn_domain.contexts.orchestration.slices.list_claude_plugins import (
        ListClaudePluginsHandler,
    )
    from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins import (
        AddGlobalClaudePluginHandler,
        GlobalClaudePluginsProjection,
        ListGlobalClaudePluginsHandler,
        RemoveGlobalClaudePluginHandler,
    )
    from syn_domain.contexts.orchestration.slices.register_claude_plugin import (
        RegisterClaudePluginHandler,
    )
    from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
        ClaudePluginLockProjection,
    )
    from syn_domain.contexts.orchestration.slices.register_skill import RegisterSkillHandler
    from syn_domain.contexts.orchestration.slices.register_skill.projection import (
        SkillLockProjection,
    )
    from syn_domain.contexts.orchestration.slices.show_claude_plugin import (
        ShowClaudePluginHandler,
    )
    from syn_shared.settings.config import Settings
    from syn_shared.settings.github import GitHubAppSettings

from syn_adapters.conversations import get_conversation_storage
from syn_adapters.events import get_event_store
from syn_adapters.projections.manager import ProjectionManager, get_projection_manager

# Re-exported, not defined here: joining the event publisher to the projection
# manager needs neither half of this app, and the artifact backfill migration
# calls it too (#1215). Routes keep importing it from the composition root.
from syn_adapters.projections.sync import (
    sync_published_events_to_projections as sync_published_events_to_projections,
)
from syn_adapters.session_store import HttpSessionStore
from syn_adapters.storage import (
    connect_event_store,
    disconnect_event_store,
    get_artifact_repository,
    get_event_publisher,
    get_event_store_client,
    get_session_repository,
    get_workflow_repository,
)
from syn_adapters.storage.artifact_storage import get_artifact_storage
from syn_adapters.storage.repositories import (
    get_trigger_repository,
    get_workflow_execution_repository,
)
from syn_adapters.workspace_backends.service import WorkspaceService
from syn_domain.contexts.artifacts import ArtifactQueryService
from syn_domain.contexts.orchestration import WorkflowExecutionProcessor
from syn_shared.agents import (
    AgentProvider,
    UnsupportedAgentProviderError,
    require_executable_provider,
)
from syn_shared.env_constants import (
    ENV_CLAUDE_CODE_ENABLE_TELEMETRY,
    ENV_OTEL_EXPORTER_OTLP_ENDPOINT,
)


async def ensure_connected() -> None:
    """Ensure the event store connection is established."""
    await connect_event_store()


async def disconnect() -> None:
    """Gracefully disconnect from the event store."""
    await disconnect_event_store()


def get_projection_mgr() -> ProjectionManager:
    """Return the singleton ProjectionManager."""
    return get_projection_manager()


def _build_session_store(settings: Settings) -> HttpSessionStore | None:
    """The read side of the session store, or None when it is not configured.

    Returns None rather than raising: the store is opt-in, and a deployment
    without one simply imports no delegate cost. Failing startup over an
    optional telemetry source would trade a partial cost figure for no platform
    at all.
    """
    store = settings.session_store
    if not store.is_enabled or not store.url:
        return None

    # The READ token: this client only ever fetches. Handing it the write
    # token yields 401 on every fetch against a store that scopes the two
    # separately, and a 401 is classified as transient - so every delegate
    # would retry forever and none would ever be priced.
    read_token = store.effective_read_token
    token = read_token.get_secret_value() if read_token else None
    return HttpSessionStore(base_url=store.url, auth_token=token)


def _build_workspace_telemetry_env() -> dict[str, str]:
    """Build OTel env vars to inject into workspace containers.

    When collector_url is configured, enables Claude Code's OTLP export so
    token/cost metrics and API-level events flow through the two-channel
    observability pipeline (plugin hooks + OTel). See ADR-056.

    Returns empty dict if collector_url is not set; OTel silently no-ops
    inside the container (CLAUDE_CODE_ENABLE_TELEMETRY is already baked into
    the workspace image as a default, so no-endpoint is a graceful fallback).
    """
    from syn_shared.settings import get_settings

    collector_url = get_settings().collector_url
    if not collector_url:
        return {}
    return {
        ENV_CLAUDE_CODE_ENABLE_TELEMETRY: "1",
        ENV_OTEL_EXPORTER_OTLP_ENDPOINT: collector_url,
    }


async def get_execution_processor() -> WorkflowExecutionProcessor:
    """Wire up WorkflowExecutionProcessor with all dependencies (ISS-196).

    Replaces the old get_execution_engine(); uses the Processor To-Do List
    pattern instead of the imperative WorkflowExecutionEngine.
    """
    event_store = get_event_store()
    await event_store.initialize()

    artifact_storage = await get_artifact_storage()
    conversation_storage = await get_conversation_storage()

    manager = get_projection_manager()
    artifact_query = ArtifactQueryService(manager.artifact_list)

    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )
    from syn_shared.settings.workspace import WorkspaceSettings

    ws_settings = WorkspaceSettings()
    # The workspace service is the Docker headless path: claude -p and
    # codex exec both run there, keeping the stream-json pipeline, Envoy
    # token accounting, and telemetry.
    ws_config = WorkspaceServiceConfig(image=ws_settings.docker_image)

    # WHY (issue #726, PR2): the materializer turns ResolvedClaudePlugin
    # entries on each phase into workspace files; the processor passes it
    # through to ``WorkspaceProvisionHandler`` per dispatch.
    claude_plugin_materializer = await get_claude_plugin_materializer()

    # WHY (issue #772): mirrors the claude-plugin materializer above; turns
    # ResolvedSkill entries on each phase into workspace files, then the
    # processor threads it through to WorkspaceProvisionHandler per dispatch.
    skill_materializer = await get_skill_materializer()

    # Session capture (APS-V1-0004). Off unless a store URL is configured, and
    # off is the DEFAULT: no deployment gains a dependency on a store it never
    # asked for. When on, the processor probes each workspace before teardown
    # and records the verdict on the observability lane.
    #
    # `event_store` is the same recorder the rest of Lane 2 writes through, so
    # the capture indicator lands beside the telemetry it explains rather than
    # in a store of its own.
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCaptureService,
    )
    from syn_shared.settings import get_settings

    _settings = get_settings()
    session_capture = SessionCaptureService(
        _settings.session_store,
        _settings.app_environment,
        event_store,
    )

    return WorkflowExecutionProcessor(
        execution_repository=get_workflow_execution_repository(),
        session_repository=get_session_repository(),
        workspace_service=WorkspaceService.create(
            config=ws_config,
            environment=_build_workspace_telemetry_env(),
        ),
        artifact_repository=get_artifact_repository(),
        artifact_content_storage=artifact_storage,
        artifact_query=artifact_query,
        conversation_storage=conversation_storage,
        observability_writer=event_store,
        controller=get_controller(),
        prompt_builder=_build_workspace_prompt,
        command_builder=_build_agent_command,
        todo_projection=ExecutionTodoProjection(store=get_projection_store()),
        claude_plugin_materializer=claude_plugin_materializer,
        skill_materializer=skill_materializer,
        session_capture=session_capture,
        session_store=_build_session_store(_settings),
        import_ledger=_create_import_ledger(),
    )


def _build_claude_command(
    phase: ExecutablePhase,
    prompt: str,
) -> list[str]:
    """Build the Claude CLI command for agent execution."""
    # `AgentConfiguration.model` is `str | None` because a codex phase can
    # leave it unset (see syn_shared.agents.DEFAULT_CLAUDE_MODEL).
    # A claude-provider phase always resolves a concrete model (the domain
    # default "haiku" when the YAML omits `model:`), so `None` here would
    # indicate a construction bug elsewhere, not a real "unset" case worth
    # silently tolerating - fail loudly instead of forwarding `--model None`.
    model = phase.agent_config.model
    if model is None:
        msg = (
            f"Claude phase '{phase.phase_id}' resolved to a None model - "
            "AgentConfiguration.model should always default to a claude "
            "alias for provider='claude'."
        )
        raise ValueError(msg)
    cmd = [
        "claude",
        "--model",
        model,
        "--verbose",
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "-p",
        prompt,
    ]

    # `--tools` is AVAILABILITY; `--allowedTools` is auto-approval. We emitted
    # the second while the field is named and documented as the first, and the
    # command already carries --dangerously-skip-permissions, so auto-approving
    # was a no-op twice over: a phase declaring three tools could use all of
    # them (issue #964). Verified against claude 2.1.251:
    #   --tools <tools...>  Specify the list of available tools from the
    #                       built-in set. Use "" to disable all tools ...
    #
    # ONE flag with a comma-joined list, not the flag repeated. `--tools` is
    # VARIADIC (`<tools...>`), which has two consequences:
    #
    #   1. Repeating it keeps only the last occurrence, so the flag-per-tool
    #      form would have restricted every phase to its last-declared tool.
    #   2. It is GREEDY - it swallows any positional that follows it. Verified
    #      against claude 2.1.251:
    #        $ claude -p --tools Bash,Read "say ok"
    #        Error: Input must be provided either through stdin or as a prompt
    #               argument when using --print
    #      The prompt was eaten as a tool name.
    #
    # ORDERING IS THEREFORE LOAD-BEARING: `-p <prompt>` must come BEFORE
    # `--tools`. Moving this extend() earlier breaks every claude phase, with
    # an error that names stdin rather than argument order. Pinned by
    # test_the_prompt_must_precede_the_variadic_tools_flag.
    if phase.agent_config.allowed_tools:
        cmd.extend(["--tools", ",".join(phase.agent_config.allowed_tools)])

    return cmd


from syn_api._codex_command import (  # noqa: E402
    UnsupportedToolPolicyError,
    _build_codex_command,
    _resolve_sandbox,
    apply_tool_policy_to_prompt,
)


def _build_agent_command(
    phase: ExecutablePhase,
    prompt: str,
) -> list[str]:
    """Build the command selected by the phase provider.

    Exhaustive on purpose: every known provider is named, and anything else
    raises. The previous ``return _build_claude_command(...)`` fall-through
    meant an unknown or removed provider - a stored ``claude-interactive``
    template rehydrated from history, say - quietly ran as headless Claude and
    reported success.
    """
    provider = require_executable_provider(
        phase.agent_config.provider,
        phase_id=phase.phase_id,
    )
    # Every harness carries the grant in the prompt; only claude can also
    # enforce it on the command line.
    scoped_prompt = apply_tool_policy_to_prompt(prompt, phase.agent_config.allowed_tools)
    if provider is AgentProvider.CODEX:
        if phase.agent_config.allowed_tools:
            raise UnsupportedToolPolicyError(
                provider=str(provider),
                phase_id=phase.phase_id,
                declared=list(phase.agent_config.allowed_tools),
            )
        return _build_codex_command(
            scoped_prompt,
            phase.agent_config.model,
            _resolve_sandbox(phase.agent_config.sandbox, phase_id=phase.phase_id),
        )
    if provider is AgentProvider.CLAUDE:
        return _build_claude_command(phase, scoped_prompt)
    raise UnsupportedAgentProviderError(provider, phase_id=phase.phase_id)


def _owner_repo_from_url(url: str | None) -> str:
    """Extract owner/repo from a GitHub HTTPS URL. Empty string if not a github URL."""
    if not url:
        return ""
    stripped = url.rstrip("/").removesuffix(".git")
    parts = stripped.split("/")
    if len(parts) >= 5 and parts[2] == "github.com":
        return f"{parts[3]}/{parts[4]}"
    return ""


def _substitute_builtins(
    template: str,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
) -> str:
    """Layer 1: Replace built-in variables in the prompt template."""
    result = template.replace("{{execution_id}}", execution_id)
    result = result.replace("{{workflow_id}}", workflow_id)
    result = result.replace("{{repo_url}}", repo_url or "")
    # {{repository}} is a deprecated single-repo convenience -- derived from the
    # primary repo's URL as owner/repo. Tracked for removal in #715.
    # Multi-repo workflows should use {{repos}} (CSV of HTTPS URLs) or discover
    # repos from /workspace/repos/ at runtime instead.
    if "{{repository}}" in result:
        logger.warning(
            "Workflow %s uses deprecated {{repository}} template variable. "
            "It will be removed in a future release. Migrate to /workspace/repos/ "
            "discovery (single-repo) or {{repos}} (multi-repo). "
            "Track: https://github.com/syntropic137/syntropic137/issues/715",
            workflow_id,
        )
        result = result.replace("{{repository}}", _owner_repo_from_url(repo_url))
    return result


def _substitute_inputs(
    template: str,
    phase: ExecutablePhase,
    inputs: dict[str, Any] | None,
    phase_outputs: dict[str, str],
) -> str:
    """Layers 2a-2d: Replace workflow inputs, phase inputs, outputs, and $ARGUMENTS."""
    result = template

    # Layer 2a: Workflow inputs
    if inputs:
        for key, value in inputs.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))

    # Layer 2b: Phase-level static inputs
    for phase_input in phase.inputs:
        if phase_input.value is not None:
            result = result.replace(f"{{{{{phase_input.name}}}}}", phase_input.value)

    # Layer 2c: Phase outputs inline
    for pid, content in phase_outputs.items():
        result = result.replace(f"{{{{{pid}}}}}", content[:2000])

    # Layer 2d: $ARGUMENTS substitution (ISS-211 CC command pattern)
    task = (inputs or {}).get("task", "")
    result = result.replace("$ARGUMENTS", str(task))

    return result


def _build_context_appendix(phase_outputs: dict[str, str]) -> str:
    """Layer 3: Build the context appendix from previous phase outputs."""
    parts = ["\n## Context from Previous Phases"]
    for pid, content in phase_outputs.items():
        parts.append(f"\n### Phase {pid}\n{content[:2000]}")
    return "\n".join(parts)


async def _build_workspace_prompt(
    phase: ExecutablePhase,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
    phase_outputs: dict[str, str],
    inputs: dict[str, Any] | None = None,
) -> str:
    """Build the workspace prompt for a phase.

    Substitution layers (in order):
    1. Built-in variables: {{execution_id}}, {{workflow_id}}, {{repo_url}}
    2a. Workflow inputs: {{key}} → value from inputs dict
    2b. Phase-level static inputs: {{name}} → value from phase definition
    2c. Phase outputs: {{phase-id}} → previous phase artifact content (inline)
    2d. $ARGUMENTS → task string from inputs["task"]
    3. Context appendix: previous phase outputs appended as fallback section
    """
    from syn_domain.contexts.orchestration import render_workspace_prompt

    phase_prompt = _substitute_builtins(phase.prompt_template, execution_id, workflow_id, repo_url)
    phase_prompt = _substitute_inputs(phase_prompt, phase, inputs, phase_outputs)

    # The preamble describes the workspace this phase actually got, so it is
    # rendered per phase rather than shared: `clone_repos: false` means no
    # checkout, and telling that agent the repository is on disk is what made
    # the merged gate unusable (#1187).
    prompt_parts = [
        render_workspace_prompt(clone_repos=phase.clone_repos),
        f"\n## Task\n{phase_prompt}",
    ]

    if phase_outputs:
        prompt_parts.append(_build_context_appendix(phase_outputs))

    return "\n".join(prompt_parts)


def get_workflow_repo():
    """Return the workflow template repository."""
    return get_workflow_repository()


def get_session_repo():
    """Return the agent session repository."""
    return get_session_repository()


def get_artifact_repo():
    """Return the artifact repository."""
    return get_artifact_repository()


def get_publisher():
    """Return the event publisher."""
    return get_event_publisher()


class _InMemoryAggregateRepository:
    """Simple in-memory repository for test mode (trigger aggregates).

    InMemoryTriggerQueryStore from the domain layer lacks the save()/get_by_id()
    interface required by domain handlers, so we provide a minimal implementation.

    Uses ``Any`` deliberately: this is a generic test double that stores
    arbitrary aggregates; concrete types are only known at call sites.
    """

    def __init__(self) -> None:
        self._aggregates: dict[str, Any] = {}

    async def get_by_id(self, aggregate_id: str) -> Any:  # noqa: ANN401
        return self._aggregates.get(aggregate_id)

    async def save(self, aggregate: Any) -> None:  # noqa: ANN401
        agg_id = str(aggregate.id) if hasattr(aggregate, "id") else str(aggregate.trigger_id)
        self._aggregates[agg_id] = aggregate

    async def save_new(self, aggregate: Any) -> None:  # noqa: ANN401
        """Persist a brand-new aggregate (mirrors Repository protocol)."""
        await self.save(aggregate)

    async def exists(self, aggregate_id: str) -> bool:
        return aggregate_id in self._aggregates


_test_trigger_repo: _InMemoryAggregateRepository | None = None


def get_trigger_repo():
    """Return the trigger rule repository.

    In test mode, returns a NullRepository since InMemoryTriggerQueryStore
    lacks save()/get_by_id() required by domain handlers.
    """
    from syn_shared.settings import get_settings

    settings = get_settings()
    if settings.uses_in_memory_stores:
        global _test_trigger_repo
        if _test_trigger_repo is None:
            _test_trigger_repo = _InMemoryAggregateRepository()
        return _test_trigger_repo

    return get_trigger_repository()


def get_trigger_store():
    """Return the trigger query store."""
    from syn_domain.contexts.github import get_trigger_query_store

    return get_trigger_query_store()


# ---------------------------------------------------------------------------
# Event pipeline (ISS-386) - dedup + unified ingestion
# ---------------------------------------------------------------------------

_event_pipeline_singleton: object | None = None
_webhook_health_tracker_singleton: object | None = None


def get_event_pipeline() -> EventPipeline:
    """Return the singleton EventPipeline with Redis dedup (in-memory fallback)."""
    from syn_domain.contexts.github import EvaluateWebhookHandler, EventPipeline

    global _event_pipeline_singleton
    if _event_pipeline_singleton is not None:
        assert isinstance(_event_pipeline_singleton, EventPipeline)
        return _event_pipeline_singleton
    from syn_shared.settings import get_settings

    settings = get_settings()

    dedup = _create_dedup_adapter()
    evaluator = EvaluateWebhookHandler(
        store=get_trigger_store(),
        repository=get_trigger_repo(),
        dispatch_rate_limit=settings.polling.dispatch_rate_limit,
        dispatch_rate_window_seconds=settings.polling.dispatch_rate_window_seconds,
    )
    pipeline = EventPipeline(
        dedup=dedup,
        evaluator=evaluator,
    )
    _event_pipeline_singleton = pipeline
    return pipeline


def _create_dedup_adapter() -> DedupPort:
    """Create the appropriate dedup adapter based on environment.

    Priority (ADR-060): Postgres (durable) > Redis (cache) > In-memory (tests).
    """
    from syn_shared.settings import get_settings

    settings = get_settings()

    if settings.uses_in_memory_stores:
        from syn_adapters.dedup.memory_dedup import InMemoryDedupAdapter

        return InMemoryDedupAdapter()

    # ADR-060: Prefer Postgres for durable dedup that survives restarts
    if settings.syn_observability_db_url:
        try:
            from syn_api._wiring_db import get_shared_db_pool

            pool = get_shared_db_pool()
            if pool is not None:
                from syn_adapters.dedup.postgres_dedup import PostgresDedupAdapter

                ttl_days = max(1, -(-settings.polling.dedup_ttl_seconds // 86400))
                logger.info("EventPipeline using Postgres dedup (ADR-060)")
                return PostgresDedupAdapter(pool, ttl_days=ttl_days)  # type: ignore[arg-type]  # asyncpg.Pool vs AsyncConnectionPool
        except Exception:
            logger.warning(
                "Postgres dedup unavailable; falling back to Redis",
                exc_info=True,
            )

    try:
        import redis.asyncio as aioredis

        from syn_adapters.dedup.redis_dedup import RedisDedupAdapter

        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        logger.info("EventPipeline using Redis dedup")
        return RedisDedupAdapter(
            redis_client,
            ttl_seconds=settings.polling.dedup_ttl_seconds,
        )
    except Exception as exc:
        # ADR-060: Never fall back to in-memory dedup in production --
        # dedup state is lost on restart, causing duplicate workflow executions.
        raise RuntimeError(
            "No durable dedup backend available (Postgres and Redis both failed). "
            "Configure SYN_OBSERVABILITY_DB_URL or REDIS_URL for production. "
            "See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md)."
        ) from exc


_import_ledger_singleton: ImportLedgerPort | None = None


def _create_import_ledger() -> ImportLedgerPort:
    """Return the process-wide delegate import ledger (#933, #936).

    A singleton because `get_execution_processor()` builds a NEW processor per
    dispatch. A fresh Postgres adapter each time would re-issue CREATE TABLE on
    every execution, and a fresh in-memory one would forget the mark between
    phases of a single execution - which is precisely the cross-phase recount
    #936 is about, reintroduced by the wiring rather than the logic.

    Postgres or nothing. Unlike dedup there is no Redis tier: the mark says how
    much of a session has already been CHARGED, and it has to stay consistent
    with the cost rows in `agent_events`. A ledger in a different store can
    disagree with the spend it describes, and nothing in the system would
    report the disagreement - it would just quietly bill wrong.

    ADR-060: never fall back to in-memory in production. Losing the mark on
    restart silently reverts to double-billing delegates (#936), which is the
    overcount failure mode that nobody reports because it just looks expensive.
    """
    global _import_ledger_singleton
    if _import_ledger_singleton is not None:
        return _import_ledger_singleton

    from syn_shared.settings import get_settings

    settings = get_settings()

    if settings.uses_in_memory_stores:
        from syn_adapters.import_ledger import InMemoryImportLedger

        _import_ledger_singleton = InMemoryImportLedger()
        return _import_ledger_singleton

    if settings.syn_observability_db_url:
        from syn_api._wiring_db import get_shared_db_pool

        pool = get_shared_db_pool()
        if pool is not None:
            from syn_adapters.import_ledger import PostgresImportLedger

            logger.info("Delegate import ledger using Postgres (ADR-060)")
            _import_ledger_singleton = PostgresImportLedger(pool)  # type: ignore[arg-type]  # asyncpg.Pool vs AsyncConnectionPool
            return _import_ledger_singleton

    raise RuntimeError(
        "No durable delegate import ledger available. Configure "
        "SYN_OBSERVABILITY_DB_URL for production. Without it, delegate cost is "
        "double-billed across phases (#936) and across a crash (#933). "
        "See ADR-060 (docs/adrs/ADR-060-restart-safe-trigger-deduplication.md)."
    )


def get_webhook_health_tracker() -> WebhookHealthTracker:
    """Return the singleton WebhookHealthTracker."""
    from syn_domain.contexts.github.services import WebhookHealthTracker

    global _webhook_health_tracker_singleton
    if _webhook_health_tracker_singleton is not None:
        assert isinstance(_webhook_health_tracker_singleton, WebhookHealthTracker)
        return _webhook_health_tracker_singleton

    from syn_shared.settings import get_settings

    settings = get_settings()
    threshold = settings.polling.webhook_stale_threshold_seconds
    tracker = WebhookHealthTracker(stale_threshold=threshold)
    _webhook_health_tracker_singleton = tracker
    return tracker


# ---------------------------------------------------------------------------
# Pending SHA store (poll-based self-healing, #602)
# ---------------------------------------------------------------------------

_pending_sha_store_singleton: object | None = None


def get_pending_sha_store() -> PendingSHAStore:
    """Return the singleton PendingSHAStore for check-run polling.

    ADR-060: production requires a durable backend. Never silently
    falls back to in-memory -- raises RuntimeError instead.
    """
    global _pending_sha_store_singleton
    if _pending_sha_store_singleton is not None:
        return _pending_sha_store_singleton  # type: ignore[return-value]

    from syn_shared.settings import get_settings

    settings = get_settings()

    # Test/offline: use in-memory (guarded by InMemoryAdapter base class)
    if settings.uses_in_memory_stores:
        from syn_adapters.github.pending_sha_store import InMemoryPendingSHAStore

        mem_store: PendingSHAStore = InMemoryPendingSHAStore()
        _pending_sha_store_singleton = mem_store
        return mem_store

    # Production: Postgres required (ADR-060)
    if settings.syn_observability_db_url:
        try:
            from syn_api._wiring_db import get_shared_db_pool

            pool = get_shared_db_pool()
            if pool is not None:
                from syn_adapters.github.postgres_pending_sha_store import (
                    PostgresPendingSHAStore,
                )

                store: PendingSHAStore = PostgresPendingSHAStore(pool)  # type: ignore[arg-type]  # asyncpg.Pool vs AsyncConnectionPool
                _pending_sha_store_singleton = store
                logger.info("PendingSHAStore using Postgres (restart-durable)")
                return store
        except Exception:
            logger.warning(
                "Postgres PendingSHAStore unavailable",
                exc_info=True,
            )

    # ADR-060: NEVER silent fallback to in-memory in production
    msg = (
        "No durable PendingSHAStore backend available. "
        "Configure SYN_OBSERVABILITY_DB_URL for production use."
    )
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Phase 3 additions - execution control, events, conversations, etc.
# ---------------------------------------------------------------------------


_controller_singleton: ExecutionController | None = None


def get_controller() -> ExecutionController:
    """Return a singleton ExecutionController for pause/resume/cancel/inject.

    Returns the same instance on every call so the execution engine and API
    endpoints share the same signal queue; signals enqueued by an HTTP
    endpoint are visible to the engine polling in the same process.

    Uses a Redis-backed signal queue (REDIS_URL env var, defaults to
    redis://localhost:6379/0). Falls back to _NullSignalQueueAdapter only
    if Redis is explicitly unavailable (no URL and no connection possible).

    Wraps: ExecutionController(ProjectionControlStateAdapter, signal_adapter)
    """
    global _controller_singleton
    if _controller_singleton is not None:
        return _controller_singleton

    from syn_adapters.control import ExecutionController
    from syn_adapters.control.adapters.projection import ProjectionControlStateAdapter
    from syn_adapters.projection_stores import get_projection_store

    state_adapter = ProjectionControlStateAdapter(get_projection_store())

    from syn_shared.settings import get_settings

    redis_url = get_settings().redis_url
    try:
        import redis.asyncio as aioredis

        from syn_adapters.control.adapters.redis_adapter import RedisSignalQueueAdapter

        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        signal_adapter: SignalQueuePort = RedisSignalQueueAdapter(redis_client)
        logger.info("ExecutionController using Redis signal queue (%s)", redis_url)
    except Exception:
        logger.warning(
            "Redis unavailable (%s); control signals (pause/cancel/resume) will not work",
            redis_url,
            exc_info=True,
        )
        signal_adapter = _NullSignalQueueAdapter()

    _controller_singleton = ExecutionController(
        state_port=state_adapter,
        signal_port=signal_adapter,
    )
    return _controller_singleton


logger = logging.getLogger(__name__)


class BackgroundWorkflowDispatcher:
    """Bridges WorkflowDispatchProjection → ExecuteWorkflowHandler.

    - run_workflow() → handler.handle() bridge
    - Fire-and-forget via asyncio.Task (never blocks projection loop)
    - Tracks tasks for graceful shutdown
    - Semaphore-bounded concurrency (Phase A2)
    """

    def __init__(self, handler: ExecuteWorkflowHandler, max_concurrent: int = 1) -> None:
        """`max_concurrent` defaults to 1 for the same reason the setting does.

        A caller that omits it used to get 5, which quietly reintroduced the
        unsafe value the setting exists to avoid (#865). The safe value has to
        be the one you get by saying nothing.
        """
        self._handler = handler
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def run_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str = "",
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
    ) -> None:
        # SYNCHRONOUS refusal, before the task exists (#1039). Everything after
        # this line is fire-and-forget: `WorkflowDispatchProjection` awaits
        # this method and then writes `status="dispatched"`, so anything that
        # fails inside the task leaves a trigger record claiming a run that has
        # no execution stream and never will. Raising HERE reaches the
        # projection's `dispatch_exception` path, which marks the record
        # `failed` - the state that is actually true.
        await self._handler.validate_stored_declarations(workflow_id)

        asyncio_task = asyncio.create_task(
            self._run_with_semaphore(workflow_id, inputs, execution_id, task=task, repos=repos),
            name=f"workflow-exec-{execution_id or workflow_id}",
        )
        self._tasks.add(asyncio_task)
        asyncio_task.add_done_callback(self._tasks.discard)

    async def _run_with_semaphore(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
    ) -> None:
        async with self._semaphore:
            await self._run(workflow_id, inputs, execution_id, task=task, repos=repos)

    async def _run(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
        repos: list[RepositoryRef] | None = None,
    ) -> None:
        from syn_domain.contexts.orchestration import (
            DuplicateExecutionError,
            ExecuteWorkflowCommand,
        )

        try:
            cmd = ExecuteWorkflowCommand(
                aggregate_id=workflow_id,
                inputs=inputs or {},
                repos=repos or [],
                execution_id=execution_id or None,
                task=task,
            )
            await self._handler.handle(cmd)
        except DuplicateExecutionError:
            logger.info(
                "Duplicate dispatch for execution %s, already running",
                execution_id,
            )
        except Exception:
            logger.exception(
                "Background workflow execution raised exception",
                extra={"workflow_id": workflow_id, "execution_id": execution_id},
            )

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


async def get_execute_workflow_handler() -> ExecuteWorkflowHandler:
    """Single composition root for ExecuteWorkflowHandler.

    Both the synchronous POST /workflows/{id}/execute route and the
    background dispatcher path go through this. Keeping the construction
    in one place prevents drift like #726's missed phase_plugin_resolver
    wiring, where one path materialized claude plugins into workspaces and
    the other silently skipped them.

    WHY (issue #726): bind the resolution service's per-phase resolver so
    ``ExecuteWorkflowHandler`` populates ``ExecutablePhase.claude_plugins``
    with lock-resolved entries before dispatch reaches the processor.

    WHY (issue #772): mirrors the claude plugin wiring for skills -- binds
    ``SkillResolutionService.resolve_for_phase`` so
    ``ExecutablePhase.skills`` is populated the same way.
    """
    from syn_domain.contexts.orchestration import ExecuteWorkflowHandler

    processor = await get_execution_processor()
    resolution_service = await get_claude_plugin_resolution_service()
    skill_resolution_service = await get_skill_resolution_service()
    return ExecuteWorkflowHandler(
        processor=processor,
        workflow_repository=get_workflow_repository(),
        phase_plugin_resolver=resolution_service.resolve_for_phase,
        phase_skill_resolver=skill_resolution_service.resolve_for_phase,
    )


async def get_workflow_dispatcher() -> BackgroundWorkflowDispatcher:
    """Create a BackgroundWorkflowDispatcher backed by the processor."""
    handler = await get_execute_workflow_handler()
    from syn_shared.settings import get_settings

    max_concurrent = get_settings().polling.max_concurrent_dispatches
    return BackgroundWorkflowDispatcher(handler, max_concurrent=max_concurrent)


class _NullSignalQueueAdapter:
    """No-op signal adapter when Redis is not available."""

    async def enqueue(self, execution_id: str, signal: ControlSignal) -> None:
        pass

    async def dequeue(self, execution_id: str) -> ControlSignal | None:  # noqa: ARG002
        return None

    async def get_signal(self, execution_id: str) -> ControlSignal | None:  # noqa: ARG002
        return None


def get_event_store_instance() -> AgentEventStore:
    """Return the AgentEventStore for TimescaleDB queries."""
    return get_event_store()


def get_session_cost_query():
    """Return a SessionCostQueryService backed by TimescaleDB.

    Read-only service for session cost data; separates reads from
    the write-side projection. See #532.

    Raises:
        RuntimeError: If the TimescaleDB pool is not yet initialized.
    """
    from syn_domain.contexts.agent_sessions import SessionCostQueryService

    pool = get_event_store_instance().pool
    if pool is None:
        raise RuntimeError(
            "TimescaleDB pool is not initialized; ensure_connected() must be called first"
        )
    return SessionCostQueryService(pool=pool)


def get_execution_cost_query():
    """Return an ExecutionCostQueryService backed by TimescaleDB.

    Read-only service for execution cost data; separates reads from
    the write-side projection. See #532.

    Raises:
        RuntimeError: If the TimescaleDB pool is not yet initialized.
    """
    from syn_domain.contexts.orchestration import ExecutionCostQueryService

    pool = get_event_store_instance().pool
    if pool is None:
        raise RuntimeError(
            "TimescaleDB pool is not initialized; ensure_connected() must be called first"
        )
    return ExecutionCostQueryService(pool=pool)


def get_canonical_usage_query():
    """Return a CanonicalUsageQueryService backed by TimescaleDB.

    The ONE source the dashboard's totals read, so the metric card and the
    activity heatmap cannot drift apart again (#932).

    Raises:
        RuntimeError: If the TimescaleDB pool is not yet initialized.
    """
    from syn_domain.contexts.agent_sessions import CanonicalUsageQueryService, CostCalculator

    pool = get_event_store_instance().pool
    if pool is None:
        raise RuntimeError(
            "TimescaleDB pool is not initialized; ensure_connected() must be called first"
        )
    return CanonicalUsageQueryService(pool=pool, cost_calculator=CostCalculator())


async def get_conversation_store() -> MinioConversationStorage:
    """Return the conversation storage (MinIO-backed)."""
    return await get_conversation_storage()


def get_realtime() -> RealTimeProjection:
    """Return the RealTimeProjection singleton."""
    from syn_adapters.projections.realtime import get_realtime_projection

    return get_realtime_projection()


def _get_budget_checker() -> _BudgetChecker | None:
    """Return the SpendTracker as a budget checker, or None if unavailable."""
    try:
        from syn_tokens.singletons import get_spend_tracker

        return get_spend_tracker()
    except Exception:
        logger.warning("SpendTracker unavailable, dispatch budget checks disabled")
        return None


def get_subscription_coordinator(
    realtime_projection: RealTimeProjection | None = None,
    execution_service: _ExecutionService | None = None,
) -> CoordinatorSubscriptionService:
    """Create the CoordinatorSubscriptionService.

    Wraps: create_coordinator_service(event_store, projection_store, ...)
    """
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.subscriptions import create_coordinator_service
    from syn_shared.settings import get_settings

    # Pass TimescaleDB pool to cost projections (#505, #507)
    timescale_pool = None
    with contextlib.suppress(Exception):
        timescale_pool = get_event_store_instance().pool

    settings = get_settings()

    return create_coordinator_service(
        event_store=get_event_store_client(),
        projection_store=get_projection_store(),
        realtime_projection=realtime_projection,
        execution_service=execution_service,
        pool=timescale_pool,
        budget_checker=_get_budget_checker(),
        max_dispatches_per_hour=settings.polling.max_dispatches_per_hour,
    )


def get_github_settings() -> GitHubAppSettings:
    """Return the GitHubAppSettings instance."""
    from syn_shared.settings.github import get_github_settings as _get

    return _get()


# ---------------------------------------------------------------------------
# Claude plugin injection (issue #726)
#
# See ADR-066: the API tier holds storage + repository wiring only. After the
# Phase A redesign there is no fetcher in the API container -- the CLI clones
# locally and uploads the tree contents inline. Production storage is MinIO;
# tests/offline (``settings.uses_in_memory_stores``) use the in-memory adapter
# guarded by ``InMemoryAdapter``.
#
# Why singletons: the lock + global projections are coordinator-owned read
# models with internal store handles; instantiating fresh per request would
# leak handles. The handlers themselves are cheap to build but follow the
# same singleton pattern as other slices for consistency.
# ---------------------------------------------------------------------------


# WHY each singleton is typed with the concrete handler/projection class:
# the wiring layer is the trust boundary that builds these collaborators, so
# downstream callers (route handlers, services) get precise types and never
# need ``# type: ignore`` at use sites. See feedback_no_any_in_plumbing.
_claude_plugin_storage_singleton: MinioClaudePluginStorage | InMemoryClaudePluginStorage | None = (
    None
)
_register_claude_plugin_handler_singleton: RegisterClaudePluginHandler | None = None
_add_global_claude_plugin_handler_singleton: AddGlobalClaudePluginHandler | None = None
_remove_global_claude_plugin_handler_singleton: RemoveGlobalClaudePluginHandler | None = None
_list_global_claude_plugins_handler_singleton: ListGlobalClaudePluginsHandler | None = None
_list_claude_plugins_handler_singleton: ListClaudePluginsHandler | None = None
_show_claude_plugin_handler_singleton: ShowClaudePluginHandler | None = None
_claude_plugin_resolution_service_singleton: ClaudePluginResolutionService | None = None
_claude_plugin_materializer_singleton: ClaudePluginMaterializer | None = None


def _claude_plugin_registration_repository() -> RepositoryAdapter[
    ClaudePluginRegistrationAggregate
]:
    """Repository for ``ClaudePluginRegistrationAggregate``.

    Always returns the durable ``RepositoryAdapter``; in test/offline mode the
    underlying ESP client is the in-memory MemoryEventStoreClient, so the
    adapter still publishes events through the InMemoryEventPublisher and
    ``sync_published_events_to_projections()`` can dispatch them to the
    lock projection. The Phase 5 slice unit tests still use the bare
    ``InMemoryClaudePluginRegistrationRepository`` directly (no event-store
    plumbing needed there).
    """
    from syn_adapters.storage.repositories import (
        get_claude_plugin_registration_repository as _durable,
    )

    return _durable()


def _global_claude_plugin_registry_repository() -> RepositoryAdapter[
    GlobalClaudePluginRegistryAggregate
]:
    """Repository for ``GlobalClaudePluginRegistryAggregate`` (singleton aggregate)."""
    from syn_adapters.storage.repositories import (
        get_global_claude_plugin_registry_repository as _durable,
    )

    return _durable()


async def get_claude_plugin_storage() -> MinioClaudePluginStorage | InMemoryClaudePluginStorage:
    """Return the claude plugin tree storage adapter (MinIO in prod, in-memory in tests)."""
    global _claude_plugin_storage_singleton
    if _claude_plugin_storage_singleton is not None:
        return _claude_plugin_storage_singleton

    from syn_shared.settings import get_settings

    if get_settings().uses_in_memory_stores:
        from syn_adapters.storage.claude_plugin_storage.factory import (
            get_test_claude_plugin_storage,
        )

        _claude_plugin_storage_singleton = get_test_claude_plugin_storage()
        return _claude_plugin_storage_singleton

    from syn_adapters.storage.claude_plugin_storage.factory import (
        get_claude_plugin_storage as _prod,
    )

    _claude_plugin_storage_singleton = await _prod()
    return _claude_plugin_storage_singleton


def get_claude_plugin_lock_projection() -> ClaudePluginLockProjection:
    """Return the claude_plugin_lock projection from the shared registry.

    Critical: route reads + sync_published_events_to_projections writes MUST
    use the same projection instance, otherwise events written by the manager
    are invisible to the route. The projection registry is the single owner.
    """
    from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
        ClaudePluginLockProjection,
    )

    projection = get_projection_manager().get_projection("claude_plugin_lock")
    # WHY assert: ProjectionManager.get_projection returns Any for heterogeneity;
    # narrow it once at the wiring boundary so callers see the precise type.
    assert isinstance(projection, ClaudePluginLockProjection)
    return projection


def get_global_claude_plugins_projection() -> GlobalClaudePluginsProjection:
    """Return the global_claude_plugins projection from the shared registry."""
    from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins.projection import (
        GlobalClaudePluginsProjection,
    )

    projection = get_projection_manager().get_projection("global_claude_plugins")
    assert isinstance(projection, GlobalClaudePluginsProjection)
    return projection


async def get_register_claude_plugin_handler() -> RegisterClaudePluginHandler:
    """Return the ``RegisterClaudePluginHandler`` composed from storage + repo.

    No fetcher dependency after the #726 Phase A redesign; the CLI uploads the
    pre-cloned tree contents inline.
    """
    global _register_claude_plugin_handler_singleton
    if _register_claude_plugin_handler_singleton is not None:
        return _register_claude_plugin_handler_singleton

    from syn_domain.contexts.orchestration.slices.register_claude_plugin import (
        RegisterClaudePluginHandler,
    )

    _register_claude_plugin_handler_singleton = RegisterClaudePluginHandler(
        storage=await get_claude_plugin_storage(),
        repo=_claude_plugin_registration_repository(),
    )
    return _register_claude_plugin_handler_singleton


async def get_add_global_claude_plugin_handler() -> AddGlobalClaudePluginHandler:
    """Return the ``AddGlobalClaudePluginHandler``.

    Phase A redesign: depends on the lock projection rather than the register
    handler. Refuses to add anything that has not been registered first.
    """
    global _add_global_claude_plugin_handler_singleton
    if _add_global_claude_plugin_handler_singleton is not None:
        return _add_global_claude_plugin_handler_singleton

    from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins import (
        AddGlobalClaudePluginHandler,
    )

    _add_global_claude_plugin_handler_singleton = AddGlobalClaudePluginHandler(
        repo=_global_claude_plugin_registry_repository(),
        lock_projection=get_claude_plugin_lock_projection(),
    )
    return _add_global_claude_plugin_handler_singleton


def get_remove_global_claude_plugin_handler() -> RemoveGlobalClaudePluginHandler:
    """Return the ``RemoveGlobalClaudePluginHandler``."""
    global _remove_global_claude_plugin_handler_singleton
    if _remove_global_claude_plugin_handler_singleton is not None:
        return _remove_global_claude_plugin_handler_singleton

    from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins import (
        RemoveGlobalClaudePluginHandler,
    )

    _remove_global_claude_plugin_handler_singleton = RemoveGlobalClaudePluginHandler(
        repo=_global_claude_plugin_registry_repository(),
    )
    return _remove_global_claude_plugin_handler_singleton


def get_list_global_claude_plugins_handler() -> ListGlobalClaudePluginsHandler:
    """Return the ``ListGlobalClaudePluginsHandler``."""
    global _list_global_claude_plugins_handler_singleton
    if _list_global_claude_plugins_handler_singleton is not None:
        return _list_global_claude_plugins_handler_singleton

    from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins import (
        ListGlobalClaudePluginsHandler,
    )

    _list_global_claude_plugins_handler_singleton = ListGlobalClaudePluginsHandler(
        projection=get_global_claude_plugins_projection(),
    )
    return _list_global_claude_plugins_handler_singleton


def get_list_claude_plugins_handler() -> ListClaudePluginsHandler:
    """Return the ``ListClaudePluginsHandler`` (lock projection scan)."""
    global _list_claude_plugins_handler_singleton
    if _list_claude_plugins_handler_singleton is not None:
        return _list_claude_plugins_handler_singleton

    from syn_domain.contexts.orchestration.slices.list_claude_plugins import (
        ListClaudePluginsHandler,
    )

    _list_claude_plugins_handler_singleton = ListClaudePluginsHandler(
        projection=get_claude_plugin_lock_projection(),
    )
    return _list_claude_plugins_handler_singleton


def get_show_claude_plugin_handler() -> ShowClaudePluginHandler:
    """Return the ``ShowClaudePluginHandler`` (lock projection by name+version)."""
    global _show_claude_plugin_handler_singleton
    if _show_claude_plugin_handler_singleton is not None:
        return _show_claude_plugin_handler_singleton

    from syn_domain.contexts.orchestration.slices.show_claude_plugin import (
        ShowClaudePluginHandler,
    )

    _show_claude_plugin_handler_singleton = ShowClaudePluginHandler(
        projection=get_claude_plugin_lock_projection(),
    )
    return _show_claude_plugin_handler_singleton


async def get_claude_plugin_resolution_service() -> ClaudePluginResolutionService:
    """Return the ``ClaudePluginResolutionService`` used by the workflow install path.

    Phase A redesign: validate-only; no register handler dependency.
    """
    global _claude_plugin_resolution_service_singleton
    if _claude_plugin_resolution_service_singleton is not None:
        return _claude_plugin_resolution_service_singleton

    from syn_api.services.claude_plugin_resolution_service import (
        ClaudePluginResolutionService,
    )

    _claude_plugin_resolution_service_singleton = ClaudePluginResolutionService(
        lock_projection=get_claude_plugin_lock_projection(),
        global_projection=get_global_claude_plugins_projection(),
    )
    return _claude_plugin_resolution_service_singleton


async def get_claude_plugin_materializer() -> ClaudePluginMaterializer:
    """Return the process-wide ``ClaudePluginMaterializer`` (issue #726, PR2).

    Construction is async because the storage singleton is async; the
    materializer itself is stateless apart from its LRU cache.
    """
    global _claude_plugin_materializer_singleton
    if _claude_plugin_materializer_singleton is not None:
        return _claude_plugin_materializer_singleton

    from syn_api.services.claude_plugin_materializer import ClaudePluginMaterializer

    storage = await get_claude_plugin_storage()
    _claude_plugin_materializer_singleton = ClaudePluginMaterializer(storage=storage)
    return _claude_plugin_materializer_singleton


def reset_claude_plugin_singletons() -> None:
    """Reset every claude-plugin singleton (test isolation only)."""
    global _claude_plugin_storage_singleton
    global _register_claude_plugin_handler_singleton
    global _add_global_claude_plugin_handler_singleton
    global _remove_global_claude_plugin_handler_singleton
    global _list_global_claude_plugins_handler_singleton
    global _list_claude_plugins_handler_singleton
    global _show_claude_plugin_handler_singleton
    global _claude_plugin_resolution_service_singleton
    global _claude_plugin_materializer_singleton

    _claude_plugin_storage_singleton = None
    _register_claude_plugin_handler_singleton = None
    _add_global_claude_plugin_handler_singleton = None
    _remove_global_claude_plugin_handler_singleton = None
    _list_global_claude_plugins_handler_singleton = None
    _list_claude_plugins_handler_singleton = None
    _show_claude_plugin_handler_singleton = None
    _claude_plugin_resolution_service_singleton = None
    _claude_plugin_materializer_singleton = None


# ── Skill wiring (issue #772) ───────────────────────────────────────
#
# Mirrors the claude-plugin wiring block above. Skills have no global scope
# in this plan, so there is no global-registry projection/handler here.

_skill_storage_singleton: MinioSkillStorage | InMemorySkillStorage | None = None
_register_skill_handler_singleton: RegisterSkillHandler | None = None
_skill_resolution_service_singleton: SkillResolutionService | None = None
_skill_materializer_singleton: SkillMaterializer | None = None


async def get_skill_storage() -> MinioSkillStorage | InMemorySkillStorage:
    """Get the configured skill storage adapter (production singleton)."""
    global _skill_storage_singleton
    if _skill_storage_singleton is not None:
        return _skill_storage_singleton

    from syn_shared.settings import get_settings

    if get_settings().uses_in_memory_stores:
        from syn_adapters.storage.skill_storage.factory import get_test_skill_storage

        _skill_storage_singleton = get_test_skill_storage()
        return _skill_storage_singleton

    from syn_adapters.storage.skill_storage.factory import get_skill_storage as _prod

    _skill_storage_singleton = await _prod()
    return _skill_storage_singleton


def get_skill_lock_projection() -> SkillLockProjection:
    """Return the skill_lock projection from the shared registry.

    WHY assert isinstance: the projection manager stores projections keyed by
    name as ``CheckpointedProjection``; the concrete type is only known at
    this call site, so an isinstance check keeps every downstream caller
    fully typed without ``# type: ignore`` (see feedback_no_any_in_plumbing).
    """
    from syn_domain.contexts.orchestration.slices.register_skill.projection import (
        SkillLockProjection,
    )

    projection = get_projection_manager().get_projection("skill_lock")
    assert isinstance(projection, SkillLockProjection)
    return projection


async def get_register_skill_handler() -> RegisterSkillHandler:
    """Return the process-wide ``RegisterSkillHandler`` singleton (issue #772)."""
    global _register_skill_handler_singleton
    if _register_skill_handler_singleton is not None:
        return _register_skill_handler_singleton

    from syn_adapters.storage.repositories import get_skill_registration_repository
    from syn_domain.contexts.orchestration.slices.register_skill import RegisterSkillHandler

    _register_skill_handler_singleton = RegisterSkillHandler(
        storage=await get_skill_storage(),
        repo=get_skill_registration_repository(),
    )
    return _register_skill_handler_singleton


async def get_skill_resolution_service() -> SkillResolutionService:
    """Return the process-wide ``SkillResolutionService`` singleton (issue #772)."""
    global _skill_resolution_service_singleton
    if _skill_resolution_service_singleton is not None:
        return _skill_resolution_service_singleton

    from syn_api.services.skill_resolution_service import SkillResolutionService

    _skill_resolution_service_singleton = SkillResolutionService(
        lock_projection=get_skill_lock_projection(),
    )
    return _skill_resolution_service_singleton


async def get_skill_materializer() -> SkillMaterializer:
    """Return the process-wide ``SkillMaterializer`` (issue #772).

    Mirrors ``get_claude_plugin_materializer``: construction is async because
    the storage singleton is async; the materializer itself is stateless
    apart from its LRU cache.
    """
    global _skill_materializer_singleton
    if _skill_materializer_singleton is not None:
        return _skill_materializer_singleton

    from syn_api.services.skill_materializer import SkillMaterializer

    storage = await get_skill_storage()
    _skill_materializer_singleton = SkillMaterializer(storage=storage)
    return _skill_materializer_singleton


def reset_skill_singletons() -> None:
    """Reset every skill singleton (test isolation only)."""
    global _skill_storage_singleton
    global _register_skill_handler_singleton
    global _skill_resolution_service_singleton
    global _skill_materializer_singleton

    _skill_storage_singleton = None
    _register_skill_handler_singleton = None
    _skill_resolution_service_singleton = None
    _skill_materializer_singleton = None
