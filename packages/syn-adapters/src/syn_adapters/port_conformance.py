"""Every port, and the thing that actually implements it (#1305).

A ``Protocol`` nothing checks is documentation that can lie. Structural
matching is only performed where a value of the concrete type MEETS an
annotation of the port type, and until this module existed several ports had
no such site anywhere: ``WorkflowExecutionRepositoryPort`` had drifted from
``RepositoryAdapter`` over a parameter NAME, and a full pyright run was green.

This module is that site, once, for all of them. Each line below reads as a
claim - "this implementation satisfies this port" - and pyright is what makes
the claim cost something: rename or remove a method on an adapter, change a
parameter name, widen a return type, and the pairing goes red under
``just typecheck``. That is the whole mechanism; there is no runtime part and
nothing here is called.

Nothing executes. The imports are ``TYPE_CHECKING``-only and the bodies are
never invoked, so a module that names every adapter in the system costs no
import time and can introduce no cycle.

``ci/fitness/code_quality/test_port_conformance.py`` is what keeps this list
honest: it discovers every ``Protocol`` whose name ends in ``Port`` and fails
when one appears neither here nor in its table of ports with no implementation
in this repository. A new port cannot arrive unpaired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.control.adapters.memory import (
        InMemoryControlStateAdapter,
        InMemorySignalQueueAdapter,
    )
    from syn_adapters.control.adapters.projection import ProjectionControlStateAdapter
    from syn_adapters.control.adapters.redis_adapter import RedisSignalQueueAdapter
    from syn_adapters.control.ports import ControlStatePort, SignalQueuePort
    from syn_adapters.conversations.minio import MinioConversationStorage
    from syn_adapters.conversations.protocol import (
        ConversationStoragePort as AdapterConversationStoragePort,
    )
    from syn_adapters.dedup.memory_dedup import InMemoryDedupAdapter
    from syn_adapters.dedup.postgres_dedup import PostgresDedupAdapter
    from syn_adapters.dedup.redis_dedup import RedisDedupAdapter
    from syn_adapters.events.store import AgentEventStore
    from syn_adapters.github.checks_api_client import GitHubChecksAPIClient
    from syn_adapters.github.events_api_client import GitHubEventsAPIClient
    from syn_adapters.github.pending_sha_store import InMemoryPendingSHAStore
    from syn_adapters.github.postgres_pending_sha_store import PostgresPendingSHAStore
    from syn_adapters.maintenance import (
        InMemoryMaintenanceAdapter,
        PostgresMaintenanceAdapter,
        RedisMaintenanceAdapter,
    )
    from syn_adapters.session_store.http_store import HttpSessionStore
    from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage
    from syn_adapters.storage.claude_plugin_storage.minio import MinioClaudePluginStorage
    from syn_adapters.storage.repositories import (
        get_artifact_repository,
        get_claude_plugin_registration_repository,
        get_global_claude_plugin_registry_repository,
        get_session_repository,
        get_skill_registration_repository,
        get_workflow_execution_repository,
        get_workflow_repository,
    )
    from syn_adapters.storage.skill_storage.minio import MinioSkillStorage
    from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
        SessionCaptureService,
    )
    from syn_adapters.workspace_backends.agentic.stream_adapter import (
        AgenticEventStreamAdapter,
    )
    from syn_adapters.workspace_backends.docker.docker_sidecar_adapter import (
        DockerSidecarAdapter,
    )
    from syn_adapters.workspace_backends.memory.memory_adapter import (
        MemoryIsolationAdapter,
    )
    from syn_adapters.workspace_backends.memory.memory_artifact import (
        MemoryArtifactAdapter,
    )
    from syn_adapters.workspace_backends.memory.memory_sidecar import (
        MemorySidecarAdapter,
    )
    from syn_adapters.workspace_backends.memory.memory_stream import (
        MemoryEventStreamAdapter,
    )
    from syn_adapters.workspace_backends.memory.memory_token import (
        MemoryTokenInjectionAdapter,
    )
    from syn_adapters.workspace_backends.recording.adapter import (
        RecordingEventStreamAdapter,
    )
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceService
    from syn_adapters.workspace_backends.tokens.token_injection_adapter import (
        DirectTokenInjectionAdapter,
    )
    from syn_adapters.workspace_backends.tokens.token_vending_adapter import (
        TokenVendingServiceAdapter,
    )
    from syn_domain.contexts._shared.maintenance import MaintenancePort
    from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort
    from syn_domain.contexts.agent_sessions.import_ledger import ImportLedgerPort
    from syn_domain.contexts.agent_sessions.ports.SessionObservationPort import (
        SessionObservationPort,
    )
    from syn_domain.contexts.artifacts.domain.services import ArtifactQueryService
    from syn_domain.contexts.artifacts.ports.ArtifactContentStoragePort import (
        ArtifactContentStoragePort as ArtifactsArtifactContentStoragePort,
    )
    from syn_domain.contexts.github.ports.ChecksApiPort import GitHubChecksAPIPort
    from syn_domain.contexts.github.ports.EventsApiPort import GitHubEventsAPIPort
    from syn_domain.contexts.github.slices.event_pipeline.dedup_port import DedupPort
    from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import (
        PendingSHAStore,
    )
    from syn_domain.contexts.orchestration._shared.ports import (
        ArtifactCollectionPort,
        EventStreamPort,
        IsolationBackendPort,
        SidecarPort,
        TokenInjectionPort,
        TokenVendingPort,
    )
    from syn_domain.contexts.orchestration.ports.ArtifactQueryServicePort import (
        ArtifactQueryServicePort,
    )
    from syn_domain.contexts.orchestration.ports.ArtifactRepositoryPort import (
        ArtifactRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.ClaudePluginRegistrationRepositoryPort import (
        ClaudePluginRegistrationRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
        ClaudePluginStoragePort,
    )
    from syn_domain.contexts.orchestration.ports.CodexRolloutPort import CodexRolloutPort
    from syn_domain.contexts.orchestration.ports.GlobalClaudePluginRegistryRepositoryPort import (
        GlobalClaudePluginRegistryRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.ObservabilityServicePort import (
        ObservabilityServicePort,
    )
    from syn_domain.contexts.orchestration.ports.SessionRepositoryPort import (
        SessionRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.SkillRegistrationRepositoryPort import (
        SkillRegistrationRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.SkillStoragePort import SkillStoragePort
    from syn_domain.contexts.orchestration.ports.WorkflowExecutionRepositoryPort import (
        WorkflowExecutionRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.WorkflowTemplateRepositoryPort import (
        WorkflowTemplateRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.WorkspaceServicePort import (
        WorkspaceServicePort,
    )

    def _event_sourced_repositories() -> None:
        """What each repository factory hands out satisfies its port.

        Calling the factory rather than naming ``RepositoryAdapter`` directly
        checks the whole chain: not "this class could satisfy the port" but
        "what production wiring returns for this aggregate does".
        """
        _artifact: ArtifactRepositoryPort = get_artifact_repository()
        _claude_plugin: ClaudePluginRegistrationRepositoryPort = (
            get_claude_plugin_registration_repository()
        )
        _plugin_registry: GlobalClaudePluginRegistryRepositoryPort = (
            get_global_claude_plugin_registry_repository()
        )
        _session: SessionRepositoryPort = get_session_repository()
        _skill: SkillRegistrationRepositoryPort = get_skill_registration_repository()
        _execution: WorkflowExecutionRepositoryPort = get_workflow_execution_repository()
        _template: WorkflowTemplateRepositoryPort = get_workflow_repository()

    def _object_storage(
        artifacts: MinioArtifactStorage,
        conversations: MinioConversationStorage,
        plugins: MinioClaudePluginStorage,
        skills: MinioSkillStorage,
    ) -> None:
        """MinIO-backed storage against the ports the domain declares.

        Each of these has exactly one declaration now. The orchestration
        context used to declare its own ``ArtifactContentStoragePort`` and
        ``ConversationStoragePort``; both had drifted from MinIO and neither
        had a consumer, so both are deleted rather than repaired (#1305).
        """
        _artifacts: ArtifactsArtifactContentStoragePort = artifacts
        _conversations: AdapterConversationStoragePort = conversations
        _plugins: ClaudePluginStoragePort = plugins
        _skills: SkillStoragePort = skills

    def _workspace_backends(
        agentic_isolation: AgenticIsolationAdapter,
        memory_isolation: MemoryIsolationAdapter,
        docker_sidecar: DockerSidecarAdapter,
        memory_sidecar: MemorySidecarAdapter,
        agentic_stream: AgenticEventStreamAdapter,
        memory_stream: MemoryEventStreamAdapter,
        recording_stream: RecordingEventStreamAdapter,
        memory_artifacts: MemoryArtifactAdapter,
        vending: TokenVendingServiceAdapter,
        direct_injection: DirectTokenInjectionAdapter,
        memory_injection: MemoryTokenInjectionAdapter,
        workspace: ManagedWorkspace,
        service: WorkspaceService,
    ) -> None:
        """The backends ``WorkspaceService`` composes, and the facade itself.

        The in-memory backends are here for the same reason as the real ones:
        ``WorkspaceService.create_for_testing`` wires them through the same
        constructor, so a drift in one of them is a drift in a live code path.
        """
        _agentic_isolation: IsolationBackendPort = agentic_isolation
        _memory_isolation: IsolationBackendPort = memory_isolation
        _docker_sidecar: SidecarPort = docker_sidecar
        _memory_sidecar: SidecarPort = memory_sidecar
        _agentic_stream: EventStreamPort = agentic_stream
        _memory_stream: EventStreamPort = memory_stream
        _recording_stream: EventStreamPort = recording_stream
        _memory_artifacts: ArtifactCollectionPort = memory_artifacts
        _vending: TokenVendingPort = vending
        _direct_injection: TokenInjectionPort = direct_injection
        _memory_injection: TokenInjectionPort = memory_injection
        _rollout: CodexRolloutPort = workspace
        _service: WorkspaceServicePort = service

    def _observability(
        event_store: AgentEventStore,
        query: ArtifactQueryService,
        capture: SessionCaptureService,
        session_store: HttpSessionStore,
        observations: SessionObservationPort,
        ledger: ImportLedgerPort,
    ) -> None:
        """Telemetry and session-reading adapters.

        ``observations`` and ``ledger`` are already annotated with their port
        at the wiring site in ``syn_api._wiring``; they are restated here so
        this list is the complete answer to "what implements this port" rather
        than a list of the ones that happened to lack a call site.
        """
        _events: ObservabilityServicePort = event_store
        _query: ArtifactQueryServicePort = query
        _capture: SessionCapturePort = capture
        _sessions: SessionStorePort = session_store
        _observations: SessionObservationPort = observations
        _ledger: ImportLedgerPort = ledger

    def _github_and_control(
        events_client: GitHubEventsAPIClient,
        checks_client: GitHubChecksAPIClient,
        redis_dedup: RedisDedupAdapter,
        postgres_dedup: PostgresDedupAdapter,
        memory_dedup: InMemoryDedupAdapter,
        projection_state: ProjectionControlStateAdapter,
        memory_state: InMemoryControlStateAdapter,
        redis_signals: RedisSignalQueueAdapter,
        memory_signals: InMemorySignalQueueAdapter,
        postgres_pending: PostgresPendingSHAStore,
        memory_pending: InMemoryPendingSHAStore,
    ) -> None:
        """GitHub ingestion and execution control.

        The three dedup adapters are interchangeable at runtime - ``_wiring``
        picks one by what infrastructure is reachable - so all three must
        satisfy the port, not just whichever one happens to be reachable.
        """
        _events: GitHubEventsAPIPort = events_client
        _checks: GitHubChecksAPIPort = checks_client
        _redis_dedup: DedupPort = redis_dedup
        _postgres_dedup: DedupPort = postgres_dedup
        _memory_dedup: DedupPort = memory_dedup
        _projection_state: ControlStatePort = projection_state
        _memory_state: ControlStatePort = memory_state
        _redis_signals: SignalQueuePort = redis_signals
        _memory_signals: SignalQueuePort = memory_signals
        _postgres_pending: PendingSHAStore = postgres_pending
        _memory_pending: PendingSHAStore = memory_pending

    def _maintenance(
        postgres: PostgresMaintenanceAdapter,
        redis: RedisMaintenanceAdapter,
        memory: InMemoryMaintenanceAdapter,
    ) -> None:
        """Every durable fallback and the test double satisfy the shared gate."""
        _postgres: MaintenancePort = postgres
        _redis: MaintenancePort = redis
        _memory: MaintenancePort = memory
