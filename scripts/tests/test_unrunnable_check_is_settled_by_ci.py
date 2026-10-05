"""A check the workspace cannot run is settled by CI on the same head SHA.

PRs #1562 and #1576 (2026-10-04) were held in draft by `reverify` when the only
open item was a docker-backed fitness test. The workspace has no docker, and
CI's Architectural Fitness job had already run that test green on the same
head. Each PR needed a human to override the verdict.

The rule now in every verify and reverify prompt: read CI's result for the
check, and accept it only when the run's `headSha` is the SHA under review. A
green run on an older head proves nothing. A pending run is waited on, with a
time limit. A failed run blocks, with a log excerpt.

These tests read the prompt as `POST /workflows` installs it, not the markdown
on disk, for the same reason as `test_implement_v2_repair_path.py`. The section
is copied into seven prompt files, so the main assertion is that all seven
installed copies are identical. Five verify prompts and two reverify prompts
that each wrote the rule their own way would drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)

pytestmark = pytest.mark.unit

_WORKFLOWS = Path(__file__).resolve().parents[2] / "workflows"

#: Every phase that certifies or blocks a candidate on gate results.
_GATING_PHASES = [
    ("sdlc/implement-v3", "Verify the change independently"),
    ("sdlc/implement-v3", "Confirm the fix closed what verification found"),
    ("sdlc/implement", "Verify the change independently"),
    ("sdlc/implement", "Confirm the fix closed what verification found"),
    ("custom/bake-opus", "Verify the change independently"),
    ("custom/bake-haiku", "Verify the change independently"),
    ("custom/bake-sonnet", "Verify the change independently"),
]

_HEADING = "## A check this workspace cannot run is settled by CI on the same head SHA"


_GATEWAY = "ci/fitness/infrastructure/test_gateway_bind.py"

#: Architectural Fitness on run 37247898846 (PR #1587, head 9b2f098a), green.
#: The repo's `addopts` adds `-q` to the job's `-v`: one progress line per file.
_GREEN_CI_LOG = f"""\
uv run pytest ci/fitness/ -v --tb=short -m architecture
ci/fitness/infrastructure/test_compose_env_forwarding.py ............... [ 92%]
...............                                                          [ 93%]
{_GATEWAY} ...                       [ 93%]
ci/fitness/infrastructure/test_phase_definition_roundtrip.py .           [ 93%]
=========================== short test summary info ============================
SKIPPED [1] ci/fitness/event_sourcing/test_event_ownership.py:86: got empty parameter set
========== 990 passed, 5 skipped, 21 deselected, 2 warnings in 44.88s ==========
"""

#: The same job had the gateway tests skipped: green, and settles nothing.
_SKIPPED_CI_LOG = f"""\
{_GATEWAY} sss                       [ 93%]
=========================== short test summary info ============================
SKIPPED [1] {_GATEWAY}:40: docker not available
"""


def _prompt_grep(section: str, log: str) -> list[str]:
    """Run the prompt's own `--log | grep` over a CI log, as the agent would."""
    found = re.search(r"--log \| grep (-F )?'([^']+)'", section)
    assert found, "the section gives no grep over the job log"
    pattern = found.group(2).replace("<test-file>", _GATEWAY)
    return [line for line in log.splitlines() if pattern in line]


def _installed_section(workflow: str, phase_name: str) -> str:
    """The section as installed, with whitespace collapsed so a re-flow is not a failure."""
    command = build_command_from_definition(
        WorkflowDefinition.from_file(_WORKFLOWS / workflow / "workflow.yaml")
    )
    (phase,) = [p for p in command.phases if p.name == phase_name]
    prompt = phase.prompt_template or ""
    start = prompt.find(_HEADING)
    assert start >= 0, f"{workflow} {phase_name!r} installs without the CI-settles-it section"
    end = prompt.find("\n## ", start + len(_HEADING))
    return re.sub(r"\s+", " ", prompt[start : end if end >= 0 else None])


@pytest.fixture(scope="module")
def sections() -> dict[tuple[str, str], str]:
    return {key: _installed_section(*key) for key in _GATING_PHASES}


def test_every_gating_phase_carries_the_same_rule(
    sections: dict[tuple[str, str], str],
) -> None:
    reference = sections[_GATING_PHASES[0]]
    drifted = [key for key, text in sections.items() if text != reference]
    assert not drifted, f"these copies differ from {_GATING_PHASES[0]}: {drifted}"


@pytest.mark.parametrize("key", _GATING_PHASES, ids=lambda k: f"{k[0]}:{k[1][:7]}")
class TestTheRule:
    def test_both_shas_are_printed_and_must_match(
        self, sections: dict[tuple[str, str], str], key: tuple[str, str]
    ) -> None:
        section = sections[key]
        assert "git rev-parse HEAD" in section
        assert "gh run view <run-id> --json headSha,status,conclusion" in section
        assert "both must be the same full SHA" in section
        assert "A green CI run on an older head proves nothing" in section

    def test_it_reads_the_checks_for_the_pr(
        self, sections: dict[tuple[str, str], str], key: tuple[str, str]
    ) -> None:
        assert "gh pr checks <n> --json name,state,link" in sections[key]

    def test_a_pass_on_this_sha_is_not_a_blocker(
        self, sections: dict[tuple[str, str], str], key: tuple[str, str]
    ) -> None:
        section = sections[key]
        assert "the check is closed. It is not a blocker" in section
        # A green job that deselected the test did not run it (#1562's -m architecture).
        assert "the number of dots must equal that count" in section
        assert "uv run pytest --collect-only -q -m <the job's marker> <test-file>" in section

    def test_its_grep_finds_the_evidence_in_a_real_ci_log(
        self, sections: dict[tuple[str, str], str], key: tuple[str, str]
    ) -> None:
        # PR #1587's first draft grepped for `<test-file>::` and wanted `PASSED`,
        # which `-q` never prints, so it could not close a check CI had passed.
        matched = _prompt_grep(sections[key], _GREEN_CI_LOG)
        assert any(_GATEWAY + " ..." in line for line in matched), matched

    def test_its_grep_surfaces_a_skip_of_the_file(
        self, sections: dict[tuple[str, str], str], key: tuple[str, str]
    ) -> None:
        matched = _prompt_grep(sections[key], _SKIPPED_CI_LOG)
        assert any(line.startswith("SKIPPED") for line in matched), matched
        assert "a `SKIPPED` line naming the file all mean the check was not run" in sections[key]

    def test_a_pending_run_is_waited_on_with_a_bound(
        self, sections: dict[tuple[str, str], str], key: tuple[str, str]
    ) -> None:
        assert re.search(r"timeout \d+m gh pr checks <n> --watch", sections[key])

    def test_a_failed_run_blocks_with_its_log(
        self, sections: dict[tuple[str, str], str], key: tuple[str, str]
    ) -> None:
        section = sections[key]
        assert "it IS a blocker. Put it under BLOCKING" in section
        assert "gh run view --job <job-id> --log-failed" in section
