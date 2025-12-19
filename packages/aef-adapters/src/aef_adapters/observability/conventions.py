"""AEF Semantic Conventions for OpenTelemetry.

Defines resource attributes and semantic conventions specific to the
Agentic Engineering Framework. These extend the agentic-primitives
AgentSemanticConventions with platform-level context.

Usage:
    from aef_adapters.observability import AEFSemanticConventions

    # Use as constants
    attrs = {
        AEFSemanticConventions.WORKFLOW_EXECUTION_ID: execution.id,
        AEFSemanticConventions.WORKFLOW_PHASE_ID: phase.id,
    }

See ADR-028: OTel Platform Integration for architectural details.
See ADR-029: Explicit Naming Convention for naming rationale.
"""

from __future__ import annotations


class AEFSemanticConventions:
    """AEF-specific OpenTelemetry semantic conventions.

    These resource attributes are injected into container environments
    to enable correlation of all OTel signals (metrics, traces, logs)
    from agent sessions back to workflow executions.

    Hierarchy:
        workflow_template_id -> workflow_execution_id -> workflow_phase_id -> agent.session.id
    """

    # ========== Workflow Context ==========
    # The workflow template that defines the execution
    WORKFLOW_TEMPLATE_ID = "aef.workflow.template.id"

    # Unique identifier for a specific workflow execution run
    WORKFLOW_EXECUTION_ID = "aef.workflow.execution.id"

    # Unique identifier for a phase within the workflow execution
    WORKFLOW_PHASE_ID = "aef.workflow.phase.id"

    # Human-readable name of the phase (e.g., "research", "implement")
    WORKFLOW_PHASE_NAME = "aef.workflow.phase.name"

    # ========== GitHub Context ==========
    # Pull request number for correlation with GitHub
    GITHUB_PR_NUMBER = "github.pr.number"

    # Repository in owner/name format
    GITHUB_REPO = "github.repo"

    # Commit SHA for the PR head
    GITHUB_COMMIT_SHA = "github.commit.sha"

    # ========== Tenant Context ==========
    # Multi-tenant identifier (for SaaS deployments)
    TENANT_ID = "aef.tenant.id"

    # ========== Task Context ==========
    # External task identifier (e.g., JIRA, Linear)
    TASK_ID = "aef.task.id"

    # Task system identifier
    TASK_SYSTEM = "aef.task.system"

    @classmethod
    def all_attributes(cls) -> list[str]:
        """Return all AEF semantic convention attribute names.

        Useful for documentation and validation.
        """
        return [attr for attr in dir(cls) if attr.isupper() and not attr.startswith("_")]
