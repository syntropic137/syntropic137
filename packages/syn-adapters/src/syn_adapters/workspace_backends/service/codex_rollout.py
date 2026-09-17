"""Recovering the rollout codex wrote inside a workspace (#1284).

Implements ``CodexRolloutPort`` for a live ``ManagedWorkspace``. Codex names
the model it ran on disk and nowhere on its stdout stream, so this read is the
only observation of a codex phase's identity that exists - without it every
codex artifact says ``provider="codex", model=null`` and proves which HARNESS
ran, never which MODEL.

WHERE codex keeps its sessions is not restated here. ``CodexTranscriptSource``
in agentic-primitives already owns the ``$CODEX_HOME`` layout, the override,
the absent-root case and the id each file is keyed by, and it reads through the
workspace's exec rather than the local filesystem because the container may not
be on this machine. Per the boundary rule in AGENTS.md that knowledge tracks
the codex CLI, so restating it here would drift the next time codex moves a
directory - silently, and into a field that reads as evidence.

WHAT the records mean stays in the domain: this hands back exactly what was
written and ``model_from_rollout`` reads it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from agentic_isolation.harnesses.codex.transcripts import CodexTranscriptSource
from agentic_isolation.providers.base import ExecuteResult

if TYPE_CHECKING:
    from agentic_isolation.harnesses import ExecFn

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.agent_sessions import RolloutDocument

logger = logging.getLogger(__name__)

#: A transcript nothing depends on must not hold up a workspace teardown.
_READ_TIMEOUT_SECONDS = 30


def _exec_fn_for(workspace: ManagedWorkspace) -> ExecFn:
    """Adapt ``ManagedWorkspace.execute`` to the ``ExecFn`` shape.

    The two differ only in calling convention: ``ExecFn`` passes one shell
    string, ``ManagedWorkspace.execute`` takes argv and shell-quotes it, so the
    string has to arrive as ``sh -c``'s operand or the shell metacharacters
    ``CodexTranscriptSource`` relies on would be quoted into literals.
    """

    async def exec_fn(
        command: str,
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecuteResult:
        result = await workspace.execute(
            ["sh", "-c", command],
            timeout_seconds=int(timeout) if timeout else _READ_TIMEOUT_SECONDS,
            working_directory=cwd,
            environment=env,
        )
        return ExecuteResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
        )

    return exec_fn


def _records(lines: list[str]) -> RolloutDocument:
    """The JSONL lines as records, skipping any line that is not one.

    A rollout is written while codex runs, so its last line can be a partial
    one, and a single unusable line must never cost the rest of the file.
    """
    document: list[dict[str, object]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError, RecursionError):
            continue
        if isinstance(record, dict):
            document.append(record)
    return document


async def read_codex_rollout(
    workspace: ManagedWorkspace,
    native_session_id: str,
) -> RolloutDocument | None:
    """The rollout codex persisted under ``native_session_id``, or None.

    ``None`` means it could not be read - nothing was persisted, the listing
    failed, the workspace is gone. An empty document means the opposite: the
    file was read and holds nothing. Both leave the model unknown, but only the
    first is an operational fault, and the caller logs them differently for
    that reason.
    """
    try:
        extraction = await CodexTranscriptSource(_exec_fn_for(workspace)).extract()
    except Exception:
        # `extract()` documents that it never raises. Believing that without a
        # guard would make this the one read that can fail a teardown.
        logger.exception("Reading codex transcripts raised (session=%s)", native_session_id)
        return None

    if extraction.errors:
        logger.warning(
            "Reading codex transcripts reported errors (session=%s): %s",
            native_session_id,
            "; ".join(extraction.errors),
        )

    for transcript in extraction.transcripts:
        if transcript.session_id == native_session_id:
            return _records(transcript.lines)

    if len(extraction.transcripts) == 1:
        # A workspace runs ONE codex leader and is thrown away after it, and a
        # codex phase's declared delegate is `claude -p`, which writes claude
        # transcripts and not rollouts. So a lone rollout in this container is
        # this session's, whatever id it is filed under, and this is not a
        # guess about which session it belongs to - there is no other.
        #
        # It is needed because the id is resolved from `session_meta`, and the
        # field that carries it has already moved once: agentic-primitives
        # reads `payload.session_id` while the rollout captured in this repo's
        # own fixture writes `payload.id`. On a codex version that writes the
        # latter every exact match fails and falls back to the FILENAME stem,
        # which can never equal an announced thread id. Without this the whole
        # feature would be silently dead on some codex versions, which is the
        # failure mode #1284 exists to remove.
        only = extraction.transcripts[0]
        logger.info(
            "Codex rollout %s is filed under %s, not the announced %s - it is the only "
            "one in this workspace, so it is this session's",
            only.source_path,
            only.session_id,
            native_session_id,
        )
        return _records(only.lines)

    logger.warning(
        "No codex rollout found for session %s among %d transcript(s)",
        native_session_id,
        len(extraction.transcripts),
    )
    return None
