"""Harness-neutral translation accepts a third capability without parser changes."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from agentic_isolation.harnesses import AgentName, ExecFn, TranscriptSource
from agentic_isolation.harnesses.evidence import NativeEvidence, NativeLink

from syn_adapters.session_inventory import native_evidence

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class ExampleHarness:
    name: AgentName = AgentName.GEMINI

    def transcript_source(self, exec_fn: ExecFn) -> TranscriptSource | None:
        return None

    def evidence_reader(self) -> ExampleHarness:
        return self

    def extract(self, content: bytes) -> NativeEvidence:
        assert content == b"third harness format"
        return NativeEvidence(
            native_id="opaque/native",
            extractor_version="example/1",
            identity_lines=(3,),
            links=(
                NativeLink(
                    parent_id="parent",
                    child_id="opaque/native",
                    relation="spawn",
                    mechanism="example-header",
                    basis="child_header",
                    lines=(3,),
                ),
            ),
        )


def test_third_harness_is_translated_without_new_vendor_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native_evidence, "get_harness", lambda _name: ExampleHarness())
    result = native_evidence.AgenticNativeSessionEvidence().extract(
        "example", b"third harness format"
    )
    assert result.native_id == "opaque/native"
    assert result.extractor_version == "example/1"
    assert result.relationships[0].parent_native_id == "parent"
    assert result.relationships[0].source_lines == (3,)
    assert result.supported


def test_unknown_capability_is_explicit_and_does_not_guess_identity() -> None:
    result = native_evidence.AgenticNativeSessionEvidence().extract("unsupported", b"anything")
    assert result.native_id is None
    assert not result.supported
    assert result.issues == ("unsupported_harness_evidence",)
