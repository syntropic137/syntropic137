"""#2107: only owner-requested tombstones may reach a replica."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
from pydantic import SecretStr

from syn_adapters.session_inventory.capture_deletion_worker import PROPAGATED_REASONS
from syn_adapters.session_inventory.capture_outboxes import ExporterDeletionOutbox
from syn_adapters.session_inventory.exporter_transport import ExporterConfig
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


async def test_deletion_outbox_discard_withdraws_the_queued_delete(tmp_path: Path) -> None:
    outbox = tmp_path / "capture-deletions"
    (outbox / "queue").mkdir(parents=True)
    (outbox / "queue" / "entry").write_bytes(b"queued delete")
    transport = ExporterDeletionOutbox(
        ExporterConfig(
            binary=Path("/fixture/exporter"),
            outbox_dir=outbox,
            store_url="http://127.0.0.1:1",
            token=SecretStr("test-only"),
        )
    )
    await transport.discard()
    assert not outbox.exists()
    await transport.discard()  # idempotent
