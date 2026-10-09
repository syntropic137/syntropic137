"""PC-83 through the REAL stream parsers: raw harness JSONL decides the fallback.

`test_pc83_a_phase_falls_back_once.py` scripts each attempt's outcome as a
post-parser string, so it proves the fallback rule is applied and can never
prove the parsers classify a real busy or quota line as the failure kinds that
rule accepts. Here every attempt is RAW JSONL, read by `EventStreamProcessor`
or `CodexStreamProcessor` - whichever the runner `run_phase_agent` picked for
that attempt says - under `processor.run()` with the real provisioning
handler. What is asserted is the recorded `AgentExecutionCompleted`, the
execution detail the API reads, and the message an operator sees.

Mutation check: replacing the fallback dispatch in `run_phase_agent` with a
return of the primary's result fails (a), (b) and (e) below; dropping the
`work_done` guard from `fallback_attempt` fails (f); letting the first codex
`error` outrank `turn.failed` again in `CodexStreamProcessor` fails (g).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration import (
    AgentExecutionCompletedCommand,
    AgentExecutionResult,
    SubagentTracker,
    TokenAccumulator,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE
from syn_shared.agents import AgentProvider, AgentRunner

from .test_processor_smoke import FakeExecutionRepository, _make_processor, _one_phase_workflow

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from event_sourcing import DomainEvent

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_cost_limit import (
        PhaseCostLimit,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_push import (
        PushObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        Runner,
        WorkflowExecutionResult,
    )

pytestmark = pytest.mark.unit

NO_WAITING = UpstreamRetryPolicy(base_delay_seconds=0.0)

SUCCEEDED = 'TASK_RESULT: {"success": true, "comments": "verified"}\nTASK_RESULT_END'

#: Claude's busy fault as the raw terminal line claude writes (#1303).
CLAUDE_OVERLOADED = json.dumps(
    {
        "type": "result",
        "is_error": True,
        "result": (
            'API Error: 529 {"type":"error","error":'
            '{"type":"overloaded_error","message":"Overloaded"}}'
        ),
    }
)

#: The real codex quota sentence, observed 2026-10-06, on the event codex puts it on.
CODEX_QUOTA_SENTENCE = (
    "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to "
    "purchase more credits or try again at Oct 9th, 2026 9:10 PM."
)
CODEX_QUOTA = json.dumps({"type": "turn.failed", "error": {"message": CODEX_QUOTA_SENTENCE}})

#: The real codex content-filter refusal, as codex streamed it (exec-61dad6055e6f).
#: Its first lines are an `item.completed` `agent_message`: the agent had
#: started, and said something, but had done no work (#1825).
CODEX_REFUSED_AS_OBSERVED: tuple[str, ...] = tuple(
    (Path(__file__).parents[3] / "fixtures" / "codex" / "codex_turn_failed.jsonl")
    .read_text()
    .splitlines()
)
#: The same refusal arriving before codex completed any item: the request was
#: declined before the agent did anything.
CODEX_REFUSED_BEFORE_WORK: tuple[str, ...] = tuple(
    line for line in CODEX_REFUSED_AS_OBSERVED if '"item.completed"' not in line
)


def _codex_read(item_id: str, command: str) -> tuple[str, str]:
    """A codex shell command, opened and closed, exactly as codex emits it."""
    item = {"id": item_id, "type": "command_execution", "command": command}
    return (
        json.dumps({"type": "item.started", "item": item}),
        json.dumps({"type": "item.completed", "item": {**item, "exit_code": 0}}),
    )


#: What a codex verifier does before it is refused (exec-dc6a7109b21b): reads
#: the change, then the observed refusal.
CODEX_REFUSED_AFTER_READING: tuple[str, ...] = (
    *_codex_read("item_r1", "/bin/zsh -lc 'gh pr diff 1819'"),
    *_codex_read("item_r2", "/bin/zsh -lc 'sed -n 1,200p agent_attempts.py'"),
    *CODEX_REFUSED_AS_OBSERVED,
)
#: The refusal after codex EDITED a file: that is work, and a second agent
#: from the top would redo it.
CODEX_REFUSED_AFTER_WORK: tuple[str, ...] = (
    json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": "item_w1",
                "type": "file_change",
                "status": "completed",
                "changes": [{"path": "a.py", "kind": "update"}],
            },
        }
    ),
    *CODEX_REFUSED_BEFORE_WORK,
)
#: The `error` codex recovered from in `codex_error_then_recovered.jsonl`.
CODEX_HICCUP: str = next(
    line
    for line in (
        Path(__file__).parents[3] / "fixtures" / "codex" / "codex_error_then_recovered.jsonl"
    )
    .read_text()
    .splitlines()
    if '"type":"error"' in line
)
#: A constructed stream, not a recording: that hiccup, then the refusal, with
#: no item between them. The turn codex failed was failed by the refusal.
CODEX_HICCUP_THEN_REFUSED: tuple[str, ...] = (
    *CODEX_REFUSED_BEFORE_WORK[:2],
    CODEX_HICCUP,
    *CODEX_REFUSED_BEFORE_WORK[2:],
)

#: A failure that is neither busy nor quota, for the fallback itself to hit.
CODEX_NOT_LOGGED_IN = json.dumps(
    {
        "type": "turn.failed",
        "error": {"message": "You are not logged in. Run `codex login` to continue."},
    }
)

CLAUDE_SUCCEEDS = json.dumps({"type": "result", "is_error": False, "result": SUCCEEDED})
CODEX_SUCCEEDS = (
    json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": SUCCEEDED}}),
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
)

CODEX_FALLBACK = AgentConfiguration(provider=AgentProvider.CODEX, model="gpt-5.1-codex-max")
CLAUDE_FALLBACK = AgentConfiguration(provider=AgentProvider.CLAUDE, model="claude-fallback-model")


async def _as_stream(lines: tuple[str, ...]) -> AsyncIterator[str]:
    for line in lines:
        yield line


@dataclass
class _RawJsonlAgent:
    """Feeds each attempt's raw lines to production's parser for that attempt's runner.

    The double decides nothing about what a stream meant: the parser's
    `StreamResult` is what `run_phase_agent` judges. A clean stream writes the
    deliverable, as an agent that finished would have.
    """

    attempts: tuple[tuple[str, ...], ...]
    runners: list[Runner] = field(default_factory=list)

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
        cost_limit: PhaseCostLimit | None = None,
        on_push: PushObserver | None = None,
    ) -> AgentExecutionResult:
        self.runners.append(runner)
        lines = self.attempts[len(self.runners) - 1]
        assert todo.phase_id is not None
        if on_launch is not None:
            await on_launch()
        tokens = TokenAccumulator()
        subagents = SubagentTracker()
        parser: EventStreamProcessor | CodexStreamProcessor
        if runner == AgentRunner.CODEX:
            parser = CodexStreamProcessor(
                tokens=tokens,
                collector=collector,
                controller=None,
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                agent_model=agent_model,
                rollout=None,
            )
        else:
            parser = EventStreamProcessor(
                tokens=tokens,
                subagents=subagents,
                observability=None,
                controller=None,
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                workspace_id=None,
                agent_model=agent_model,
                collector=collector,
            )
        stream_result = await parser.process_stream(_as_stream(lines), workspace)
        if not stream_result.error_reason:
            await workspace.inject_files(list(A_DELIVERABLE))
        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
            subagents=subagents,
            command=AgentExecutionCompletedCommand(
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                exit_code=1 if stream_result.error_reason else 0,
                last_agent_message=stream_result.last_agent_message,
            ),
        )


# pyright verifies the double still matches the real handler's contract.
_: AgentHandlerProtocol = _RawJsonlAgent(attempts=())


class _ReplayedTransport:
    """A workspace whose agent subprocess printed `lines` and exited `exit_code`.

    The ONLY substitution: `AgentExecutionHandler` launches against it as it
    would a container, picks its parser, and judges the result itself.
    """

    def __init__(self, workspace: ManagedWorkspace, lines: tuple[str, ...], exit_code: int) -> None:
        self._workspace = workspace
        self._lines = lines
        self.last_stream_exit_code = exit_code

    def __getattr__(self, name: str) -> object:
        return getattr(self._workspace, name)

    async def stream(self, *_args: object, **_kwargs: object) -> AsyncIterator[str]:
        if CLAUDE_SUCCEEDS in self._lines:
            await self._workspace.inject_files(list(A_DELIVERABLE))
        for line in self._lines:
            yield line


@dataclass
class _ProductionHandlerAgent(_RawJsonlAgent):
    """The real `AgentExecutionHandler`, over a replayed subprocess per attempt."""

    exit_codes: tuple[int, ...] = ()

    async def handle(  # type: ignore[override]
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
        cost_limit: PhaseCostLimit | None = None,
        on_push: PushObserver | None = None,
    ) -> AgentExecutionResult:
        self.runners.append(runner)
        attempt = len(self.runners) - 1
        transport = _ReplayedTransport(
            workspace,
            self.attempts[attempt],
            self.exit_codes[attempt] if attempt < len(self.exit_codes) else 0,
        )
        return await AgentExecutionHandler(controller=None).handle(
            todo=todo,
            workspace=transport,  # type: ignore[arg-type]
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            session_id=session_id,
            agent_model=agent_model,
            timeout_seconds=timeout_seconds,
            collector=collector,
            runner=runner,
            on_launch=on_launch,
            cost_limit=cost_limit,
            on_push=on_push,
        )


class _RecordingRepository(FakeExecutionRepository):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[DomainEvent] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.extend(envelope.event for envelope in aggregate.get_uncommitted_events())
        await super().save(aggregate)


def _phase(primary: AgentConfiguration, fallback: AgentConfiguration | None) -> ExecutablePhase:
    (phase,) = _one_phase_workflow()
    return replace(phase, agent_config=primary, fallback_agent=fallback)


async def _run(
    agent: _RawJsonlAgent, phase: ExecutablePhase, execution_id: str
) -> tuple[WorkflowExecutionResult, _RecordingRepository]:
    repository = _RecordingRepository()
    processor = _make_processor(agent, retry_policy=NO_WAITING, execution_repository=repository)
    result = await processor.run(
        workflow_id="wf-pc83-raw",
        workflow_name="Fallback agent, raw streams",
        phases=[phase],
        inputs={},
        execution_id=execution_id,
    )
    return result, repository


def _completed(repository: _RecordingRepository) -> AgentExecutionCompletedEvent:
    (event,) = [e for e in repository.events if isinstance(e, AgentExecutionCompletedEvent)]
    return event


async def _detail(repository: _RecordingRepository, execution_id: str) -> WorkflowExecutionDetail:
    """The execution record GET /executions/{id} serves, built from the run's own events."""
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    for event in repository.events:
        handler_name = ExecutionJournal._event_type_to_handler(  # pyright: ignore[reportPrivateUsage]
            getattr(event, "event_type", type(event).__name__)
        )
        handler = getattr(projection, handler_name, None)
        if handler:
            await handler(ExecutionJournal._serialize_event(event))  # pyright: ignore[reportPrivateUsage]
    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, execution_id)
    assert record is not None
    return WorkflowExecutionDetail.from_dict(record)


class TestRawStreamsFallBack:
    async def test_a_claude_overloaded_past_its_retries_completes_on_the_fallback(self) -> None:
        """(a) Raw claude 529 on every retry, then the codex fallback finishes the phase."""
        agent = _RawJsonlAgent(
            attempts=(*[(CLAUDE_OVERLOADED,)] * NO_WAITING.max_attempts, CODEX_SUCCEEDS)
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CLAUDE), CODEX_FALLBACK)

        result, repository = await _run(agent, phase, "exec-pc83-raw-capacity")

        assert result.status == "completed", result.error_message
        assert agent.runners == [AgentRunner.CLAUDE] * NO_WAITING.max_attempts + [AgentRunner.CODEX]
        completed = _completed(repository)
        assert completed.agent_provider == AgentProvider.CODEX
        assert completed.agent_model == "gpt-5.1-codex-max"
        (row,) = (await _detail(repository, "exec-pc83-raw-capacity")).phases
        assert row.agent_provider == AgentProvider.CODEX
        assert row.agent_model == "gpt-5.1-codex-max"

    async def test_b_a_codex_quota_is_not_retried_and_completes_on_the_fallback(self) -> None:
        """(b) Raw codex quota: one primary attempt, no retry, then the claude fallback."""
        agent = _RawJsonlAgent(attempts=((CODEX_QUOTA,), (CLAUDE_SUCCEEDS,)))
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, repository = await _run(agent, phase, "exec-pc83-raw-quota")

        assert result.status == "completed", result.error_message
        assert agent.runners == [AgentRunner.CODEX, AgentRunner.CLAUDE], (
            "a spent quota was retried on the primary, or the fallback never ran"
        )
        completed = _completed(repository)
        assert completed.agent_provider == AgentProvider.CLAUDE
        assert completed.agent_model == "claude-fallback-model"

    async def test_c_a_codex_quota_with_no_fallback_fails_fast_with_its_reset_time(self) -> None:
        """(c) No fallback declared: one attempt, and the error names the reset time."""
        agent = _RawJsonlAgent(attempts=((CODEX_QUOTA,), (CODEX_SUCCEEDS)))
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), None)

        result, _repository = await _run(agent, phase, "exec-pc83-raw-quota-alone")

        assert result.status == "failed"
        assert agent.runners == [AgentRunner.CODEX], "a spent quota was retried"
        assert result.error_message is not None
        assert "codex quota exhausted until 2026-10-09T21:10" in result.error_message, (
            result.error_message
        )

    async def test_d_a_failing_fallback_fails_the_phase_naming_both_failures(self) -> None:
        """(d) Claude busy past its retries, then the codex fallback fails on its own."""
        agent = _RawJsonlAgent(
            attempts=(*[(CLAUDE_OVERLOADED,)] * NO_WAITING.max_attempts, (CODEX_NOT_LOGGED_IN,))
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CLAUDE), CODEX_FALLBACK)

        result, _repository = await _run(agent, phase, "exec-pc83-raw-both-fail")

        assert result.status == "failed"
        assert agent.runners[-1] == AgentRunner.CODEX
        message = result.error_message or ""
        assert "overloaded" in message.lower(), message
        assert "Then the fallback agent failed" in message, message
        assert "not logged in" in message, message

    async def test_e_a_codex_refusal_before_any_work_completes_on_the_fallback(self) -> None:
        """(e) Codex's content filter refuses before any item: not retried, claude runs it."""
        agent = _RawJsonlAgent(attempts=(CODEX_REFUSED_BEFORE_WORK, (CLAUDE_SUCCEEDS,)))
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, repository = await _run(agent, phase, "exec-refusal-raw-before-work")

        assert result.status == "completed", result.error_message
        assert agent.runners == [AgentRunner.CODEX, AgentRunner.CLAUDE], (
            "a refusal was retried on the primary, or the fallback never ran"
        )
        completed = _completed(repository)
        assert completed.agent_provider == AgentProvider.CLAUDE
        assert completed.agent_model == "claude-fallback-model"
        (row,) = (await _detail(repository, "exec-refusal-raw-before-work")).phases
        assert row.agent_provider == AgentProvider.CLAUDE

    async def test_e2_a_codex_refusal_after_only_reading_completes_on_the_fallback(
        self,
    ) -> None:
        """(e2) #1825: codex read the change, spoke, then was refused, and exited 1.

        Driven through the real `AgentExecutionHandler`. Before #1825 any codex
        item counted as work, so this exact verify run never reached claude.
        """
        agent = _ProductionHandlerAgent(
            attempts=(CODEX_REFUSED_AFTER_READING, (CLAUDE_SUCCEEDS,)), exit_codes=(1, 0)
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, repository = await _run(agent, phase, "exec-refusal-raw-after-reading")

        assert result.status == "completed", result.error_message
        (row,) = (await _detail(repository, "exec-refusal-raw-after-reading")).phases
        assert row.agent_provider == AgentProvider.CLAUDE
        assert row.agent_model == "claude-fallback-model"

    @pytest.mark.parametrize(
        "commands",
        [
            pytest.param(("echo reviewed & touch review-output",), id="background-touch"),
            pytest.param(("echo reviewed & git commit -am reviewed",), id="background-commit"),
            pytest.param(("echo reviewed & git push origin HEAD",), id="background-push"),
            pytest.param(("ls > /dev/null-review-output",), id="redirect-past-dev-null"),
            pytest.param(("git diff --ext-diff",), id="git-ext-diff"),
            pytest.param(("git diff --textconv",), id="git-textconv"),
            pytest.param(("git grep --open-files-in-pager=touch pattern",), id="git-grep-pager"),
            # Installing a driver is itself work. A driver installed BEFORE the
            # attempt is covered by (e4), with no installing command in the attempt.
            pytest.param(
                ("git config diff.external ./touch-driver", "git diff"), id="configured-driver"
            ),
            pytest.param(
                ("export GIT_EXTERNAL_DIFF=./touch-driver", "git diff"), id="exported-driver"
            ),
            pytest.param(("GIT_EXTERNAL_DIFF=./touch-driver git diff",), id="inline-driver"),
        ],
    )
    async def test_e3_a_codex_refusal_after_a_possible_write_keeps_the_primary_failure(
        self, commands: tuple[str, ...]
    ) -> None:
        """(e3) #1825 review: shells the classifier once misread as read-only.

        The exact refusal and exit code 1, through the real handler. Each
        command can write or run another program, so the fallback must not run.
        """
        primary = (
            *(line for i, c in enumerate(commands) for line in _codex_read(f"item_w{i}", c)),
            *CODEX_REFUSED_AS_OBSERVED,
        )
        agent = _ProductionHandlerAgent(attempts=(primary, (CLAUDE_SUCCEEDS,)), exit_codes=(1, 0))
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, repository = await _run(agent, phase, "exec-refusal-raw-after-write")

        assert agent.runners == [AgentRunner.CODEX]
        assert result.status == "failed"
        (row,) = (await _detail(repository, "exec-refusal-raw-after-write")).phases
        assert row.agent_provider != AgentProvider.CLAUDE

    @pytest.mark.parametrize(
        ("diff", "runs_driver", "provider"),
        [
            pytest.param("git diff", True, AgentProvider.CODEX, id="plain-diff-is-work"),
            pytest.param(
                "git --no-pager diff --no-ext-diff --no-textconv",
                False,
                AgentProvider.CLAUDE,
                id="constrained-diff-falls-back",
            ),
        ],
    )
    async def test_e4_a_driver_configured_before_the_attempt_is_the_attempts_write(
        self, tmp_path: Path, diff: str, runs_driver: bool, provider: AgentProvider
    ) -> None:
        """(e4) #1825 review round 2: `diff.external` set up OUTSIDE the attempt.

        The attempt itself installs nothing: it runs only `diff`, then the exact
        refusal and exit 1. A real repository shows what that diff does with
        the driver already configured, and the handler must agree: a diff that
        ran the driver wrote, so only codex runs and the phase records codex; a
        diff that switched drivers off changed nothing, so claude runs it.
        """
        marker = tmp_path / "driver-ran"
        driver = tmp_path / "touch-driver"
        driver.write_text(f"#!/bin/sh\ntouch {marker}\n")
        driver.chmod(0o755)
        repo = tmp_path / "repo"
        for args in (
            ("init", "-q", str(repo)),
            ("-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit",
             "-q", "--allow-empty", "-m", "base"),
            ("-C", str(repo), "config", "diff.external", str(driver)),
        ):  # fmt: skip
            subprocess.run(["git", *args], check=True)
        (repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "-C", str(repo), "add", "-N", "a.txt"], check=True)
        subprocess.run(diff, shell=True, cwd=repo, check=True, capture_output=True)
        assert marker.exists() is runs_driver, "the real diff did not behave as assumed"

        primary = (*_codex_read("item_d1", f"/bin/zsh -lc '{diff}'"), *CODEX_REFUSED_AS_OBSERVED)
        agent = _ProductionHandlerAgent(attempts=(primary, (CLAUDE_SUCCEEDS,)), exit_codes=(1, 0))
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, repository = await _run(agent, phase, "exec-refusal-preconfigured-driver")

        expected = [AgentRunner.CODEX] if runs_driver else [AgentRunner.CODEX, AgentRunner.CLAUDE]
        assert agent.runners == expected
        assert result.status == ("failed" if runs_driver else "completed"), result.error_message
        (row,) = (await _detail(repository, "exec-refusal-preconfigured-driver")).phases
        # A failed phase records no provider at all, only a completed one does.
        assert (row.agent_provider == AgentProvider.CLAUDE) is (provider == AgentProvider.CLAUDE)

    async def test_f_a_codex_refusal_after_work_does_not_fall_back(self) -> None:
        """(f) Codex edited a file, then was refused. No fallback: that was work."""
        agent = _RawJsonlAgent(attempts=(CODEX_REFUSED_AFTER_WORK, (CLAUDE_SUCCEEDS,)))
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, _repository = await _run(agent, phase, "exec-refusal-raw-after-work")

        assert result.status == "failed"
        assert agent.runners == [AgentRunner.CODEX], (
            "the fallback re-ran a phase whose primary had already done work"
        )
        assert "flagged for possible cybersecurity risk" in (result.error_message or "")

    @pytest.mark.parametrize("exit_code", [0, 1])
    async def test_g_a_refusal_after_a_hiccup_still_completes_on_the_fallback(
        self, exit_code: int
    ) -> None:
        """(g) An `error` codex went past, then the refusal: the refusal ended the turn.

        Found by verification of #1819: the parser kept the FIRST fault, so the
        hiccup hid the refusal, the phase died `unknown`, and the declared
        fallback never ran. Driven through the real `AgentExecutionHandler`,
        under both exit statuses the CLI could report.
        """
        agent = _ProductionHandlerAgent(
            attempts=(CODEX_HICCUP_THEN_REFUSED, (CLAUDE_SUCCEEDS,)), exit_codes=(exit_code, 0)
        )
        phase = _phase(AgentConfiguration(provider=AgentProvider.CODEX), CLAUDE_FALLBACK)

        result, repository = await _run(agent, phase, "exec-refusal-raw-after-hiccup")

        assert result.status == "completed", result.error_message
        assert agent.runners == [AgentRunner.CODEX, AgentRunner.CLAUDE], (
            "a hiccup before the refusal hid it, so the fallback never ran"
        )
        completed = _completed(repository)
        assert completed.agent_provider == AgentProvider.CLAUDE
        assert completed.agent_model == "claude-fallback-model"
        (row,) = (await _detail(repository, "exec-refusal-raw-after-hiccup")).phases
        assert (row.agent_provider, row.agent_model) == (
            AgentProvider.CLAUDE,
            "claude-fallback-model",
        )
