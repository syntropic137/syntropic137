"""Persist a source namespace once, independent of process or container identity."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from syn_domain.contexts.agent_sessions import RunIdentity

from .local_archive import _sync_directory


def installation_identity(root: Path, override: str = "") -> str:
    """Called after archive initialization. Concurrent starters use the same ID."""
    target = root / ".source-instance-id"
    candidate = RunIdentity(
        source_instance_id=override or str(uuid4()),
        execution_id="identity-validation",
    ).source_instance_id
    descriptor, temporary = tempfile.mkstemp(prefix=".identity-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(candidate)
            output.flush()
            os.fsync(output.fileno())
        with contextlib.suppress(FileExistsError):
            os.link(temporary, target)
        _sync_directory(root)
    finally:
        Path(temporary).unlink(missing_ok=True)
    # Corrupt identity is a startup failure, never a newly generated namespace.
    value = target.read_text()
    if override and value != override:
        raise ValueError("configured source identity differs from the durable archive identity")
    return RunIdentity(
        source_instance_id=value, execution_id="identity-validation"
    ).source_instance_id
