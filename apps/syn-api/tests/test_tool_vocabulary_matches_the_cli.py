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

WHY THIS IS IN TWO HALVES, AND WHY THE SPLIT IS THE POINT (review of #1210).
The first version of this file put the whole check behind ``integration``.
``.github/workflows/ci.yml`` runs integration tests only on schedules, manual
dispatch, pushes to ``main``, and PRs based on ``release`` - so on a PR into
``main``, which is every feature PR in this repo, the check was SKIPPED. It
could only report vocabulary drift after the merge it existed to gate. A check
that runs only after the merge it gates is a post-mortem.

So the halves are:

``TestTheVocabularyIsTheOneThatWasObserved`` - UNIT, no Docker, runs on every
PR. It pins ``ToolName`` to ``tool_vocabulary_record.json``, a committed record
of an actual probe. Editing the enum without re-probing and updating that record
fails the PR. This half is deliberately strong enough to catch drift on its own.

``TestTheVocabularyMatchesThePinnedCli`` - INTEGRATION, needs Docker. It checks
the record itself against the CLI in the pinned image, which is the only thing
that can catch the record going stale when Anthropic ships a release. It SKIPS -
loudly, naming the reason - where Docker is absent, which includes every agent
workspace container. A skip here is a gap, not a pass: this repo has already
shipped a green gate that checked nothing (docs/retrospectives/2026-08-17-green-
checks-that-check-nothing.md), so read a skipped run as "unverified".

Together: the unit half says "the enum is what we wrote down", the integration
half says "what we wrote down is what the CLI does". Neither alone is the check;
only the second needs an image, so only the second is allowed to skip.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel, ConfigDict

from syn_api._wiring_agent_command import _build_claude_command
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE
from syn_shared.tools import ToolName, canonical_tool_name

if TYPE_CHECKING:
    from collections.abc import Iterator

#: No inference must ever happen: the grant is resolved locally, and a model the
#: API does not know cannot be billed even if a real key is in the environment.
_UNBILLABLE_MODEL = "definitely-not-a-model"

_PROBE_TIMEOUT_SECONDS = 180

#: Pulling the pinned image is retried, because a registry that is slow once is
#: not evidence about the vocabulary (#2053). The pauses sit BETWEEN attempts,
#: so the whole pull is bounded at 3 x 180 s + 15 s + 45 s = 10 minutes. No
#: jitter: one runner pulls one image, so there is no herd to spread out.
_PULL_ATTEMPTS = 3
_PULL_BACKOFF_SECONDS = (15, 45)

_RECORD_PATH = Path(__file__).parent / "tool_vocabulary_record.json"


class _ObservedVocabulary(BaseModel):
    """What a probe of the CLI actually returned, committed so it can be diffed.

    This exists so the unit half has something to compare ``ToolName`` against
    that is NOT ``ToolName``. A test that derived its expectation from the enum
    would pass for every possible enum, which is the shape of bug this whole
    file is about.

    ``provenance`` is a field rather than a comment because JSON has no
    comments and the caveat is load-bearing: it records WHERE the observation
    was made, and the answer is not always "the pinned image".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The CLI version the ``granted``/``ungranted`` lists were read from.
    cli_version: str
    #: What the pinned image's Dockerfile ARG selects. Read, not probed - the
    #: integration half is what turns this into a verified claim.
    pinned_image_cli_version: str
    provenance: str
    #: Names the CLI resolved to exactly themselves.
    granted: tuple[str, ...]
    #: Names the CLI resolved to an empty grant. The negative control: without
    #: it, "the vocabulary matches" is satisfied by a CLI that grants nothing.
    ungranted: tuple[str, ...]


_RECORD = _ObservedVocabulary.model_validate_json(_RECORD_PATH.read_text(encoding="utf-8"))


class _CliInitLine(BaseModel):
    """The ``system``/``init`` line of the CLI's ``stream-json`` output.

    Parsed into a model rather than read out of a raw mapping so the fields
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


def _probe_init_line(declared: str) -> _CliInitLine:
    """What the CLI in the pinned image reports when asked for ``declared``.

    Returns the whole ``init`` line rather than just its grant, because the
    version on it is part of what this file checks: a grant is only evidence
    about the CLI that produced it.

    The grant is empty when the CLI does not recognise the name - the failure
    mode #1207 is about. Raises if no ``init`` line arrives at all, because a
    broken probe reporting an empty grant looks exactly like the defect it is
    meant to detect.

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
                return parsed
    finally:
        watchdog.cancel()
        process.kill()
        process.wait(timeout=30)
    msg = (
        f"no init line for --tools {declared}; the probe is broken, not the "
        f"vocabulary.\nsaw: {''.join(seen)[:800]}"
    )
    raise AssertionError(msg)


@dataclass(frozen=True)
class _ImageAvailable:
    """The pinned image is in the local Docker store."""


@dataclass(frozen=True)
class _NoDocker:
    """There is no ``docker`` binary, so nothing here can be checked."""


@dataclass(frozen=True)
class _PullFailed:
    """Docker is present and every attempt to pull the pinned image failed."""

    attempts: int
    last_error: str


def _pull_error(argv: list[str]) -> str | None:
    """Run one pull; ``None`` if it succeeded, otherwise what went wrong."""
    try:
        pulled = subprocess.run(  # fixed argv, no shell
            argv,
            capture_output=True,
            check=False,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"timed out after {_PROBE_TIMEOUT_SECONDS} s"
    if pulled.returncode == 0:
        return None
    stderr = pulled.stderr.decode(errors="replace").strip()
    return f"exit {pulled.returncode}: {stderr or '(no stderr)'}"


@dataclass
class _AvailabilityMemo:
    """Whether the pinned image has already been found in this session."""

    available: bool = False


_MEMO = _AvailabilityMemo()


def _pinned_image_availability() -> _ImageAvailable | _NoDocker | _PullFailed:
    """Whether the pinned image can be probed, pulling it if it is absent.

    Only success is remembered for the session. A failure is NOT: running out of
    attempts says the registry was down for ten minutes, not that it always
    will be, so the next test that needs the image tries again (#2053). CI runs
    the integration half with ``-x``, so it stops at the first named failure
    rather than paying that bound once per parametrized case.
    """
    if _MEMO.available:
        return _ImageAvailable()
    if shutil.which("docker") is None:
        return _NoDocker()
    inspected = subprocess.run(  # fixed argv, no shell
        ["docker", "image", "inspect", DEFAULT_WORKSPACE_IMAGE],
        capture_output=True,
        check=False,
    )
    if inspected.returncode == 0:
        _MEMO.available = True
        return _ImageAvailable()
    last_error = ""
    for attempt in range(_PULL_ATTEMPTS):
        if attempt:
            time.sleep(_PULL_BACKOFF_SECONDS[attempt - 1])
        error = _pull_error(["docker", "pull", "--quiet", DEFAULT_WORKSPACE_IMAGE])
        if error is None:
            _MEMO.available = True
            return _ImageAvailable()
        last_error = error
    return _PullFailed(attempts=_PULL_ATTEMPTS, last_error=last_error)


def _require_pinned_image() -> str:
    """The pinned image, or a loud skip when there is no Docker, or a failure.

    Only a missing ``docker`` binary skips. A registry that will not serve the
    image FAILS, with one named message rather than a subprocess traceback:
    turning it into a skip would report "unverified" as if nothing were wrong,
    on exactly the runners that are supposed to verify (#2053).
    """
    availability = _pinned_image_availability()
    match availability:
        case _ImageAvailable():
            return DEFAULT_WORKSPACE_IMAGE
        case _NoDocker():
            pytest.skip(
                f"needs Docker and the pinned workspace image {DEFAULT_WORKSPACE_IMAGE}. "
                "SKIPPED means the vocabulary was NOT checked against the CLI on this "
                "run - treat it as unverified, not as a pass (#1207)."
            )
        case _PullFailed(attempts=attempts, last_error=last_error):
            pytest.fail(
                f"pinned image {DEFAULT_WORKSPACE_IMAGE} could not be pulled after "
                f"{attempts} attempts: {last_error}",
                pytrace=False,
            )


@pytest.fixture
def pinned_image() -> str:
    """The pinned image to probe; see ``_require_pinned_image`` for the rest.

    A FIXTURE, not a module-level ``skipif``, and that is not a style choice.
    The availability check shells out to ``docker image inspect`` and then to
    ``docker pull``, so evaluating it at import time ran a multi-gigabyte pull
    during COLLECTION of every pytest invocation - including ``pytest -m unit``,
    which deselects every test here and on a machine with Docker (every CI
    runner, most dev machines) paid for the pull anyway. Deferring it to the
    tests that need it means the unit half touches Docker never.
    """
    return _require_pinned_image()


@pytest.mark.unit
class TestTheVocabularyIsTheOneThatWasObserved:
    """The half that gates a PR, because it needs no image (review of #1210).

    ``tool_vocabulary_record.json`` is a committed record of an actual probe.
    Comparing ``ToolName`` against it means adding or removing a name is a
    two-file change: the enum, and the evidence for it. That is the whole
    mechanism - it makes "where did this name come from?" answerable, which is
    the question nobody could answer about ``LS``.

    What makes this fail: editing ``ToolName`` alone. What makes it fail for
    the RIGHT reason: the integration half below, which is what stops the
    record from being updated to match a wrong enum.
    """

    def test_the_enum_is_exactly_the_observed_grant(self) -> None:
        assert {tool.value for tool in ToolName} == set(_RECORD.granted), (
            f"ToolName and {_RECORD_PATH.name} disagree. The record is a probe "
            f"of CLI {_RECORD.cli_version}; if the CLI changed, re-probe and "
            "update the record (TestTheVocabularyMatchesThePinnedCli does the "
            "probing). Do NOT edit the record to match the enum - that is how "
            "LS, TodoRead, TodoWrite and MultiEdit got in (#1207)."
        )

    @pytest.mark.parametrize("ungranted", _RECORD.ungranted)
    def test_a_name_observed_ungranted_is_refused(self, ungranted: str) -> None:
        """The negative control, without which the check above is half a check.

        "The enum equals the granted list" is also satisfied by a record whose
        granted list is wrong. These are the names a probe watched resolve to
        an empty grant, so accepting one means shipping a phase that runs with
        no tools.
        """
        assert canonical_tool_name(ungranted) is None, (
            f"{ungranted} is accepted by the vocabulary, but {_RECORD_PATH.name} "
            f"records CLI {_RECORD.cli_version} resolving it to an empty grant. "
            "A phase declaring it would run with NO tools (#1207)."
        )


@pytest.mark.unit
class TestAnInvalidNameIsRefusedBeforeAnyContainerStarts:
    """Refusal has to happen before the workspace is provisioned and paid for.

    This asserts the refusal sits on the path that BUILDS the command, so no
    container is ever started for a phase whose declaration cannot be honoured.
    """

    @pytest.mark.parametrize("ungranted", [*_RECORD.ungranted, "git"])
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


@pytest.mark.integration
class TestTheVocabularyMatchesThePinnedCli:
    """The half that checks the RECORD against reality. Needs Docker.

    Every assertion here is about ``tool_vocabulary_record.json``, not about
    ``ToolName`` - the unit half already ties those together. So this is the
    thing that catches Anthropic changing the CLI under a record that still
    looks tidy.
    """

    @pytest.mark.parametrize("tool", _RECORD.granted)
    def test_a_recorded_grant_is_still_granted_exactly_once(
        self, tool: str, pinned_image: str
    ) -> None:
        granted = _probe_init_line(tool).tools

        assert granted == (tool,), (
            f"the CLI in {pinned_image} resolved --tools {tool} to "
            f"{list(granted)}. An empty grant means a phase declaring {tool} "
            "runs with NO tools; anything else means the name is not the "
            "one-to-one grant this vocabulary claims."
        )

    @pytest.mark.parametrize("ungranted", _RECORD.ungranted)
    def test_a_recorded_non_grant_is_still_not_granted(
        self, ungranted: str, pinned_image: str
    ) -> None:
        """If the CLI grants these after all, removing them was a regression."""
        assert _probe_init_line(ungranted).tools == (), (
            f"{ungranted} IS granted by the CLI in {pinned_image}, so removing "
            "it from ToolName in #1207 took away a real capability"
        )

    def test_the_record_names_the_cli_version_this_image_carries(self, pinned_image: str) -> None:
        """A grant is only evidence about the CLI that produced it.

        Bumping the pinned digest silently re-points every assertion above at a
        different program while the record still cites the old version. That is
        the same staleness as the manifest #1207 came from, one level up, so it
        is checked rather than trusted.
        """
        reported = _probe_init_line(ToolName.READ.value).claude_code_version

        assert reported == _RECORD.pinned_image_cli_version, (
            f"{pinned_image} carries claude {reported}, but "
            f"{_RECORD_PATH.name} cites {_RECORD.pinned_image_cli_version}. "
            "Re-probe and update the record: its grants were read from a "
            "version this image no longer runs."
        )


@dataclass(frozen=True)
class _CompletedPull:
    """What a fake ``subprocess.run`` returns: the two fields the helper reads."""

    returncode: int
    stderr: bytes = b""


@pytest.mark.unit
class TestThePinnedImageIsPulledOrNamedAsUnpullable:
    """A slow registry is retried, then failed by name - never an ERROR (#2053).

    ``subprocess.run`` is replaced, so no test here talks to Docker. They go
    through ``_require_pinned_image``, the thing the fixture returns, because
    the outcome that matters is the skip or failure a reader sees, not the
    value the helper hands back.
    """

    @pytest.fixture(autouse=True)
    def _fresh_session(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
        monkeypatch.setattr(_MEMO, "available", False)
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", sleeps.append)
        monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/docker")
        yield sleeps

    def _registry(
        self, monkeypatch: pytest.MonkeyPatch, pulls: list[_CompletedPull | None]
    ) -> list[list[str]]:
        """Image absent locally; each pull does the next thing in ``pulls``.

        ``None`` is a pull that hits the timeout.
        """
        calls: list[list[str]] = []

        def fake_run(argv: list[str], **kwargs: object) -> _CompletedPull:
            calls.append(argv)
            if argv[:3] == ["docker", "image", "inspect"]:
                return _CompletedPull(returncode=1)
            outcome = pulls.pop(0)
            if outcome is None:
                raise subprocess.TimeoutExpired(argv, _PROBE_TIMEOUT_SECONDS)
            return outcome

        monkeypatch.setattr(subprocess, "run", fake_run)
        return calls

    def test_a_timeout_then_a_success_is_available(
        self, monkeypatch: pytest.MonkeyPatch, _fresh_session: list[float]
    ) -> None:
        calls = self._registry(monkeypatch, [None, _CompletedPull(returncode=0)])

        assert _require_pinned_image() == DEFAULT_WORKSPACE_IMAGE
        assert [argv[1] for argv in calls] == ["image", "pull", "pull"]
        assert _fresh_session == [_PULL_BACKOFF_SECONDS[0]]

    def test_every_attempt_timing_out_is_one_named_failure(
        self, monkeypatch: pytest.MonkeyPatch, _fresh_session: list[float]
    ) -> None:
        calls = self._registry(monkeypatch, [None] * _PULL_ATTEMPTS)

        with pytest.raises(pytest.fail.Exception) as failed:
            _require_pinned_image()

        assert str(failed.value) == (
            f"pinned image {DEFAULT_WORKSPACE_IMAGE} could not be pulled after "
            f"{_PULL_ATTEMPTS} attempts: timed out after {_PROBE_TIMEOUT_SECONDS} s"
        )
        assert [argv[1] for argv in calls].count("pull") == _PULL_ATTEMPTS
        assert _fresh_session == list(_PULL_BACKOFF_SECONDS)

    @pytest.mark.parametrize(
        "failure",
        [None, _CompletedPull(returncode=1, stderr=b"denied: 503 Service Unavailable\n")],
        ids=["timeouts", "refusals"],
    )
    def test_an_exhausted_pull_is_retried_by_the_next_test_that_needs_the_image(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _fresh_session: list[float],
        failure: _CompletedPull | None,
    ) -> None:
        calls = self._registry(
            monkeypatch, [failure] * _PULL_ATTEMPTS + [_CompletedPull(returncode=0)]
        )
        with pytest.raises(pytest.fail.Exception):
            _require_pinned_image()

        # Same session, registry recovered: the failure must not be remembered.
        assert _require_pinned_image() == DEFAULT_WORKSPACE_IMAGE
        assert [argv[1] for argv in calls].count("pull") == _PULL_ATTEMPTS + 1
        # ...but the success is, so a third test runs no docker command at all.
        before = len(calls)
        assert _require_pinned_image() == DEFAULT_WORKSPACE_IMAGE
        assert len(calls) == before

    def test_a_registry_refusal_fails_with_its_stderr_instead_of_skipping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        refused = _CompletedPull(returncode=1, stderr=b"denied: 503 Service Unavailable\n")
        self._registry(monkeypatch, [refused] * _PULL_ATTEMPTS)

        with pytest.raises(pytest.fail.Exception, match="after 3 attempts: exit 1: denied: 503"):
            _require_pinned_image()

    def test_no_docker_binary_is_the_only_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._registry(monkeypatch, [])
        monkeypatch.setattr(shutil, "which", lambda _name: None)

        with pytest.raises(pytest.skip.Exception, match="SKIPPED means the vocabulary was NOT"):
            _require_pinned_image()
        assert calls == []
