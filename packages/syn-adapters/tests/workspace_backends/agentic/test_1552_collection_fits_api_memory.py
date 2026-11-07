"""Artifact collection is bounded by SYN_EXECUTION_COLLECTION_MAX_MB (#1552).

Collection runs inside the API process, which hosts every in-process
execution, so one collection past its share of API memory kills every run.
The cap is a setting sized to the per-run allowance, and both read paths take
it: the provider read (Docker, E2B) is handed what is left of the phase's
budget as `ReadLimits`, and the bind-mount walk refuses a file over it before
reading a byte of it.

The provider tests drive `copy_from` through the real E2B provider over its
sandbox double, and assert on the bytes the provider asked the workspace for.
Each sets the cap to 1MiB, a value no default produces, and uses files that
the old 200MiB / 50MiB caps would have read whole.
"""

from __future__ import annotations

import os
import tracemalloc
from typing import TYPE_CHECKING, ClassVar

import pytest

from syn_adapters.workspace_backends.agentic import adapter_copy
from syn_adapters.workspace_backends.agentic.credential_scrubber import (
    SCRUB_GROWTH_RATIO,
    SCRUB_GROWTH_SLACK_BYTES,
    SCRUB_LINE_MAX_CHARS,
    CredentialScrubber,
    scrub_bytes,
    scrub_files,
)
from syn_adapters.workspace_backends.e2b import e2b_conformance as suite
from syn_adapters.workspace_backends.e2b.test_e2b_backend import _TEMPLATE, SandboxDouble, _adapter
from syn_domain.contexts.orchestration._shared.file_transfer import (
    FileRefusal,
    FilesRefusedError,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    _as_collected,
)
from syn_shared.settings import reset_settings
from syn_shared.settings.execution import (
    API_BASELINE_MEMORY_MIB,
    COLLECTION_MEMORY_MIB,
    COLLECTION_RETAINED_COPIES,
    COLLECTION_TRANSIENT_COPIES,
    EXECUTION_API_MEMORY_MIB,
    EXECUTION_MEASURED_MEMORY_MIB,
    ExecutionSettings,
)
from syn_shared.settings.infra import InfraSettings

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from syn_adapters.workspace_backends.agentic import AgenticIsolationAdapter

pytestmark = [pytest.mark.unit]

_MIB = 1024 * 1024
_OUTPUT = "artifacts/output"


@pytest.fixture
def one_mib_cap(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setenv("SYN_EXECUTION_COLLECTION_MAX_MB", "1")
    reset_settings()
    return _MIB


def _write(root: Path, name: str, size: int) -> bytes:
    content = (name.encode() * (size // len(name) + 1))[:size]
    path = root / _OUTPUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _collect(root: Path) -> list[tuple[str, bytes]]:
    handle = IsolationHandle(
        isolation_id="ws-1552", isolation_type="docker", host_workspace_path=str(root)
    )
    return adapter_copy._copy_from_workspace_blocking(handle, [f"{_OUTPUT}/*"])


def _record_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The bytes each `os.read` brought into memory, so a test sees what was loaded."""
    requested: list[int] = []
    real_read = os.read

    def _read(fd: int, n: int) -> bytes:
        chunk = real_read(fd, n)
        if chunk:
            requested.append(len(chunk))
        return chunk

    monkeypatch.setattr(adapter_copy.os, "read", _read)
    return requested


def test_an_oversized_file_is_never_read_into_memory(
    tmp_path: Path, one_mib_cap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "big.bin", 2 * one_mib_cap)
    requested = _record_reads(monkeypatch)

    collected = _collect(tmp_path)

    assert collected == []
    assert requested == [], "a file over the cap was read"


def test_collection_stops_before_the_sum_passes_the_cap(
    tmp_path: Path, one_mib_cap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.bin", "b.bin", "c.bin"):
        _write(tmp_path, name, 600 * 1024)
    requested = _record_reads(monkeypatch)

    collected = _collect(tmp_path)

    assert len(collected) == 1, "only one 600KiB file fits a 1MiB collection"
    assert sum(requested) <= one_mib_cap, "read past the collection cap"


def test_below_the_caps_collection_is_unchanged(tmp_path: Path, one_mib_cap: int) -> None:
    small = {
        name: _write(tmp_path, name, 1000 * (i + 1)) for i, name in enumerate(("x.md", "y.md"))
    }

    collected = _collect(tmp_path)

    assert sorted(collected) == sorted((f"{_OUTPUT}/{n}", c) for n, c in small.items())
    assert sum(len(c) for _, c in collected) < one_mib_cap


class _ObservedSandbox(SandboxDouble):
    """The E2B double, recording each path and size the provider asks it to read."""

    requested: ClassVar[list[tuple[str, int]]] = []

    @staticmethod
    def _records(files: Mapping[str, bytes], root: str, stdin: bytes) -> bytes:
        _ObservedSandbox.requested.extend(
            (rel, len(files[f"{root}/{rel}"])) for rel in stdin.decode().split("\0")[:-1]
        )
        return SandboxDouble._records(files, root, stdin)


async def _workspace(
    adapter: AgenticIsolationAdapter, files: list[tuple[str, bytes]]
) -> IsolationHandle:
    handle = await adapter.create(suite.isolation_config(_TEMPLATE))
    await adapter.copy_to(handle, files)
    return handle


@pytest.fixture
def e2b(one_mib_cap: int) -> AgenticIsolationAdapter:
    del one_mib_cap
    _ObservedSandbox.requested = []
    adapter, _ = _adapter(_ObservedSandbox())
    return adapter


def _requested_bytes() -> int:
    return sum(n for _, n in _ObservedSandbox.requested)


async def test_the_provider_never_reads_an_oversized_file(
    e2b: AgenticIsolationAdapter,
) -> None:
    handle = await _workspace(e2b, [(f"{_OUTPUT}/big.bin", b"x" * (2 * _MIB))])

    with pytest.raises(FilesRefusedError) as refused:
        await e2b.copy_from(handle, [f"{_OUTPUT}/**/*"])

    assert _ObservedSandbox.requested == [], "a file over the cap was read"
    assert [(r.path, r.reason) for r in refused.value.refused] == [
        (f"{_OUTPUT}/big.bin", "file_too_large")
    ]


async def test_the_provider_stops_before_the_sum_passes_the_cap(
    e2b: AgenticIsolationAdapter,
) -> None:
    files = [(f"{_OUTPUT}/{n}.bin", b"x" * (600 * 1024)) for n in ("a", "b", "c")]
    handle = await _workspace(e2b, files)

    with pytest.raises(FilesRefusedError) as refused:
        await e2b.copy_from(handle, [f"{_OUTPUT}/**/*"])

    assert _requested_bytes() <= _MIB, _ObservedSandbox.requested
    assert len(refused.value.files) == 1
    assert {r.reason for r in refused.value.refused} == {"total_bytes_exceeded"}


async def test_below_the_caps_the_provider_read_is_unchanged(
    e2b: AgenticIsolationAdapter,
) -> None:
    files = [
        (f"{_OUTPUT}/ spaced \u00fc.bin", bytes(range(256))),
        (f"{_OUTPUT}/a.md", b"hello\nworld\n"),
        (f"{_OUTPUT}/exact.bin", b"y" * (_MIB - 256 - 12)),
    ]
    handle = await _workspace(e2b, files)

    collected = await e2b.copy_from(handle, [f"{_OUTPUT}/**/*", f"{_OUTPUT}/*"])

    assert sorted(collected) == sorted(files)


async def test_a_phase_reading_twice_draws_on_one_budget(
    e2b: AgenticIsolationAdapter,
) -> None:
    """The codex output check and the collector both read one phase's output."""
    handle = await _workspace(e2b, [(f"{_OUTPUT}/a.bin", b"x" * (600 * 1024))])

    first = await e2b.copy_from(handle, [f"{_OUTPUT}/**/*"])
    with pytest.raises(FilesRefusedError) as refused:
        await e2b.copy_from(handle, [f"{_OUTPUT}/**/*"])

    assert len(first) == 1
    assert _requested_bytes() <= _MIB, _ObservedSandbox.requested
    # Larger than what the phase has left, so refused by name, unread.
    assert [(r.path, r.reason) for r in refused.value.refused] == [
        (f"{_OUTPUT}/a.bin", "file_too_large")
    ]


async def test_a_spent_budget_reads_nothing_and_names_what_was_asked(
    e2b: AgenticIsolationAdapter,
) -> None:
    handle = await _workspace(e2b, [(f"{_OUTPUT}/a.bin", b"x" * _MIB)])
    await e2b.copy_from(handle, [f"{_OUTPUT}/**/*"])
    _ObservedSandbox.requested = []

    with pytest.raises(FilesRefusedError) as refused:
        await e2b.copy_from(handle, [f"{_OUTPUT}/**/*"])

    assert _ObservedSandbox.requested == []
    assert [(r.path, r.reason) for r in refused.value.refused] == [
        (f"{_OUTPUT}/**/*", "total_bytes_exceeded")
    ]


async def test_each_phase_has_its_own_budget(e2b: AgenticIsolationAdapter) -> None:
    files = [(f"{_OUTPUT}/a.bin", b"x" * (600 * 1024))]
    first_phase = await _workspace(e2b, files)
    second_phase = await _workspace(e2b, files)

    await e2b.copy_from(first_phase, [f"{_OUTPUT}/**/*"])
    collected = await e2b.copy_from(second_phase, [f"{_OUTPUT}/**/*"])

    assert collected == files


#: Shapes that cost far more in memory than on disk: one long ASCII line,
#: ASCII with one character outside Latin-1 (decoded at 4 bytes a character),
#: lines too short to carry anything, and bytes that are not UTF-8.
_SHAPES = {
    "ascii": b"x",
    "one_emoji": "\U0001f600".encode() + b"x" * 1023,
    "newlines": b"\n",
    "short_lines": b"aa\n",
    "not_utf8": b"\xff",
}
_SIZE = 64 * 1024


def _shaped(unit: bytes, size: int = _SIZE) -> bytes:
    return (unit * (size // len(unit) + 1))[:size]


@pytest.mark.parametrize("shape", sorted(_SHAPES))
@pytest.mark.parametrize("secret", ["", "ghs_SECRETVALUE123456"])
def test_scrub_and_conversion_stay_within_the_counted_copies(shape: str, secret: str) -> None:
    """What `copy_from` and `ArtifactCollector` do to a collected file, measured.

    The scrub's peak above its input is the transient, counted once per
    process; what survives it, decoded and encoded for storage, is retained.
    """
    content = _shaped(_SHAPES[shape])
    if secret:
        content = secret.encode() + b"\n" + content[: _SIZE - len(secret) - 1]
    scrubber = CredentialScrubber([secret])

    tracemalloc.start()
    try:
        scrubbed = scrub_bytes(scrubber, content)
        _, transient = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        stored, _ = _as_collected("artifacts/output/f", scrubbed)
        encoded = stored.encode() if isinstance(stored, str) else stored
        retained, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert transient <= COLLECTION_TRANSIENT_COPIES * _SIZE + 4096, transient / _SIZE
    assert retained <= COLLECTION_RETAINED_COPIES * _SIZE + 4096, retained / _SIZE
    assert encoded is not None


def test_a_file_nothing_matches_is_not_copied_by_the_scrub() -> None:
    content = _shaped(b"aa\n")

    assert scrub_bytes(CredentialScrubber(["ghs_SECRETVALUE123456"]), content) is content


def test_the_default_cap_fits_every_run_of_the_default_api_limit() -> None:
    """The arithmetic in execution.py, from the copies measured above."""
    cap_mib = ExecutionSettings().collection_max_mb
    limit = InfraSettings().api_memory_limit
    limit_mib = int(limit[:-1]) * (1024 if limit.endswith("g") else 1)
    runs = (limit_mib - API_BASELINE_MEMORY_MIB) // EXECUTION_API_MEMORY_MIB
    # Scrubbed twice, each growing at most by the ratio, plus a slack a call.
    scrubbed_mib = cap_mib * SCRUB_GROWTH_RATIO**2 + 2 * SCRUB_GROWTH_SLACK_BYTES / 2**20
    per_run = EXECUTION_MEASURED_MEMORY_MIB + COLLECTION_RETAINED_COPIES * scrubbed_mib

    assert cap_mib == COLLECTION_MEMORY_MIB
    assert per_run <= EXECUTION_API_MEMORY_MIB
    transient = COLLECTION_TRANSIENT_COPIES * cap_mib
    # Rewriting the longest line that holds a value fits inside that peak.
    assert transient * 2**20 >= _JSON_REWRITE_FACTOR * SCRUB_LINE_MAX_CHARS
    assert API_BASELINE_MEMORY_MIB + runs * per_run + transient <= limit_mib


#: The most rewriting a JSON line measured costing, times the line (#1552):
#: empty containers, each a few bytes on disk and a whole object parsed,
#: again rebuilt. 71 measured; the arithmetic counts 80.
_JSON_REWRITE_FACTOR = 80
_SECRET = "ghs_SECRETVALUE123456"


def _json_line(item: bytes, size: int) -> bytes:
    head = b'["' + _SECRET.encode() + b'",'
    return head + item * ((size - len(head) - 5) // len(item)) + b"null]"


#: Matching content whose rewrite costs far more than its size: a short value
#: repeated (the marker is longer than it), and JSON of empty containers.
_MATCHING = {
    "short_value_repeated": ("x", b"x" * 65536),
    "json_objects": (_SECRET, _json_line(b"{},", 48 * 1024)),
    "json_lists": (_SECRET, _json_line(b"[],", 48 * 1024)),
    "json_nested_lists": (_SECRET, _json_line(b"[[[]]],", 48 * 1024)),
    "json_at_the_line_limit": (_SECRET, _json_line(b"[[[]]],", SCRUB_LINE_MAX_CHARS)),
    "json_past_the_line_limit": (_SECRET, _json_line(b"{},", SCRUB_LINE_MAX_CHARS + 64)),
}


@pytest.mark.parametrize("shape", sorted(_MATCHING))
def test_scrubbing_matching_content_stays_within_the_counted_memory(shape: str) -> None:
    """The reviewer's counterexamples (#1552): what scrubbing a matching file costs.

    Each is refused by name or kept; either way the rewrite peaks inside the
    counted transient and what is kept stays within the counted growth.
    """
    secret, content = _MATCHING[shape]
    scrubber = CredentialScrubber([secret])

    tracemalloc.start()
    try:
        kept, refused = scrub_files(scrubber, [("artifacts/output/f.json", content)])
        _, transient = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        retained_files = [_as_collected(path, data)[0] for path, data in kept]
        encoded = [s.encode() if isinstance(s, str) else s for s in retained_files]
        retained, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert transient <= _JSON_REWRITE_FACTOR * min(len(content), SCRUB_LINE_MAX_CHARS) + 4096
    grown = len(content) * SCRUB_GROWTH_RATIO + SCRUB_GROWTH_SLACK_BYTES
    assert sum(len(data) for _, data in kept) <= grown
    assert retained <= COLLECTION_RETAINED_COPIES * grown + 4096, retained / len(content)
    # Nothing is lost silently, and nothing kept carries the value.
    assert len(kept) + len(refused) == 1
    assert all(r.reason == "file_too_large" for r in refused)
    assert all(_SECRET.encode() not in data for data in encoded)


def test_a_short_value_repeated_is_refused_before_its_rewrite_is_built() -> None:
    """65536 one-character values would grow to 1.3MB; the scrub never builds it."""
    scrubber = CredentialScrubber(["x"])

    tracemalloc.start()
    try:
        kept, refused = scrub_files(scrubber, [("f", b"x" * 65536)])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert kept == ()
    assert refused == (FileRefusal(path="f", reason="file_too_large"),)
    # The line decoded and searched; its rewrite measured 14.5MB.
    assert peak < 4 * 65536


def test_a_long_matching_line_is_refused_and_a_long_clean_one_kept() -> None:
    scrubber = CredentialScrubber([_SECRET])
    clean = b"a" * (SCRUB_LINE_MAX_CHARS + 1)
    matching = _json_line(b"{},", SCRUB_LINE_MAX_CHARS + 64)

    kept, refused = scrub_files(scrubber, [("clean", clean), ("matching", matching)])

    assert kept == (("clean", clean),)
    assert kept[0][1] is clean
    assert refused == (FileRefusal(path="matching", reason="file_too_large"),)


def test_files_below_the_bounds_scrub_exactly_as_scrub_bytes_did() -> None:
    """Below the line limit and the growth allowance, nothing changes."""
    scrubber = CredentialScrubber(["short", _SECRET])
    files = [
        ("a.json", b'{"t":"' + _SECRET.encode() + b'","n":[1,2]}\nshort\n'),
        ("b.txt", b"token=short and short\n"),
        ("c.bin", b"\xff\x00short"),
    ]

    kept, refused = scrub_files(scrubber, files)

    assert refused == ()
    assert kept == tuple((p, scrub_bytes(scrubber, c)) for p, c in files)
    assert all(b"short" not in c and _SECRET.encode() not in c for _, c in kept)
