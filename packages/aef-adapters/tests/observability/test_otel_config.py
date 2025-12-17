"""Tests for OTel configuration factory."""

import os
from unittest.mock import patch

import pytest

from aef_adapters.observability.conventions import AEFSemanticConventions
from aef_adapters.observability.otel_config import (
    create_phase_otel_config,
    get_collector_endpoint,
)


class TestCreatePhaseOtelConfig:
    """Tests for create_phase_otel_config factory."""

    def test_creates_config_with_required_fields(self) -> None:
        """Test that required fields are set correctly."""
        config = create_phase_otel_config(
            workflow_execution_id="wfe_abc123",
            workflow_phase_id="wfp_def456",
            workflow_phase_name="implement",
            workflow_template_id="github-pr",
            tenant_id="tenant_xyz",
        )

        # Check resource attributes
        attrs = config.resource_attributes
        conv = AEFSemanticConventions

        assert attrs[conv.WORKFLOW_EXECUTION_ID] == "wfe_abc123"
        assert attrs[conv.WORKFLOW_PHASE_ID] == "wfp_def456"
        assert attrs[conv.WORKFLOW_PHASE_NAME] == "implement"
        assert attrs[conv.WORKFLOW_TEMPLATE_ID] == "github-pr"
        assert attrs[conv.TENANT_ID] == "tenant_xyz"

    def test_includes_github_context_when_provided(self) -> None:
        """Test that GitHub context is included when provided."""
        config = create_phase_otel_config(
            workflow_execution_id="wfe_abc123",
            workflow_phase_id="wfp_def456",
            workflow_phase_name="implement",
            workflow_template_id="github-pr",
            tenant_id="tenant_xyz",
            pr_number="42",
            repo="acme/app",
            commit_sha="abc123def456",
        )

        attrs = config.resource_attributes
        conv = AEFSemanticConventions

        assert attrs[conv.GITHUB_PR_NUMBER] == "42"
        assert attrs[conv.GITHUB_REPO] == "acme/app"
        assert attrs[conv.GITHUB_COMMIT_SHA] == "abc123def456"

    def test_excludes_github_context_when_not_provided(self) -> None:
        """Test that GitHub context is excluded when not provided."""
        config = create_phase_otel_config(
            workflow_execution_id="wfe_abc123",
            workflow_phase_id="wfp_def456",
            workflow_phase_name="implement",
            workflow_template_id="github-pr",
            tenant_id="tenant_xyz",
        )

        attrs = config.resource_attributes
        conv = AEFSemanticConventions

        assert conv.GITHUB_PR_NUMBER not in attrs
        assert conv.GITHUB_REPO not in attrs

    def test_includes_task_context_when_provided(self) -> None:
        """Test that task context is included when provided."""
        config = create_phase_otel_config(
            workflow_execution_id="wfe_abc123",
            workflow_phase_id="wfp_def456",
            workflow_phase_name="implement",
            workflow_template_id="github-pr",
            tenant_id="tenant_xyz",
            task_id="PROJ-123",
            task_system="jira",
        )

        attrs = config.resource_attributes
        conv = AEFSemanticConventions

        assert attrs[conv.TASK_ID] == "PROJ-123"
        assert attrs[conv.TASK_SYSTEM] == "jira"

    def test_uses_default_endpoint(self) -> None:
        """Test that default endpoint is used when not provided."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove OTEL_EXPORTER_OTLP_ENDPOINT if set
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)

            config = create_phase_otel_config(
                workflow_execution_id="wfe_abc123",
                workflow_phase_id="wfp_def456",
                workflow_phase_name="implement",
                workflow_template_id="github-pr",
                tenant_id="tenant_xyz",
            )

            assert config.endpoint == "http://localhost:4317"

    def test_uses_endpoint_from_env(self) -> None:
        """Test that endpoint is read from environment."""
        with patch.dict(
            os.environ,
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"},
        ):
            config = create_phase_otel_config(
                workflow_execution_id="wfe_abc123",
                workflow_phase_id="wfp_def456",
                workflow_phase_name="implement",
                workflow_template_id="github-pr",
                tenant_id="tenant_xyz",
            )

            assert config.endpoint == "http://collector:4317"

    def test_uses_explicit_endpoint_over_env(self) -> None:
        """Test that explicit endpoint overrides environment."""
        with patch.dict(
            os.environ,
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"},
        ):
            config = create_phase_otel_config(
                workflow_execution_id="wfe_abc123",
                workflow_phase_id="wfp_def456",
                workflow_phase_name="implement",
                workflow_template_id="github-pr",
                tenant_id="tenant_xyz",
                endpoint="http://custom:4317",
            )

            assert config.endpoint == "http://custom:4317"

    def test_uses_custom_service_name(self) -> None:
        """Test that custom service name is used."""
        config = create_phase_otel_config(
            workflow_execution_id="wfe_abc123",
            workflow_phase_id="wfp_def456",
            workflow_phase_name="implement",
            workflow_template_id="github-pr",
            tenant_id="tenant_xyz",
            service_name="my-custom-agent",
        )

        assert config.service_name == "my-custom-agent"

    def test_config_can_be_converted_to_env(self) -> None:
        """Test that config can be converted to environment variables."""
        config = create_phase_otel_config(
            workflow_execution_id="wfe_abc123",
            workflow_phase_id="wfp_def456",
            workflow_phase_name="implement",
            workflow_template_id="github-pr",
            tenant_id="tenant_xyz",
        )

        env_vars = config.to_env()

        assert isinstance(env_vars, dict)
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" in env_vars
        assert "OTEL_SERVICE_NAME" in env_vars
        assert "OTEL_RESOURCE_ATTRIBUTES" in env_vars


class TestGetCollectorEndpoint:
    """Tests for get_collector_endpoint utility."""

    def test_returns_default_when_not_set(self) -> None:
        """Test that default endpoint is returned."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)

            endpoint = get_collector_endpoint()
            assert endpoint == "http://localhost:4317"

    def test_returns_value_from_env(self) -> None:
        """Test that endpoint from environment is returned."""
        with patch.dict(
            os.environ,
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"},
        ):
            endpoint = get_collector_endpoint()
            assert endpoint == "http://collector:4317"
