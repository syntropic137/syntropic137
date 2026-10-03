"""Minimal typed database interface; JSON is validated at the domain boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType


class Transaction(Protocol):
    async def __aenter__(self) -> object: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> bool | None: ...


class Row(Protocol):
    def __getitem__(self, key: str) -> str: ...


class Connection(Protocol):
    async def execute(self, query: str, *args: object) -> object: ...
    async def fetchval(self, query: str, *args: object) -> str | None: ...
    async def fetch(self, query: str, *args: object) -> Sequence[Row]: ...
    def transaction(self) -> Transaction: ...


class Acquisition(Protocol):
    async def __aenter__(self) -> Connection: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> bool | None: ...


class Pool(Protocol):
    def acquire(self) -> Acquisition: ...
