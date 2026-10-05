"""ExecuteWorkflow command - represents intent to execute a workflow."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts._shared.repository_ref import (
    RepositoryRef,  # noqa: TC001 - runtime field type
)
from syn_domain.contexts.orchestration._shared.eval_choice import LaunchEval  # noqa: TC001
from syn_domain.contexts.orchestration._shared.repository_baseline import (
    RepositoryBaseline,
)
from syn_domain.contexts.orchestration._shared.tags import TagSet


@command("ExecuteWorkflow", "Starts execution of a workflow")
class ExecuteWorkflowCommand(BaseModel):
    """Command to start executing a workflow.

    The workflow must already exist. This command initiates
    the execution process with provided inputs.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # Target aggregate - the workflow to execute
    aggregate_id: str = Field(..., min_length=1, description="Workflow ID to execute")

    # Input variables for the workflow
    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="Input variables for the workflow phases",
    )

    # Typed repository identity (ADR-063 anti-corruption layer).
    # Replaces implicit inputs["repository"] / inputs["repos"] dict-key conventions.
    repos: list[RepositoryRef] = Field(
        default_factory=list,
        description="Repositories for workspace hydration, typed at the boundary.",
    )

    # Typed tags (#967). United with the workflow's own tags at launch; never
    # carried in `inputs`, where no filter would ever see them.
    tags: TagSet = Field(
        default_factory=TagSet,
        description="Tags for this run, added to the workflow's tags at launch.",
    )

    # Which eval this run joins, and the baseline it starts from (#967).
    # Resolved and admitted ONCE, by whoever builds the command
    # (`eval_admission.launch_eval_for`), so a retried dispatch joins the eval
    # it was dispatched into even if the workflow's default changed since.
    # None means no dispatcher decided: the handler then refuses a workflow
    # that has a default eval rather than silently running outside it.
    launch_eval: LaunchEval | None = Field(
        default=None,
        description="The eval this run joins and its frozen baseline, resolved before dispatch.",
    )

    # Optional execution context
    execution_id: str | None = Field(
        default=None,
        description="Custom execution ID (generated if not provided)",
    )

    # Primary task description -- substituted for $ARGUMENTS in phase prompts
    task: str | None = Field(
        default=None,
        description="Primary task description, substituted for $ARGUMENTS in prompts",
    )

    # Dry run mode - validate without executing
    dry_run: bool = Field(
        default=False,
        description="If true, validate inputs but don't execute",
    )


# `LaunchEval.baseline` names `RepositoryBaseline` only under TYPE_CHECKING
# (importing it there cycles through the ports package), so pydantic is given
# the name here, where it can be imported.
ExecuteWorkflowCommand.model_rebuild(_types_namespace={"RepositoryBaseline": RepositoryBaseline})
