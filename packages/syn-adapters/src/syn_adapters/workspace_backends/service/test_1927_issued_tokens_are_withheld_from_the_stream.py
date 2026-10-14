"""Every GitHub token issued to a workspace is withheld from its agent stream (#1927).

The setup phase writes installation tokens to files the agent can read, and the
renewal task replaces them while the agent runs. They never pass through the
launch environment, so the stream boundary can only redact them if the
workspace hands over its ledger - read live, so a token renewed mid-stream is
covered from the next page on. The redaction itself is pinned beside the
stream adapter; this pins the hop that feeds it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from syn_adapters.workspace_backends.service.issued_tokens import IssuedToken
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceService

pytestmark = pytest.mark.unit


def _token(value: str) -> IssuedToken:
    return IssuedToken(value, "inst-1", ("org/repo",), datetime.now(UTC) + timedelta(hours=1))


class _EventStream:
    """Reads what the boundary would withhold, once per line, as the adapter does per page."""

    def __init__(self, on_line: Callable[[], None]) -> None:
        self.seen: list[tuple[str, ...]] = []
        self._on_line = on_line

    async def stream(
        self, *_args: object, withheld: Callable[[], Iterable[str]] | None = None, **_kw: object
    ) -> AsyncIterator[str]:
        assert withheld is not None, "the workspace handed the boundary nothing to withhold"
        for line in ("first", "second"):
            self.seen.append(tuple(withheld()))
            yield line
            self._on_line()


class _Service:
    def __init__(self, event_stream: _EventStream) -> None:
        self._event_stream = event_stream


async def test_issued_tokens_reach_the_stream_boundary_including_a_renewal() -> None:
    renewals = iter([_token("ghs_RENEWED_1927")])
    workspace: ManagedWorkspace

    def renew() -> None:
        workspace.issuance_ledger.record(renewals)

    event_stream = _EventStream(renew)
    workspace = ManagedWorkspace(
        workspace_id="ws-1927",
        execution_id="exec-1927",
        aggregate=MagicMock(),
        isolation_handle=MagicMock(),
        sidecar_handle=None,
        _service=cast("WorkspaceService", _Service(event_stream)),
    )
    workspace.issuance_ledger.record((_token("ghs_SETUP_1927"),))

    assert [line async for line in workspace.stream(["claude"])] == ["first", "second"]

    assert event_stream.seen == [
        ("ghs_SETUP_1927",),
        ("ghs_SETUP_1927", "ghs_RENEWED_1927"),
    ]
