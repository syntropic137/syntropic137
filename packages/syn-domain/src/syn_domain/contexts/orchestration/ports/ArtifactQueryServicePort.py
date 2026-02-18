"""Port interface for querying artifacts from projections.

This port provides read-only access to artifact projections for multi-phase
workflows. Artifacts from previous phases are injected into subsequent phase prompts.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.ArtifactValueObjects import (
        ArtifactSummary,
    )


class ArtifactQueryServicePort(Protocol):
    """Port for querying artifacts from the artifact projection.

    This port is REQUIRED for multi-phase workflows. It queries the
    artifact_list projection to retrieve phase outputs for injection
    into subsequent phase prompts.

    Example workflow:
    - Phase 1 (Research): Creates artifact with research findings
    - Phase 2 (Planning): Injects Phase 1 artifact into prompt
    - Phase 3 (Implementation): Injects Phase 1 + Phase 2 artifacts
    """

    async def get_for_phase_injection(
        self,
        execution_id: str,
        completed_phase_ids: list[str],
    ) -> dict[str, str]:
        """Get artifact content for injecting into phase prompts.

        Retrieves artifacts from completed phases for the given execution.
        Returns a mapping of phase_id -> artifact_content for prompt substitution.

        Args:
            execution_id: The execution ID to query artifacts for.
            completed_phase_ids: List of phase IDs that have completed
                (in order of execution).

        Returns:
            Dictionary mapping phase_id to artifact content (str).
            Only includes the primary/latest artifact for each phase.

        Example:
            # After Phase 1 and Phase 2 complete
            phase_outputs = await artifact_query.get_for_phase_injection(
                execution_id="exec-123",
                completed_phase_ids=["research", "planning"],
            )
            # Returns: {
            #     "research": "# Research Findings\n...",
            #     "planning": "# Implementation Plan\n...",
            # }

            # Use in prompt template:
            # prompt = f'''
            # Based on the research:
            # {phase_outputs["research"]}
            #
            # And the plan:
            # {phase_outputs["planning"]}
            #
            # Implement the solution.
            # '''
        """
        ...

    async def get_by_execution(
        self,
        execution_id: str,
    ) -> list["ArtifactSummary"]:
        """Get all artifacts for an execution.

        Args:
            execution_id: The execution ID to query artifacts for.

        Returns:
            List of ArtifactSummary objects (from projection).
        """
        ...
