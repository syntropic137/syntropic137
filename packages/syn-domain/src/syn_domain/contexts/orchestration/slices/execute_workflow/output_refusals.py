"""The refusal policy for a phase's output files (#1913).

A refused FILE is named and recorded, and the rest of the output is collected;
a walk that stopped early fails the collection, because it cannot say which
files it missed. A refusal is never collected as an empty or a missing file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from syn_domain.contexts.orchestration._shared.file_transfer import (
    FileRefusal,
    FilesRefusedError,
)

logger = logging.getLogger(__name__)


class _CollectsFiles(Protocol):
    async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]: ...


@dataclass(frozen=True)
class KeptOutput:
    """What was kept of a phase that will not complete, and what was refused.

    The refusals travel with the ids so the caller can record them on the
    execution: dropping them here is how they used to reach only a log line.
    """

    artifact_ids: list[str] = field(default_factory=list)
    refused: tuple[FileRefusal, ...] = ()


class OutputCollectionIncompleteError(RuntimeError):
    """The walk of the phase's output stopped early, so nobody knows what it held.

    The refusal policy (#1913): a refused FILE is named and recorded, and the
    rest of the output is collected; a walk that stopped (too many entries,
    too deep) cannot say which files it missed, so the phase's output is not
    collected as if it were whole.
    """

    def __init__(self, refused: tuple[FileRefusal, ...]) -> None:
        self.refused = refused
        super().__init__(
            "the phase's output could not be listed in full: "
            + ", ".join(r.describe() for r in refused)
            + ". Reduce the files under artifacts/output, or raise the collection limits."
        )


async def collect_output_files(
    workspace: _CollectsFiles, patterns: list[str]
) -> tuple[list[tuple[str, bytes]], tuple[FileRefusal, ...]]:
    """The phase's output files and what was refused, under the refusal policy.

    Raises:
        OutputCollectionIncompleteError: the walk stopped before listing it all.
    """
    try:
        return await workspace.collect_files(patterns=patterns), ()
    except FilesRefusedError as e:
        if not e.complete:
            raise OutputCollectionIncompleteError(e.refused) from e
        logger.warning("Output files refused at collection: %s", e)
        return list(e.files), e.refused
