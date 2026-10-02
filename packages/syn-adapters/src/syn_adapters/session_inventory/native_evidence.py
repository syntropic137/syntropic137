"""Translate the agentic-primitives capability contract, never parse vendor fields."""

from agentic_isolation.harnesses import EvidenceHarnessPlugin, get_harness
from agentic_isolation.harnesses.envelope_evidence import EnvelopeEvidenceReader

from syn_domain.contexts.agent_sessions import (
    NativeRelationshipFact,
    NativeTranscriptFacts,
    UnsupportedEvidenceIssue,
)


class AgenticNativeSessionEvidence:
    def extract(self, harness: str, content: bytes) -> NativeTranscriptFacts:
        return self._extract(harness, content, envelope=False)

    def extract_envelope(self, harness: str, content: bytes) -> NativeTranscriptFacts:
        return self._extract(harness, content, envelope=True)

    def _extract(self, harness: str, content: bytes, *, envelope: bool) -> NativeTranscriptFacts:
        plugin = get_harness(harness)
        if not isinstance(plugin, EvidenceHarnessPlugin):
            return NativeTranscriptFacts(
                native_id=None,
                supported=False,
                issues=(UnsupportedEvidenceIssue.HARNESS,),
                extractor_version="agentic-evidence/1",
                byte_count=len(content),
            )
        reader = plugin.evidence_reader()
        if envelope:
            if not isinstance(reader, EnvelopeEvidenceReader):
                return NativeTranscriptFacts(
                    native_id=None,
                    supported=False,
                    issues=(UnsupportedEvidenceIssue.ENVELOPE,),
                    extractor_version="agentic-evidence/1",
                    byte_count=len(content),
                )
            result = reader.extract_envelope(content)
        else:
            result = reader.extract(content)
        return NativeTranscriptFacts(
            native_id=result.native_id,
            root_native_id=result.root_id,
            identity_lines=result.identity_lines,
            issues=result.issues,
            extractor_version=result.extractor_version,
            byte_count=len(content),
            relationships=tuple(
                NativeRelationshipFact(
                    parent_native_id=link.parent_id,
                    child_native_id=link.child_id,
                    relation=link.relation,
                    mechanism=link.mechanism,
                    basis=link.basis,
                    source_lines=link.lines,
                    call_id=link.call_id,
                )
                for link in result.links
            ),
        )
