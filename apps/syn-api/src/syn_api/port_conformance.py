"""Static proof that every declared port is satisfied by its implementation.

A ``Protocol`` nobody assigns to is documentation that can lie. Structural
matching only happens where a concrete object meets a port-typed name, so a
port with no annotated call site is never checked at all -- the port and its
only adapter drift apart and nothing goes red (#1305).

This module is that missing call site, once per port. Each entry names a port
and the implementation that has to satisfy it; pyright checks the ``return``.
Rename a parameter, drop a method or change a signature on either side and the
type check fails here, with the port and the implementation both named in the
error.

Nothing here runs. The declarations live under ``TYPE_CHECKING`` so importing
this module constructs nothing and touches no infrastructure; the assertions
are made entirely by the type checker. ``ci/fitness/event_sourcing/
test_port_conformance.py`` keeps the list complete, so a port added later
cannot repeat the omission that caused #1305.

Ports whose implementation lives outside this repository are listed in that
fitness test with the reason, not here -- there is nothing local to assign.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.conversations.minio import MinioConversationStorage
    from syn_adapters.github.checks_api_client import GitHubChecksAPIClient
    from syn_adapters.github.events_api_client import GitHubEventsAPIClient
    from syn_adapters.observability.agent_event_store import AgentEventStore
    from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage
    from syn_adapters.storage.claude_plugin_storage.minio import MinioClaudePluginStorage
    from syn_adapters.storage.repositories import RepositoryAdapter
    from syn_adapters.storage.skill_storage.minio import MinioSkillStorage
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceService
    from syn_domain.contexts.agent_sessions._shared import AgentSessionAggregate
    from syn_domain.contexts.agent_sessions.ports.SessionObservationPort import (
        SessionObservationPort,
    )
    from syn_domain.contexts.artifacts import ArtifactQueryService
    from syn_domain.contexts.artifacts._shared import ArtifactAggregate
    from syn_domain.contexts.artifacts.ports import (
        ArtifactContentStoragePort as ArtifactsContextContentStoragePort,
    )
    from syn_domain.contexts.github.ports import GitHubChecksAPIPort, GitHubEventsAPIPort
    from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
        ClaudePluginRegistrationAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_global_claude_plugin_registry.GlobalClaudePluginRegistryAggregate import (
        GlobalClaudePluginRegistryAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_skill_registration.SkillRegistrationAggregate import (
        SkillRegistrationAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.ports import (
        ArtifactContentStoragePort,
        ArtifactQueryServicePort,
        ArtifactRepositoryPort,
        ClaudePluginRegistrationRepositoryPort,
        ClaudePluginStoragePort,
        CodexRolloutPort,
        ConversationStoragePort,
        GlobalClaudePluginRegistryRepositoryPort,
        ObservabilityServicePort,
        SessionRepositoryPort,
        WorkflowExecutionRepositoryPort,
        WorkflowTemplateRepositoryPort,
        WorkspaceServicePort,
    )
    from syn_domain.contexts.orchestration.ports.SkillRegistrationRepositoryPort import (
        SkillRegistrationRepositoryPort,
    )
    from syn_domain.contexts.orchestration.ports.SkillStoragePort import SkillStoragePort

    # --- orchestration: repository ports -------------------------------------
    # All four wrap the same generic RepositoryAdapter, which is why a single
    # parameter-name drift on it unsatisfied four ports at once.

    def _workflow_execution_repository(
        impl: RepositoryAdapter[WorkflowExecutionAggregate],
    ) -> WorkflowExecutionRepositoryPort:
        return impl

    def _workflow_template_repository(
        impl: RepositoryAdapter[WorkflowTemplateAggregate],
    ) -> WorkflowTemplateRepositoryPort:
        return impl

    def _session_repository(
        impl: RepositoryAdapter[AgentSessionAggregate],
    ) -> SessionRepositoryPort:
        return impl

    def _artifact_repository(
        impl: RepositoryAdapter[ArtifactAggregate],
    ) -> ArtifactRepositoryPort:
        return impl

    def _claude_plugin_registration_repository(
        impl: RepositoryAdapter[ClaudePluginRegistrationAggregate],
    ) -> ClaudePluginRegistrationRepositoryPort:
        return impl

    def _global_claude_plugin_registry_repository(
        impl: RepositoryAdapter[GlobalClaudePluginRegistryAggregate],
    ) -> GlobalClaudePluginRegistryRepositoryPort:
        return impl

    def _skill_registration_repository(
        impl: RepositoryAdapter[SkillRegistrationAggregate],
    ) -> SkillRegistrationRepositoryPort:
        return impl

    # --- orchestration: service ports ----------------------------------------

    def _workspace_service(impl: WorkspaceService) -> WorkspaceServicePort:
        return impl

    def _artifact_query_service(impl: ArtifactQueryService) -> ArtifactQueryServicePort:
        return impl

    def _observability_service(impl: AgentEventStore) -> ObservabilityServicePort:
        return impl

    # --- orchestration: storage ports ----------------------------------------

    def _artifact_content_storage(impl: MinioArtifactStorage) -> ArtifactContentStoragePort:
        return impl

    def _claude_plugin_storage(impl: MinioClaudePluginStorage) -> ClaudePluginStoragePort:
        return impl

    def _skill_storage(impl: MinioSkillStorage) -> SkillStoragePort:
        return impl

    def _conversation_storage(impl: MinioConversationStorage) -> ConversationStoragePort:
        return impl

    def _codex_rollout(impl: ManagedWorkspace) -> CodexRolloutPort:
        return impl

    # --- artifacts context ----------------------------------------------------
    # A second, separately declared port of the same name; the same MinIO
    # adapter has to satisfy both.

    def _artifacts_context_content_storage(
        impl: MinioArtifactStorage,
    ) -> ArtifactsContextContentStoragePort:
        return impl

    # --- agent_sessions context ----------------------------------------------

    def _session_observations(impl: AgentEventStore) -> SessionObservationPort:
        return impl

    # --- github context -------------------------------------------------------

    def _github_events_api(impl: GitHubEventsAPIClient) -> GitHubEventsAPIPort:
        return impl

    def _github_checks_api(impl: GitHubChecksAPIClient) -> GitHubChecksAPIPort:
        return impl
