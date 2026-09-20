"""#1381: a real SIGTERM at the api must not take a running phase's work with it.

THE HOP UNDER TEST IS THE SIGNAL. Recreating the api container is the ordinary
deploy, and it is delivered as SIGTERM: docker sends it, waits out
`stop_grace_period`, and only then kills. Everything downstream of that signal
was already in place before this change - #1184 knows how to push a dying
workspace's work somewhere durable, #1231 wired it into both terminal paths -
and none of it ran, because `CancelledError` is a `BaseException` and
`WorkflowExecutionProcessor.run` caught `Exception`. Every deploy therefore
destroyed whatever the running phase was holding, which is why deploying had to
wait for a full drain first.

SO THIS DRIVES AN ACTUAL SIGNAL AT AN ACTUAL PROCESS. A test that called
`shutdown()` directly would prove the plumbing below the signal and nothing
about the signal itself; a test that mocked the shutdown would prove neither.
The child process below runs the REAL `BackgroundWorkflowDispatcher`, the REAL
`lifecycle._shutdown_subscriptions`, the REAL processor `run()` loop and REAL
git, and the parent asserts what the ORIGIN repository holds after the child has
exited - the only vantage point from which "the work survived the process" can
be a true statement at all.

SIGTERM, NOT SIGKILL, and the distinction is the point rather than a gap: a
SIGTERM runs Python, so a process can save what it is holding; a SIGKILL or an
OOM runs none, and nothing in-process can preserve anything against it. What
survives a SIGKILL is only what was already durable when it landed. `docker
stop` and `docker compose up -d` both send SIGTERM and wait, which is why the
deploy this issue is about is the case a SIGTERM path covers.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _BRANCH,
    _Clone,
    _REPO,
)

pytestmark = [pytest.mark.unit]

#: The execution the deploy interrupts, and the ref its work has to land on.
_EXECUTION_ID = "exec-1381-sigterm-mid-phase"
_PHASE_ID = "implement"
_QUARANTINE_REF = f"refs/syn/lost/{_EXECUTION_ID}/{_PHASE_ID}"

#: Where the domain-side harness lives. The child needs the same processor
#: wiring, git-backed workspace and never-returning agent this repository
#: already tests the interruption with, and duplicating it here would let the
#: two drift into testing different things.
_DOMAIN_TESTS = Path(__file__).resolve().parents[3] / "packages" / "syn-domain" / "tests"

#: What the child does, in full. A separate process because a signal is
#: delivered to a process: `os.kill(os.getpid(), SIGTERM)` inside pytest would
#: hit pytest's own handlers, and nothing about the run would resemble a
#: container being replaced.
_CHILD = '''
"""One api process running one execution, waiting to be SIGTERMed."""

import asyncio
import json
import signal
import sys
from pathlib import Path

root, ready_file, domain_tests = (Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
sys.path.insert(0, domain_tests)

from contexts.workflows.execute_workflow.test_1381_a_restart_keeps_the_work import (
    watched_workspaces,
)
from contexts.workflows.execute_workflow.test_processor_smoke import (
    FakeWorkflowRepository,
    _make_processor,
    _stored_template,
)
from syn_api._wiring import BackgroundWorkflowDispatcher
from syn_api.services.lifecycle import LifecycleState, _shutdown_subscriptions
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _clone_repository,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

WORKFLOW = """
id: wf-1381-sigterm
name: Interrupted By A Deploy
requires_repos: false
phases:
  - id: implement
    name: Implement
    order: 1
    prompt_template: make the change
"""


async def main() -> int:
    clone = _clone_repository(root)
    running = asyncio.Event()
    workspaces = watched_workspaces(clone)
    processor = _make_processor(
        FakeAgentExecutionHandler.still_running(running),
        workspace_service=workspaces,
    )
    template = _stored_template(WORKFLOW)
    dispatcher = BackgroundWorkflowDispatcher(
        ExecuteWorkflowHandler(
            processor=processor,
            workflow_repository=FakeWorkflowRepository(template),
        )
    )

    # The real lifecycle shutdown, reached the way uvicorn reaches it: on the
    # signal, not by anyone calling it.
    state = LifecycleState()
    state.workflow_dispatcher = dispatcher
    shutdown_returned = asyncio.Event()

    async def _on_sigterm() -> None:
        await _shutdown_subscriptions(state)
        shutdown_returned.set()

    asyncio.get_running_loop().add_signal_handler(
        signal.SIGTERM, lambda: asyncio.ensure_future(_on_sigterm())
    )

    await dispatcher.run_workflow(template.id, {}, execution_id="%(execution_id)s")
    await asyncio.wait_for(running.wait(), timeout=120)

    # The hour of work, made where production makes it: inside the phase, after
    # it started, pushed nowhere.
    lost = clone.commit("state_machine.py", "an hour of work, and then a deploy\\n")
    (clone.path / "half_written.py").write_text("def drain():  # cut off by the deploy\\n")
    ready_file.write_text(json.dumps({"commit": lost}))

    await asyncio.wait_for(shutdown_returned.wait(), timeout=300)
    (root / "done.json").write_text(
        json.dumps(
            {
                "opened": workspaces.open_contexts,
                "closed": workspaces.closed_contexts,
            }
        )
    )
    return 0


sys.exit(asyncio.run(main()))
'''


def _start_child(tmp_path: Path) -> tuple[subprocess.Popen[str], Path, str]:
    """Start the child and return once its phase is running and holding work.

    Returns the process, the run's root, and the commit that now exists in no
    remote - the thing the deploy has to stop costing.
    """
    script = tmp_path / "one_api_process.py"
    script.write_text(_CHILD % {"execution_id": _EXECUTION_ID})
    root = tmp_path / "run"
    root.mkdir()
    ready = tmp_path / "ready.json"

    child = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script), str(root), str(ready), str(_DOMAIN_TESTS)],
        env={**os.environ, "APP_ENVIRONMENT": "test", "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if ready.exists():
            return child, root, json.loads(ready.read_text())["commit"]
        if child.poll() is not None:
            pytest.fail(f"the child died before its phase ran:\n{child.communicate()[0]}")
        time.sleep(0.1)
    child.kill()
    pytest.fail(f"the child never started a phase:\n{child.communicate()[0]}")


def test_a_real_sigterm_leaves_the_phases_work_in_the_origin(tmp_path: Path) -> None:
    """THE ISSUE, end to end: signal a running api, then go looking for the work.

    Every assertion is read out of the ORIGIN after the child has exited. That
    is deliberate and it is the whole design of this test: the process that made
    the commit is gone, its workspace is gone, and if the commit is not in the
    origin then it does not exist anywhere - which is exactly what every deploy
    used to do to it.
    """
    child, root, lost = _start_child(tmp_path)
    clone = _Clone(root, _REPO)
    branch_head_before = clone.origin_refs()[f"refs/heads/{_BRANCH}"]

    child.send_signal(signal.SIGTERM)
    output = child.communicate(timeout=300)[0]

    assert child.returncode == 0, f"the api process did not shut down cleanly:\n{output}"
    assert clone.reachable_in_origin(lost, _QUARANTINE_REF), (
        "SIGTERM destroyed the commit the running phase had made - it is "
        f"reachable from no ref in the origin. #1381 itself.\n{output}"
    )
    assert (
        clone.origin_git("show", f"{_QUARANTINE_REF}:half_written.py")
        == "def drain():  # cut off by the deploy"
    ), f"the file the agent was editing when the signal arrived did not survive\n{output}"
    assert clone.origin_refs()[f"refs/heads/{_BRANCH}"] == branch_head_before, (
        "half-finished work was published onto the branch under review"
    )


def test_the_api_does_not_exit_until_the_work_is_out(tmp_path: Path) -> None:
    """The ORDER is the guarantee, and the shutdown owns it.

    `shutdown()` cancels every task and then awaits them. Dropping the await -
    cancel and return, which is what a fire-and-forget shutdown looks like and
    reads as correct - would let the process exit while the push was still in
    flight, and the work would be lost exactly as often as the race lost. So
    what is asserted is that by the time the lifecycle shutdown had RETURNED,
    the work was already in the origin and every workspace context had been
    closed: the child writes that file only after `_shutdown_subscriptions`
    returns, and the parent reads the origin only after the child has exited.
    """
    child, root, lost = _start_child(tmp_path)
    clone = _Clone(root, _REPO)

    child.send_signal(signal.SIGTERM)
    output = child.communicate(timeout=300)[0]

    assert child.returncode == 0, f"the api process did not shut down cleanly:\n{output}"
    done = root / "done.json"
    assert done.exists(), (
        f"the lifecycle shutdown never returned, so the process exited on the "
        f"signal alone and nothing was waited for\n{output}"
    )
    accounted = json.loads(done.read_text())
    assert accounted["opened"] == 1, f"the phase never got a workspace\n{output}"
    assert accounted["closed"] == 1, (
        "the interrupted phase's workspace context was never exited, so the api "
        f"exited leaving its containers behind\n{output}"
    )
    assert clone.reachable_in_origin(lost, _QUARANTINE_REF), (
        f"the shutdown returned before the work was durable\n{output}"
    )
