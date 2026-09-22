"""Optional replica configuration cannot accidentally require a remote service."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError

from syn_adapters.session_inventory.replication_runtime import create_replication_manager
from syn_shared.settings.session_inventory import SessionInventorySettings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("capture_token", [None, "", "has space", "nonascii-雪", "x" * 4097])
def test_capture_delivery_requires_valid_separate_credential(capture_token: str | None) -> None:
    with pytest.raises(ValidationError):
        SessionInventorySettings(
            _env_file=None,
            replication_enabled=True,
            replication_store_url="https://example.com",
            replication_write_token=SecretStr("inventory-token"),
            capture_replication_enabled=True,
            capture_write_token=None if capture_token is None else SecretStr(capture_token),
        )


async def test_capture_delivery_requires_archive_and_wires_live_worker(tmp_path: Path) -> None:
    binary = tmp_path / "exporter"
    binary.touch()
    settings = SessionInventorySettings(
        _env_file=None,
        archive_dir=tmp_path,
        exporter_binary=binary,
        replication_enabled=True,
        replication_store_url="https://example.com",
        replication_write_token=SecretStr("inventory-token"),
        capture_replication_enabled=True,
        capture_write_token=SecretStr("capture-token"),
    )
    with pytest.raises(ValueError, match="archive storage"):
        create_replication_manager(AsyncMock(), AsyncMock(), "source", settings)
    manager = create_replication_manager(
        AsyncMock(), AsyncMock(), "source", settings, archive=AsyncMock()
    )
    assert manager is not None
    await manager.stop()


def test_disabled_replication_needs_no_token_url_or_binary(tmp_path: Path) -> None:
    settings = SessionInventorySettings(
        _env_file=None, archive_dir=tmp_path, exporter_binary=tmp_path / "absent"
    )
    assert create_replication_manager(AsyncMock(), AsyncMock(), "source", settings) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.com",
        "https://example.com?token=secret",
        "file:///tmp/store",
        "https://example.com#fragment",
    ],
)
def test_replica_configuration_rejects_ambiguous_or_credential_bearing_urls(
    tmp_path: Path, url: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        SessionInventorySettings(
            _env_file=None,
            archive_dir=tmp_path,
            replication_enabled=True,
            replication_store_url=url,
            replication_write_token=SecretStr("token-secret"),
        )
    assert "token-secret" not in str(caught.value)
    assert url not in str(caught.value)


def test_enabled_replication_requires_credentials_and_a_present_exporter(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        SessionInventorySettings(_env_file=None, replication_enabled=True)
    settings = SessionInventorySettings(
        _env_file=None,
        archive_dir=tmp_path,
        replication_enabled=True,
        replication_store_url="https://example.com",
        replication_write_token=SecretStr("token"),
        exporter_binary=tmp_path / "absent",
    )
    with pytest.raises(ValueError, match="does not exist"):
        create_replication_manager(AsyncMock(), AsyncMock(), "source", settings)
