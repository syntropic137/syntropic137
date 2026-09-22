"""Harness-neutral native evidence boundary. Format knowledge lives upstream."""

from typing import Protocol

from syn_domain.contexts.agent_sessions.domain.read_models.native_session_evidence import (
    NativeRelationshipFact,
    NativeTranscriptFacts,
)

__all__ = ["NativeRelationshipFact", "NativeSessionEvidencePort", "NativeTranscriptFacts"]


class NativeSessionEvidencePort(Protocol):
    def extract_envelope(self, harness: str, content: bytes) -> NativeTranscriptFacts:
        """Normalize a captured envelope without changing archived original bytes."""
        ...

    def extract(self, harness: str, content: bytes) -> NativeTranscriptFacts:
        """Bound input and return normalized facts, never inferred run membership."""
        ...
