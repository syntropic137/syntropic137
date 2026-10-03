"""An execution records the commit each repository was at when it started (#1457).

Driven through `ExecuteWorkflowHandler` over a shipped workflow, because the
handler is the one place that knows both the repositories a run was given and
the resolver that can name their commits. The processor is the double: what it
does with `source_commits` - write them on the start event, and hand them to a
resume - is proven against the real one in `start_resume/test_start_resume.py` and
`aggregate_execution/test_resume_start.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        SourceCommit,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOW = (
    Path(__file__).resolve().parents[8] / "workflows" / "sdlc" / "quickfix" / "workflow.yaml"
)
_SHA = "7c0ffee7c0ffee7c0ffee7c0ffee7c0ffee7c0ff"


class _Resolver:
    """Knows one repository's commit; the rest are unknown, as a port may say."""

    def __init__(self, known: dict[str, str]) -> None:
        self._known = known
        self.asked: list[str] = []

    async def head_sha(self, repo: RepositoryRef) -> str | None:
        self.asked.append(repo.slug)
        return self._known.get(repo.slug)


class _Processor:
    def __init__(self) -> None:
        self.source_commits: list[SourceCommit] | None = None

    async def run(
        self,
        *,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, str],
        execution_id: str,
        repos: list[RepositoryRef],
        admitted: object = None,
        source_commits: list[SourceCommit] | None = None,
        tags: object = None,
    ) -> WorkflowExecutionResult:
        del workflow_name, phases, inputs, repos, admitted
        self.source_commits = source_commits
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="completed",
            started_at=datetime.now(UTC),
        )


async def _start(resolver: _Resolver | None, *slugs: str) -> list[SourceCommit] | None:
    definition = WorkflowDefinition.from_file(_WORKFLOW)
    template = WorkflowTemplateAggregate()
    template.create_workflow(build_command_from_definition(definition))

    class _Templates:
        async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
            return template if aggregate_id == definition.id else None

    processor = _Processor()
    handler = ExecuteWorkflowHandler(
        processor=processor,  # type: ignore[arg-type]
        workflow_repository=_Templates(),  # type: ignore[arg-type]
        commit_resolver=resolver,
    )
    await handler.handle(
        ExecuteWorkflowCommand(
            aggregate_id=definition.id,
            repos=[RepositoryRef.from_slug(s) for s in slugs],
            inputs={"task": "fix it"},
        )
    )
    return processor.source_commits


async def test_each_repository_is_recorded_at_the_commit_it_was_at() -> None:
    resolver = _Resolver({"acme/widgets": _SHA})

    commits = await _start(resolver, "acme/widgets", "acme/gadgets")

    assert commits is not None
    assert [(c.repository, c.sha) for c in commits] == [
        ("acme/widgets", _SHA),
        ("acme/gadgets", None),
    ]
    assert resolver.asked == ["acme/widgets", "acme/gadgets"]


async def test_with_no_resolver_every_repository_is_still_listed_as_unknown() -> None:
    """The list says which repositories the run had even when none is pinned."""
    commits = await _start(None, "acme/widgets")

    assert commits is not None
    assert [(c.repository, c.sha) for c in commits] == [("acme/widgets", None)]
