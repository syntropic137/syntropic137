"""OTel Configuration Factory for AEF.

Provides factory functions to create OTelConfig instances with
AEF-specific resource attributes for workflow/phase correlation.

Usage:
    from aef_adapters.observability import create_phase_otel_config

    config = create_phase_otel_config(
        workflow_execution_id="wfe_abc123",
        workflow_phase_id="wfp_def456",
        workflow_phase_name="implement",
        workflow_template_id="github-pr",
        tenant_id="tenant_xyz",
        pr_number="42",
        repo="acme/app",
    )

    # Inject into container environment
    env = config.to_env()

See ADR-028: OTel Platform Integration for architectural details.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from aef_adapters.observability.conventions import AEFSemanticConventions

if TYPE_CHECKING:
    from agentic_otel import OTelConfig


def create_phase_otel_config(
    workflow_execution_id: str,
    workflow_phase_id: str,
    workflow_phase_name: str,
    workflow_template_id: str,
    tenant_id: str,
    pr_number: str | None = None,
    repo: str | None = None,
    commit_sha: str | None = None,
    task_id: str | None = None,
    task_system: str | None = None,
    endpoint: str | None = None,
    service_name: str = "agentic-agent",
) -> OTelConfig:
    """Create an OTelConfig with AEF resource attributes.

    This factory injects AEF-specific context into the OTelConfig so that
    all OTel signals (metrics, traces, logs) emitted from the container
    can be correlated back to the workflow execution.

    Args:
        workflow_execution_id: Unique ID for the workflow execution
        workflow_phase_id: Unique ID for this phase
        workflow_phase_name: Human-readable phase name (e.g., "implement")
        workflow_template_id: The workflow template being executed
        tenant_id: Multi-tenant identifier
        pr_number: GitHub PR number (optional)
        repo: GitHub repository in owner/name format (optional)
        commit_sha: Git commit SHA (optional)
        task_id: External task ID like JIRA ticket (optional)
        task_system: Task system identifier (optional)
        endpoint: OTel Collector endpoint (defaults to env or localhost)
        service_name: OTel service name (default: agentic-agent)

    Returns:
        OTelConfig with all resource attributes set

    Raises:
        ImportError: If agentic_otel is not installed
    """
    from agentic_otel import OTelConfig

    # Build resource attributes from AEF conventions
    conv = AEFSemanticConventions
    resource_attrs: dict[str, str] = {
        conv.WORKFLOW_EXECUTION_ID: workflow_execution_id,
        conv.WORKFLOW_PHASE_ID: workflow_phase_id,
        conv.WORKFLOW_PHASE_NAME: workflow_phase_name,
        conv.WORKFLOW_TEMPLATE_ID: workflow_template_id,
        conv.TENANT_ID: tenant_id,
    }

    # Add optional GitHub context
    if pr_number:
        resource_attrs[conv.GITHUB_PR_NUMBER] = pr_number
    if repo:
        resource_attrs[conv.GITHUB_REPO] = repo
    if commit_sha:
        resource_attrs[conv.GITHUB_COMMIT_SHA] = commit_sha

    # Add optional task context
    if task_id:
        resource_attrs[conv.TASK_ID] = task_id
    if task_system:
        resource_attrs[conv.TASK_SYSTEM] = task_system

    # Determine endpoint (use helper for consistent resolution)
    if endpoint is None:
        endpoint = get_collector_endpoint()

    return OTelConfig(
        endpoint=endpoint,
        service_name=service_name,
        resource_attributes=resource_attrs,
    )


def get_collector_endpoint() -> str:
    """Get the OTel Collector endpoint from environment.

    Resolution order:
    1. OTEL_EXPORTER_OTLP_ENDPOINT env var (explicit override)
    2. AEF_OTEL_COLLECTOR_HOST env var (Docker network name)
    3. Default to localhost:4317 (local development)

    In Docker compose, set AEF_OTEL_COLLECTOR_HOST=otel-collector

    Returns:
        Collector endpoint URL
    """
    # Check for explicit endpoint first
    explicit = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if explicit:
        return explicit

    # Check for Docker-style host override
    host = os.getenv("AEF_OTEL_COLLECTOR_HOST", "localhost")
    port = os.getenv("AEF_OTEL_COLLECTOR_PORT", "4317")

    return f"http://{host}:{port}"
