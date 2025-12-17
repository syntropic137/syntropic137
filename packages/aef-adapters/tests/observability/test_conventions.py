"""Tests for AEFSemanticConventions."""

import pytest

from aef_adapters.observability.conventions import AEFSemanticConventions


class TestAEFSemanticConventions:
    """Tests for AEFSemanticConventions class."""

    def test_workflow_attributes_exist(self) -> None:
        """Test that workflow context attributes are defined."""
        assert hasattr(AEFSemanticConventions, "WORKFLOW_TEMPLATE_ID")
        assert hasattr(AEFSemanticConventions, "WORKFLOW_EXECUTION_ID")
        assert hasattr(AEFSemanticConventions, "WORKFLOW_PHASE_ID")
        assert hasattr(AEFSemanticConventions, "WORKFLOW_PHASE_NAME")

    def test_github_attributes_exist(self) -> None:
        """Test that GitHub context attributes are defined."""
        assert hasattr(AEFSemanticConventions, "GITHUB_PR_NUMBER")
        assert hasattr(AEFSemanticConventions, "GITHUB_REPO")
        assert hasattr(AEFSemanticConventions, "GITHUB_COMMIT_SHA")

    def test_tenant_attribute_exists(self) -> None:
        """Test that tenant ID attribute is defined."""
        assert hasattr(AEFSemanticConventions, "TENANT_ID")

    def test_task_attributes_exist(self) -> None:
        """Test that task context attributes are defined."""
        assert hasattr(AEFSemanticConventions, "TASK_ID")
        assert hasattr(AEFSemanticConventions, "TASK_SYSTEM")

    def test_attribute_values_follow_naming_convention(self) -> None:
        """Test that attribute values follow dot-notation convention."""
        # All AEF attributes should start with 'aef.'
        assert AEFSemanticConventions.WORKFLOW_TEMPLATE_ID.startswith("aef.")
        assert AEFSemanticConventions.WORKFLOW_EXECUTION_ID.startswith("aef.")
        assert AEFSemanticConventions.WORKFLOW_PHASE_ID.startswith("aef.")
        assert AEFSemanticConventions.TENANT_ID.startswith("aef.")

        # GitHub attributes should start with 'github.'
        assert AEFSemanticConventions.GITHUB_PR_NUMBER.startswith("github.")
        assert AEFSemanticConventions.GITHUB_REPO.startswith("github.")

    def test_all_attributes_returns_list(self) -> None:
        """Test that all_attributes returns all constant names."""
        attrs = AEFSemanticConventions.all_attributes()

        assert isinstance(attrs, list)
        assert len(attrs) >= 9  # At least 9 attributes defined
        assert "WORKFLOW_EXECUTION_ID" in attrs
        assert "GITHUB_PR_NUMBER" in attrs

    def test_explicit_naming_convention(self) -> None:
        """Test that naming is explicit and unambiguous."""
        # These should include 'workflow' and 'execution' / 'phase' context
        # Format: aef.workflow.{execution_id|phase_id}
        exec_id = AEFSemanticConventions.WORKFLOW_EXECUTION_ID
        phase_id = AEFSemanticConventions.WORKFLOW_PHASE_ID

        assert "workflow" in exec_id
        assert "execution" in exec_id
        assert "workflow" in phase_id
        assert "phase" in phase_id

        # Not just 'execution_id' or 'phase_id' without context
        assert AEFSemanticConventions.WORKFLOW_EXECUTION_ID != "aef.execution_id"
        assert AEFSemanticConventions.WORKFLOW_PHASE_ID != "aef.phase_id"
