"""``ToolName`` is a claim about another program, so check it against it (#1207).

The vocabulary is a hand-maintained list of the Claude CLI's built-in tools.
Nothing verified it against the CLI, so it drifted: it carried ``LS``,
``TodoRead``, ``TodoWrite`` and ``MultiEdit``, which the CLI does not grant, and
lacked ``Skill``, which it does. A phase declaring one of the four was accepted
here and then ran with NO tools - applied to nothing, which is worse than being
either honoured or refused, because it is silent.

A list like that cannot be kept correct by review. It goes stale the moment
Anthropic ships a release, and the staleness is invisible until a phase quietly
loses its tools in production. The only durable fix is to ask the CLI.

HOW THIS ASKS, AND WHY IT COSTS NOTHING. The CLI emits its ``init`` line -
which contains the tool grant it resolved from ``--tools`` - BEFORE it
authenticates. Verified: with a deliberately invalid key the ``init`` line still
arrives, and the 401 only appears on the line after it. So the probe needs no
credentials and spends no tokens, and it deliberately passes an invalid model so
that no inference can happen even if a key is present.

It builds its argv with the REAL command builder rather than a copy, so a change
to how ``allowed_tools`` becomes ``--tools`` is covered here too. That matters:
the flag is variadic and greedy, and the ordering it depends on has already
broken once.

WHERE THIS RUNS. Anywhere Docker can pull the pinned image. It is marked
``integration``, which CI runs as a job of its own. It SKIPS - loudly, naming
the reason - where Docker is absent, which includes every agent workspace
container. A skip here is a gap, not a pass: this repo has already shipped a
green gate that checked nothing (docs/retrospectives/2026-08-17-green-checks-
that-check-nothing.md), so read a skipped run as "unverified".
"""

from __future__ import annotations

import shutil
import subprocess
import threading

import pytest
from pydantic import BaseModel, ConfigDict

from syn_api._wiring import _build_claude_command
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE
from syn_shared.tools import ToolName, canonical_tool_name

#: No inference must ever happen: the grant is resolved locally, and a model the
#: API does not know cannot be billed even if a real key is in the environment.
_UNBILLABLE_MODEL = "definitely-not-a-model"

_PROBE_TIMEOUT_SECONDS = 180


class _CliInitLine(BaseModel):
    """The ``system``/``init`` line of the CLI's ``stream-json`` output.

    Parsed into a model rather than read out of a raw mapping so the two fields
    this check depends on are named and typed in one place. Unknown keys are
    ignored: the CLI adds fields to this line freely and none of them are ours.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
    subtype: str = ""
    tools: tuple[str, ...] = ()
    claude_code_version: str = ""


def _probe_argv(declared: str) -> list[str]:
    """The exact argv production would run for a phase declaring ``declared``.

    Goes through ``_build_claude_command`` on purpose. A test that hand-wrote
    ``["claude", "--tools", name]`` would keep passing while the real builder
    emitted something the CLI ignores - which is the bug class this file exists
    to close, one level up.
    """
    phase = ExecutablePhase(
        phase_id="tool-vocabulary-probe",
        name="Tool vocabulary probe",
        order=1,
        agent_config=AgentConfiguration(model=_UNBILLABLE_MODEL, allowed_tools=(declared,)),
    )
    return _build_claude_command(phase, "say ok")


def _granted_tools(declared: str) -> tuple[str, ...]:
    """The tools the CLI in the pinned image actually grants for ``declared``.

    Returns the grant, which is empty when the CLI does not recognise the name -
    the failure mode #1207 is about. Raises if no ``init`` line arrives at all,
    because a broken probe reporting an empty grant looks exactly like the
    defect it is meant to detect.

    WHY IT KILLS THE PROCESS INSTEAD OF WAITING FOR IT. The grant is on the
    first line and the run has nothing left to contribute after it: the invalid
    key then fails authentication, and the CLI retries that ten times with
    backoff. Measured while writing this - waiting for exit took over 180
    seconds per tool and timed out. Reading the line we came for and stopping
    turns the whole matrix into seconds.
    """
    process = subprocess.Popen(  # fixed argv, no shell
        [
            "docker",
            "run",
            "--rm",
            # An invalid key, not an absent one: the CLI reads the grant out
            # before it authenticates, and a key that is present-but-wrong
            # keeps it from trying to open an interactive login.
            "--env",
            "ANTHROPIC_API_KEY=sk-ant-invalid-probe",
            "--entrypoint",
            "claude",
            DEFAULT_WORKSPACE_IMAGE,
            *_probe_argv(declared)[1:],  # argv[0] is "claude", now the entrypoint
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # A hard stop, because the loop below blocks on a line that a wedged
    # container would never send.
    watchdog = threading.Timer(_PROBE_TIMEOUT_SECONDS, process.kill)
    watchdog.start()
    seen: list[str] = []
    try:
        for line in process.stdout or ():
            seen.append(line)
            if not line.startswith("{"):
                continue
            try:
                parsed = _CliInitLine.model_validate_json(line)
            except ValueError:
                continue
            if parsed.type == "system" and parsed.subtype == "init":
                return parsed.tools
    finally:
        watchdog.cancel()
        process.kill()
        process.wait(timeout=30)
    msg = (
        f"no init line for --tools {declared}; the probe is broken, not the "
        f"vocabulary.\nsaw: {''.join(seen)[:800]}"
    )
    raise AssertionError(msg)


def _image_is_available() -> bool:
    if shutil.which("docker") is None:
        return False
    pulled = subprocess.run(  # fixed argv, no shell
        ["docker", "image", "inspect", DEFAULT_WORKSPACE_IMAGE],
        capture_output=True,
        check=False,
    )
    if pulled.returncode == 0:
        return True
    return (
        subprocess.run(  # fixed argv, no shell
            ["docker", "pull", "--quiet", DEFAULT_WORKSPACE_IMAGE],
            capture_output=True,
            check=False,
            timeout=_PROBE_TIMEOUT_SECONDS,
        ).returncode
        == 0
    )


needs_pinned_image = pytest.mark.skipif(
    not _image_is_available(),
    reason=(
        f"needs Docker and the pinned workspace image {DEFAULT_WORKSPACE_IMAGE}. "
        "SKIPPED means the vocabulary was NOT checked against the CLI on this "
        "run - treat it as unverified, not as a pass (#1207)."
    ),
)


@pytest.mark.integration
@needs_pinned_image
class TestTheVocabularyMatchesThePinnedCli:
    """Every accepted name must be granted, and granted exactly once."""

    @pytest.mark.parametrize("tool", list(ToolName), ids=lambda t: t.value)
    def test_an_accepted_name_is_granted_exactly_once(self, tool: ToolName) -> None:
        granted = _granted_tools(tool.value)

        assert granted == (tool.value,), (
            f"the CLI in {DEFAULT_WORKSPACE_IMAGE} resolved --tools "
            f"{tool.value} to {list(granted)}. An empty grant means a phase "
            f"declaring {tool.value} runs with NO tools; anything else means "
            "the name is not the one-to-one grant this vocabulary claims."
        )

    @pytest.mark.parametrize("ungranted", ["LS", "TodoRead", "TodoWrite", "MultiEdit"])
    def test_the_names_removed_in_1207_really_are_ungranted(self, ungranted: str) -> None:
        """The negative control, without which the check above proves little.

        If the CLI granted these after all, removing them from the vocabulary
        was a regression and this file should say so rather than stay quiet.
        """
        assert _granted_tools(ungranted) == (), (
            f"{ungranted} IS granted by the CLI in {DEFAULT_WORKSPACE_IMAGE}, so "
            "removing it from ToolName in #1207 took away a real capability"
        )


@pytest.mark.unit
class TestAnInvalidNameIsRefusedBeforeAnyContainerStarts:
    """The other half, and the half that needs no image.

    Refusing a bad name is only worth anything if it happens before the
    workspace is provisioned and paid for. This asserts the refusal sits on the
    path that BUILDS the command, so no container is ever started for a phase
    whose declaration cannot be honoured.
    """

    @pytest.mark.parametrize("ungranted", ["LS", "TodoRead", "TodoWrite", "MultiEdit", "git"])
    def test_the_vocabulary_refuses_it(self, ungranted: str) -> None:
        assert canonical_tool_name(ungranted) is None

    @pytest.mark.parametrize("ungranted", ["LS", "TodoRead", "TodoWrite", "MultiEdit", "git"])
    def test_no_argv_can_be_built_for_it(self, ungranted: str) -> None:
        """No argv means no ``docker run``: the refusal precedes provisioning."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            _build_agent_config_from_phase,
        )
        from syn_shared.tools import UnsupportedToolNameError

        class _StoredPhase:
            phase_id = "build-and-delegate"
            model = "haiku"
            provider = None
            allow_delegation = False
            sandbox = None
            allowed_tools = (ungranted,)

        with pytest.raises(UnsupportedToolNameError):
            _build_agent_config_from_phase(_StoredPhase())

    def test_a_granted_name_does_reach_the_tools_flag(self) -> None:
        """Negative control: the builder still emits what the probe would read."""
        argv = _probe_argv(ToolName.SKILL.value)

        assert argv[-2:] == ["--tools", "Skill"]
