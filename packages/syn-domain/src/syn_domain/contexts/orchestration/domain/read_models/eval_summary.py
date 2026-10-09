"""Read models for the eval list and eval detail views (#967).

An Eval's runs are not stored here. They are Executions, and their status,
tokens and repositories stay in the execution read model; these models carry
only what the Eval stream records, plus the run tally a query attaches from
the execution list (filtered by ``eval_id``) when it builds a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
        WorkflowExecutionSummary,
    )
    from syn_domain.pagination import Page


class EvalBaselineRepo(BaseModel):
    """One repository of an Eval's Baseline: where every run starts."""

    model_config = ConfigDict(frozen=True)

    owner: str
    name: str
    requested_ref: str
    """The branch, tag or commit the caller named, kept for display."""
    commit_sha: str
    """The full SHA ``requested_ref`` resolved to when the Baseline was saved."""


class EvalDefinitionChange(BaseModel):
    """One edit to what an Eval measures: its goal or its baseline (#1788).

    A rename or a retag is not one: it describes the experiment, not what it
    measures, so a trend chart has nothing to annotate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int
    """The event's position in the Eval's stream: the change's identity and its order.

    Never the time: two edits committed together share a millisecond."""
    definition_version: int
    """1 at creation, then one more per goal or baseline change."""
    changed_at: str
    """ISO 8601 UTC, from the event that made the change."""


class EvalRecord(BaseModel):
    """An Eval as its own stream records it, with no run facts.

    Also the stored document: written with ``model_dump(mode="json")`` and
    read back with ``model_validate``, so the two cannot drift.
    """

    model_config = ConfigDict(frozen=True)

    eval_id: str
    name: str
    goal: str
    starting_workflow_id: str | None = None
    baseline_repos: tuple[EvalBaselineRepo, ...] = ()
    tags: tuple[str, ...] = ()
    frozen: bool = False
    archived: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    definition_changes: tuple[EvalDefinitionChange, ...] = ()
    """Every definition change, in stream order; the last is the current definition."""


@dataclass(frozen=True)
class EvalSummary:
    """One row of the eval list: the Eval and how many runs it has, by status."""

    record: EvalRecord
    run_count: int
    """Executions currently in the Eval. A detached run is not counted."""
    run_status_counts: dict[str, int] = field(default_factory=dict)
    """Those executions tallied by execution status."""


@dataclass(frozen=True)
class EvalDetail:
    """One Eval with its Baseline and one page of its member executions."""

    record: EvalRecord
    runs: Page[WorkflowExecutionSummary]
    """``total`` and ``status_counts`` describe every member, not this page."""
