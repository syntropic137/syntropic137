"""A signal-death diagnostic never carries the launch's credentials (PC-127, ADR-072).

Any argv handed to ``capture_signal_death`` is redacted before it is retained
in ``SignalDeath`` or logged, whatever spelling carries the environment.
"""

from __future__ import annotations

import pytest

from syn_adapters.diagnostics.signal_capture import REDACTED, redact_environment

pytestmark = pytest.mark.unit


# The stream-path half (a signal death on a launch carrying the platform
# grant names no credential) lives in test_stream_on_operations.py, where the
# grant is a credential binding and never reaches an argv at all.


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["-e", "K=secret"], ["-e", f"K={REDACTED}"]),
        (["--env", "K=secret"], ["--env", f"K={REDACTED}"]),
        (["-eK=secret"], [f"-eK={REDACTED}"]),
        (["--env=K=secret"], [f"--env=K={REDACTED}"]),
        (["-i", "-w", "/workspace", "ctr"], ["-i", "-w", "/workspace", "ctr"]),
    ],
)
def test_every_docker_env_spelling_is_redacted(argv: list[str], expected: list[str]) -> None:
    assert list(redact_environment(["docker", "exec", *argv])) == ["docker", "exec", *expected]
