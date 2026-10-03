"""``read_codex_rollout`` driven against a real rollout tree on disk (#1284).

This is the ONLY production bridge between "a workspace holds a rollout file"
and "the domain gets a ``RolloutDocument``". Everything downstream of it -
``model_from_rollout``, the announced-vs-requested refusal, the artifact's
``agent_model`` - is tested against ``CodexRolloutPort`` DOUBLES that answer
with a canned document. Those doubles are right for what they test, and they
are also why the bridge itself was invisible: replacing this function's body
with ``return None`` left every one of them green, while in a real workspace
every codex artifact would report ``agent_model=null`` - the exact symptom
#1284 exists to remove.

So the workspace here is a double but the READ is not. ``_ShellWorkspace``
answers ``execute`` by actually running the argv it is given, so
``CodexTranscriptSource``'s ``find``/``cat`` shell, its ``$CODEX_HOME``
resolution, its absent-root marker, its session-id resolution and this
module's matching and fallback all execute for real against a tmpdir laid out
the way codex lays one out. What is faked is the container, not the behaviour
under test.

The four ways a file-finder goes wrong each get a case: nothing to find, one
file that matches, several (it must pick by session id, not by position), and
a file that exists but is filed under another id.
"""

from __future__ import annotations

import inspect
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from syn_adapters.workspace_backends.service.codex_rollout import read_codex_rollout
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_domain.contexts.agent_sessions import model_from_rollout
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import RolloutDocument, RolloutRecord

pytestmark = pytest.mark.unit

#: The same REAL captured rollout `transcript_usage` prices a codex delegate
#: from - `session_meta`, `turn_context.payload.model` and all. A hand-rolled
#: two-line file would pass this test and prove nothing about the document
#: codex actually writes.
_REPO_ROOT = Path(__file__).resolve().parents[6]
_ROLLOUT_FIXTURE = (
    _REPO_ROOT / "packages/syn-domain/tests/fixtures/delegation/codex_rollout_usage.json"
)

#: The model that capture names on its `turn_context`. Asserted, not assumed:
#: a fixture that stopped naming a model would make the read look successful
#: while the value it exists to carry arrived as None.
CAPTURED_MODEL = "gpt-5.6-sol"

#: The session that capture is filed under.
CAPTURED_SESSION = "01a0454b-169b-7952-ac16-944da94056d4"

#: Two rollouts side by side in one workspace, each naming a DIFFERENT model,
#: so the document that comes back says which of the two files was selected.
#: An id that matches neither, for the cases about not finding one.
TWO_ROLLOUTS = {
    "aaaa1111-0000-4000-8000-00000000aaaa": "gpt-5.6-sol",
    "bbbb2222-0000-4000-8000-00000000bbbb": "gpt-5.6-codex",
}
NO_SUCH_SESSION = "an-id-no-file-is-filed-under"


def _captured_records() -> RolloutDocument:
    document = json.loads(_ROLLOUT_FIXTURE.read_text())
    assert isinstance(document, list), f"{_ROLLOUT_FIXTURE} is not a list of records"
    assert any(
        record.get("type") == "turn_context" and record["payload"]["model"] == CAPTURED_MODEL
        for record in document
    ), f"{_ROLLOUT_FIXTURE} no longer names {CAPTURED_MODEL} on a turn_context"
    return document


def _refiled(record: RolloutRecord, *, session_id: str, model: str) -> RolloutRecord:
    """The captured record as a different session, or on a different model.

    A copy rather than a mutation: the capture is shared with the domain's own
    tests and two rollouts get written from it in a single test.
    """
    payload = record.get("payload")
    assert isinstance(payload, Mapping), f"a rollout record with no payload: {record}"
    if record.get("type") == "session_meta":
        # Both, because codex has written the id under each of these across
        # versions and the read has to work on either.
        return {**record, "payload": {**payload, "id": session_id, "session_id": session_id}}
    if record.get("type") == "turn_context":
        return {**record, "payload": {**payload, "model": model}}
    return record


class _ShellWorkspace:
    """A workspace whose ``execute`` really runs the command, in a tmpdir.

    Stands in for the container only: the argv arrives unshelled, exactly as
    ``docker exec`` would deliver it, so the ``sh -c`` hop in ``_exec_fn_for``
    and every shell metacharacter ``CodexTranscriptSource`` relies on have to
    survive for real. ``CODEX_HOME`` is part of the environment the way it is
    inside a workspace, not something the read is told about.
    """

    def __init__(self, codex_home: Path) -> None:
        self.codex_home = codex_home
        self.commands: list[list[str]] = []

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        self.commands.append(command)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.codex_home.parent),
            "CODEX_HOME": str(self.codex_home),
            **(environment or {}),
        }
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=working_directory,
            env=env,
            timeout=timeout_seconds,
            check=False,
        )
        return ExecutionResult(
            exit_code=proc.returncode,
            success=proc.returncode == 0,
            duration_ms=0.0,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


def _workspace(codex_home: Path) -> ManagedWorkspace:
    """The double, as the read's signature sees it.

    The cast is safe only as long as ``execute`` still has the signature the
    double copied, which pyright will not check here (co-located test files
    are excluded) - ``test_the_double_reports_the_real_execute_signature``
    checks it instead.
    """
    return cast("ManagedWorkspace", _ShellWorkspace(codex_home))


def _write_rollout(
    codex_home: Path,
    *,
    session_id: str,
    model: str = CAPTURED_MODEL,
    day: str = "2026/08/27",
    stamp: str = "2026-08-27T22-15-44",
) -> Path:
    """One rollout file, where and how codex writes one."""
    records = [
        _refiled(record, session_id=session_id, model=model) for record in _captured_records()
    ]
    path = codex_home / "sessions" / day / f"rollout-{stamp}-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{json.dumps(record)}\n" for record in records))
    return path


def _write_two_rollouts(codex_home: Path) -> None:
    """``TWO_ROLLOUTS`` on disk, as two files under one sessions root."""
    for session_id, model in TWO_ROLLOUTS.items():
        _write_rollout(
            codex_home,
            session_id=session_id,
            model=model,
            stamp=f"2026-08-27T22-15-{session_id[:2]}",
        )


def _model_of(document: RolloutDocument | None) -> str | None:
    """What the domain gets out of the read - the reason the read exists."""
    assert document is not None
    return model_from_rollout(document)


@pytest.fixture
def codex_home(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".codex"


async def test_the_rollout_codex_wrote_reaches_the_domain(codex_home: Path) -> None:
    """The whole point: a file on disk becomes a document naming a model."""
    _write_rollout(codex_home, session_id=CAPTURED_SESSION)

    document = await read_codex_rollout(_workspace(codex_home), CAPTURED_SESSION)

    assert _model_of(document) == CAPTURED_MODEL


async def test_no_rollout_at_all_is_unread_not_empty(codex_home: Path) -> None:
    """``--ephemeral``, or a phase that never got as far as writing one.

    None and an empty document mean different things to the caller, and the
    sessions root not existing is the None one.
    """
    assert not codex_home.exists()

    assert await read_codex_rollout(_workspace(codex_home), "01a0454b-169b") is None


async def test_a_sessions_root_holding_no_rollout_reads_as_unread(codex_home: Path) -> None:
    """The root exists - so ``find`` succeeds and lists nothing."""
    (codex_home / "sessions" / "2026" / "08" / "27").mkdir(parents=True)

    assert await read_codex_rollout(_workspace(codex_home), "01a0454b-169b") is None


@pytest.mark.parametrize("wanted", TWO_ROLLOUTS)
async def test_several_rollouts_are_matched_by_session_id_not_position(
    codex_home: Path, wanted: str
) -> None:
    """Asked for either of two, it answers with that one.

    Both ids are exercised against the SAME tree, which is what makes this
    bite independently of the order ``find`` happens to walk the directory in:
    a read that returns whichever file it saw first returns the same document
    for both ids, so it must fail one of these two cases whatever that order
    is.
    """
    _write_two_rollouts(codex_home)

    document = await read_codex_rollout(_workspace(codex_home), wanted)

    assert _model_of(document) == TWO_ROLLOUTS[wanted]


async def test_the_only_rollout_in_the_workspace_is_this_session_s(codex_home: Path) -> None:
    """Filed under an id that is not the announced one, and still returned.

    A workspace runs one codex leader and is thrown away after it, so a lone
    rollout has no other session it could belong to - and the id codex files
    it under has already moved once between codex versions. Refusing it here
    would leave the model silently unknown on those versions, which is the
    failure #1284 is about.
    """
    _write_rollout(codex_home, session_id=CAPTURED_SESSION)

    document = await read_codex_rollout(_workspace(codex_home), NO_SUCH_SESSION)

    assert _model_of(document) == CAPTURED_MODEL


async def test_several_rollouts_and_none_matching_is_refused(codex_home: Path) -> None:
    """The fallback is "there is no other one", not "pick something".

    With two candidates and no match there is nothing that identifies either,
    and answering with one of them would put a model on the artifact that
    nothing observed.
    """
    _write_two_rollouts(codex_home)

    assert await read_codex_rollout(_workspace(codex_home), NO_SUCH_SESSION) is None


async def test_a_half_written_last_line_does_not_cost_the_file(codex_home: Path) -> None:
    """A rollout is written while codex runs, so it can be caught mid-line."""
    path = _write_rollout(codex_home, session_id=CAPTURED_SESSION)
    with path.open("a") as handle:
        handle.write('{"type": "event_msg", "payload": {"info": ')

    document = await read_codex_rollout(_workspace(codex_home), CAPTURED_SESSION)

    assert _model_of(document) == CAPTURED_MODEL


async def test_the_port_asks_for_the_session_codex_announced(codex_home: Path) -> None:
    """The last hop: ``ManagedWorkspace.codex_rollout`` forwards WHICH id.

    This is the trap a test at either end cannot see - a hop that forwarded
    the workspace id, or the platform session id, instead of the id codex
    announced still returns a document, and with one rollout in the tree it
    even returns the right one. So the tree here holds two, where forwarding
    the wrong id can only come back empty.

    Production's own method body runs: it is called unbound on the double
    because constructing a ``ManagedWorkspace`` takes a live container.
    """
    _write_two_rollouts(codex_home)
    wanted = next(iter(TWO_ROLLOUTS))

    document = await ManagedWorkspace.codex_rollout(_workspace(codex_home), wanted)

    assert _model_of(document) == TWO_ROLLOUTS[wanted]


def test_the_double_reports_the_real_execute_signature() -> None:
    """The double copies ``ManagedWorkspace.execute``; pyright does not check it.

    A test double that lies about the contract is how a bridge gets certified
    while broken - the sibling setup-phase tests have already been bitten by
    one. If ``execute`` gains or renames a parameter, this fails here rather
    than leaving every case above passing against a shape production no longer
    has.
    """
    assert inspect.signature(_ShellWorkspace.execute) == inspect.signature(ManagedWorkspace.execute)
