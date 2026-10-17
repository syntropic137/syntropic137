"""feedback_sources read model: what Intake verifies a signed request against (ADR-076-feedback-ticketing)."""

from syn_domain.contexts.feedback.slices.feedback_sources.projection import (
    FeedbackSource,
    FeedbackSourcesProjection,
)

__all__ = ["FeedbackSource", "FeedbackSourcesProjection"]
