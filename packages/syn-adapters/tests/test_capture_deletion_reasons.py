"""#2107: only owner-requested tombstones may reach a replica."""

from __future__ import annotations

from typing import get_args

import pytest

from syn_adapters.session_inventory.capture_deletion_worker import PROPAGATED_REASONS
from syn_domain.contexts.agent_sessions.domain.read_models.transcript_body_state import (
    BodyDeletionReason,
    OwnerDeletionReason,
)

pytestmark = pytest.mark.unit


def test_only_owner_reasons_propagate_to_replicas() -> None:
    assert set(PROPAGATED_REASONS) == {"deletion", "retraction"}
    assert set(PROPAGATED_REASONS) == set(get_args(OwnerDeletionReason))


def test_every_automatic_expiry_reason_is_excluded() -> None:
    automatic = set(get_args(BodyDeletionReason)) - set(get_args(OwnerDeletionReason))
    assert automatic == {"retention_age", "retention_quota"}
    assert automatic.isdisjoint(PROPAGATED_REASONS)
