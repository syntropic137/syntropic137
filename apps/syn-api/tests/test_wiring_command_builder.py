"""Regression tests for provider-specific agent command construction.

These pin the DEFAULT sandbox level, which is currently full access
(``PhaseSandbox.FULL_ACCESS``).

That value is unchanged from before #1157, but it is no longer hardcoded: it is
now a per-phase declaration that merely defaults here. A phase wanting LESS
authority declares it and gets it today.

The default stays permissive as a stopgap. ``workspace-write`` was tried in
v0.28.0-beta.5 and broke every codex phase - the deliverable write under
``artifacts/output/`` was denied, so no artifact was produced and the phase
still reported ``completed`` (#1167). See test_codex_sandbox_least_privilege.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_api._wiring_agent_command import (
    PROMPT_ENV,
    _build_agent_command,
    _build_claude_command,
    _build_codex_command,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_shared.agents import CODEX_SANDBOX_FLAGS, PhaseSandbox

# Without this the whole module collects ZERO under CI's `pytest -m unit`, and
# the gate goes green having run none of it - including the argv pin that
# guards the #964 --tools change.
pytestmark = pytest.mark.unit

# Built from the typed mapping, never hand-written: the repository forbids a
# literal sandbox-disabling invocation (test_no_codex_sandbox_bypass, #1398).
if TYPE_CHECKING:
    from syn_domain.contexts.orchestration import AgentLaunch

FULL_ACCESS_FLAG = CODEX_SANDBOX_FLAGS[PhaseSandbox.FULL_ACCESS]


def _phase(
    provider: str, model: str = "gpt-5.6", tools: tuple[str, ...] = ("Read", "Bash")
) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="phase-1",
        name="Agent phase",
        order=1,
        agent_config=AgentConfiguration(
            provider=provider,
            model=model,
            allowed_tools=list(tools),
        ),
    )


def test_codex_command_passes_actual_model_and_reads_the_prompt_from_stdin() -> None:
    assert _build_codex_command("gpt-5.6") == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        FULL_ACCESS_FLAG,
        "--skip-git-repo-check",
        "--model",
        "gpt-5.6",
        "-",
    ]


def test_codex_command_omits_model_option_when_model_is_not_provided() -> None:
    assert _build_codex_command(None) == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        FULL_ACCESS_FLAG,
        "--skip-git-repo-check",
        "-",
    ]


def test_codex_command_omits_claude_alias_model() -> None:
    # AgentConfiguration.model defaults to "haiku" (a Claude alias); codex rejects
    # Claude model ids, so it must NOT be forwarded - codex uses its account default.
    assert "--model" not in _build_codex_command("haiku")
    assert "--model" not in _build_codex_command("sonnet")
    assert "--model" not in _build_codex_command("claude-opus-4")
    # a genuine codex / openai model id IS forwarded.
    assert _build_codex_command("o3")[-3:] == ["--model", "o3", "-"]


def test_codex_command_via_domain_default_model_forces_gpt_6_1_sol() -> None:
    """A codex phase that omits `model:` runs the codex default, FORCED.

    Regression history (#788, PR #795): an earlier fix synthesized
    `--model codex`, which is not a real model id. The default is now the
    platform alias `gpt-sol`, which must reach codex as the concrete slug
    `gpt-6.1-sol` - codex has no alias feature and would reject `gpt-sol`.
    """
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        _build_agent_config_from_phase,
    )
    from syn_shared.agents import AgentProvider, CodexModelAlias, ModelId

    phase_def = PhaseDefinition(
        phase_id="p1",
        name="p",
        order=1,
        prompt_template="x",
        provider=AgentProvider.CODEX,
    )
    cfg = _build_agent_config_from_phase(phase_def)
    assert cfg.model == CodexModelAlias.GPT_SOL

    cmd = _build_codex_command(cfg.model)
    assert cmd == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        FULL_ACCESS_FLAG,
        "--skip-git-repo-check",
        "--model",
        ModelId.GPT_6_1_SOL,
        "-",
    ]
    assert CodexModelAlias.GPT_SOL not in cmd


def test_agent_command_dispatches_on_provider_string() -> None:
    # Codex declares NO tools here: it cannot restrict by tool name, so a
    # declaration is now refused rather than dropped (#964).
    assert _harness(_build_agent_command(_phase("codex", tools=()), "x"))[0] == "codex"
    assert _harness(_build_agent_command(_phase("claude"), "x"))[0] == "claude"


def test_claude_command_argv_is_pinned() -> None:
    """Pins the argv, INCLUDING the #964 change from --allowedTools to --tools.

    It also pins that a claude alias reaches the CLI as its explicit id: the
    pinned CLI's own catalog sends `sonnet` to Sonnet 4.5 on some providers.

    This guard caught that change, which is what it is for. The change is
    deliberate: --allowedTools governs auto-approval and, beside
    --dangerously-skip-permissions on the same line, restricted nothing.

    `-p` takes no positional: the prompt arrives on stdin (#2355).
    """
    phase = _phase("claude", model="sonnet")
    expected = [
        "claude",
        "--model",
        "claude-sonnet-5-5",  # the alias is translated, never left to the CLI
        "--verbose",
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "-p",
        "--tools",
        "Read,Bash",
    ]

    assert _build_claude_command(phase) == expected


def _harness(launch: AgentLaunch) -> list[str]:
    """The harness argv inside the stdin wrapper: everything after its `$0`."""
    assert launch.argv[:2] == ("sh", "-c"), f"not launched through the wrapper: {launch.argv}"
    return list(launch.argv[4:])


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_no_argv_carries_the_prompt(provider: str) -> None:
    """#2355: a harness argv is readable through /proc by every workspace process.

    An agent cleaning up its own stray `pytest -m unit` with
    `ps aux | grep "[p]ytest -m unit" | ... | xargs kill` matched the claude CLI,
    whose argv carried the task prompt naming that command, and SIGTERMed it.
    """
    marker = "pytest -m unit and a unique marker 7f3c"
    tools = ("Read", "Bash") if provider == "claude" else ()
    launch = _build_agent_command(_phase(provider, tools=tools), f"Run {marker} then stop.")

    assert not [arg for arg in launch.argv if "7f3c" in arg], launch.argv
    assert marker in launch.environment[PROMPT_ENV]


def test_the_dispatched_prompt_carries_the_tool_grant() -> None:
    """_build_agent_command adds the harness-neutral grant; the builder does not."""
    phase = _phase("claude", model="sonnet")

    prompt = _build_agent_command(phase, "do the thing").environment[PROMPT_ENV]

    assert "do the thing" in prompt
    assert "Read" in prompt and "Bash" in prompt


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")
@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_the_wrapper_hands_the_prompt_to_stdin_and_nothing_else(
    provider: str, tmp_path: Path
) -> None:
    """Run the real wrapper with a stand-in harness that reports what it got.

    The harness must read the prompt, byte for byte, on stdin; its argv must be
    the flags only; and the variable that carried the prompt must not reach it
    or anything it starts.
    """
    prompt = "Line one with 'quotes', \"doubles\", $HOME, `ticks` and %s.\nLine two\n"
    fake = tmp_path / ("claude" if provider == "claude" else "codex")
    fake.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$0.argv"\n'
        'cat > "$0.stdin"\n'
        f'printf "%s" "${{{PROMPT_ENV}-UNSET}}" > "$0.env"\n'
    )
    fake.chmod(0o755)
    tools = ("Read",) if provider == "claude" else ()
    launch = _build_agent_command(_phase(provider, tools=tools), prompt)
    argv = [*launch.argv[:4], str(fake), *launch.argv[5:]]

    done = subprocess.run(
        argv, env={"PATH": os.environ["PATH"], **launch.environment}, timeout=30, check=False
    )

    assert done.returncode == 0
    received = Path(f"{fake}.stdin").read_text()
    assert received == launch.environment[PROMPT_ENV]
    assert received.startswith(prompt)
    assert "Line one" not in Path(f"{fake}.argv").read_text()
    assert Path(f"{fake}.env").read_text() == "UNSET"


def test_the_wrapper_exits_with_the_harness_status(tmp_path: Path) -> None:
    """A phase's exit status is the harness's, not the wrapper's or printf's."""
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\ncat > /dev/null\nexit 7\n")
    fake.chmod(0o755)
    launch = _build_agent_command(_phase("claude", tools=()), "x")
    argv = [*launch.argv[:4], str(fake), *launch.argv[5:]]

    done = subprocess.run(
        argv, env={"PATH": os.environ["PATH"], **launch.environment}, timeout=30, check=False
    )

    assert done.returncode == 7
