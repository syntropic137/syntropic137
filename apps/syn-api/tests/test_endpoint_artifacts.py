"""Tests for artifact HTTP endpoint wrappers."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from syn_api.routes.artifacts import (
    CreateArtifactRequest,
    create_artifact_endpoint,
    get_artifact_content_endpoint,
    upload_artifact_endpoint,
)
from syn_api.types import ArtifactDetail, ArtifactError, Err, Ok

# --- create_artifact_endpoint ---


async def test_create_artifact_endpoint_success() -> None:
    with patch(
        "syn_api.routes.artifacts.create_artifact",
        new_callable=AsyncMock,
        return_value=Ok("art-abc-123"),
    ):
        result = await create_artifact_endpoint(
            CreateArtifactRequest(
                workflow_id="wf-1",
                artifact_type="document",
                title="Test Doc",
                content="Hello world",
            )
        )
    assert result.id == "art-abc-123"
    assert result.title == "Test Doc"
    assert result.artifact_type == "document"
    assert result.status == "created"


async def test_create_artifact_endpoint_with_optional_fields() -> None:
    with patch(
        "syn_api.routes.artifacts.create_artifact",
        new_callable=AsyncMock,
        return_value=Ok("art-opt"),
    ) as mock_create:
        await create_artifact_endpoint(
            CreateArtifactRequest(
                workflow_id="wf-1",
                artifact_type="code",
                title="Code",
                content="print('hi')",
                phase_id="phase-1",
                session_id="sess-1",
                content_type="text/plain",
            )
        )
    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs["phase_id"] == "phase-1"
    assert kwargs["session_id"] == "sess-1"
    assert kwargs["content_type"] == "text/plain"


async def test_create_artifact_endpoint_service_error() -> None:
    with (
        patch(
            "syn_api.routes.artifacts.create_artifact",
            new_callable=AsyncMock,
            return_value=Err(ArtifactError.STORAGE_ERROR, message="disk full"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await create_artifact_endpoint(
            CreateArtifactRequest(
                workflow_id="wf-1",
                artifact_type="document",
                title="Bad",
                content="x",
            )
        )
    assert exc_info.value.status_code == 400
    assert "disk full" in str(exc_info.value.detail)


# --- upload_artifact_endpoint ---


async def test_upload_artifact_endpoint_success() -> None:
    with patch(
        "syn_api.routes.artifacts.upload_artifact",
        new_callable=AsyncMock,
        return_value=Ok("s3://bucket/art-1"),
    ):
        file = UploadFile(
            filename="test.txt",
            file=BytesIO(b"file content"),
            headers={"content-type": "text/plain"},
        )
        result = await upload_artifact_endpoint("art-1", file)
    assert result.artifact_id == "art-1"
    assert result.storage_url == "s3://bucket/art-1"
    assert result.status == "uploaded"


async def test_upload_artifact_endpoint_service_error() -> None:
    with patch(
        "syn_api.routes.artifacts.upload_artifact",
        new_callable=AsyncMock,
        return_value=Err(ArtifactError.STORAGE_ERROR, message="upload failed"),
    ):
        file = UploadFile(
            filename="test.txt",
            file=BytesIO(b"data"),
            headers={"content-type": "text/plain"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await upload_artifact_endpoint("art-1", file)
    assert exc_info.value.status_code == 400
    assert "upload failed" in str(exc_info.value.detail)


async def test_upload_artifact_endpoint_reads_file_bytes() -> None:
    with patch(
        "syn_api.routes.artifacts.upload_artifact",
        new_callable=AsyncMock,
        return_value=Ok("s3://bucket/art-2"),
    ) as mock_upload:
        file = UploadFile(
            filename="data.bin",
            file=BytesIO(b"binary-content"),
            headers={"content-type": "application/octet-stream"},
        )
        await upload_artifact_endpoint("art-2", file)
    mock_upload.assert_called_once()
    assert mock_upload.call_args.kwargs["data"] == b"binary-content"


async def test_upload_artifact_endpoint_default_filename() -> None:
    with patch(
        "syn_api.routes.artifacts.upload_artifact",
        new_callable=AsyncMock,
        return_value=Ok("s3://bucket/art-3"),
    ) as mock_upload:
        file = UploadFile(
            filename=None,  # type: ignore[arg-type]
            file=BytesIO(b"data"),
        )
        await upload_artifact_endpoint("art-3", file)
    assert mock_upload.call_args.kwargs["filename"] == "upload"


async def test_upload_artifact_endpoint_default_content_type() -> None:
    with patch(
        "syn_api.routes.artifacts.upload_artifact",
        new_callable=AsyncMock,
        return_value=Ok("s3://bucket/art-4"),
    ) as mock_upload:
        file = UploadFile(
            filename="file.dat",
            file=BytesIO(b"data"),
        )
        await upload_artifact_endpoint("art-4", file)
    assert mock_upload.call_args.kwargs["content_type"] == "application/octet-stream"


async def test_upload_artifact_endpoint_rejects_oversized_file() -> None:
    """Upload exceeding 50 MB limit returns 413."""
    oversized = b"x" * (50 * 1024 * 1024 + 1)
    file = UploadFile(filename="big.bin", file=BytesIO(oversized))
    with pytest.raises(HTTPException) as exc_info:
        await upload_artifact_endpoint("art-5", file)
    assert exc_info.value.status_code == 413


# --- get_artifact_content_endpoint ---


async def test_get_artifact_content_endpoint_returns_content() -> None:
    """When storage has the bytes, the endpoint returns 200 with content."""
    detail = ArtifactDetail(
        id="art-ready",
        artifact_type="other",
        content="hello",
        content_type="text/plain",
        size_bytes=5,
    )
    with (
        patch(
            "syn_api.prefix_resolver.resolve_or_raise",
            new_callable=AsyncMock,
            return_value="art-ready",
        ),
        patch("syn_api.routes.artifacts.get_projection_mgr"),
        patch(
            "syn_api.routes.artifacts.get_artifact",
            new_callable=AsyncMock,
            return_value=Ok(detail),
        ),
    ):
        resp = await get_artifact_content_endpoint("art-ready")
    assert resp.artifact_id == "art-ready"
    assert resp.content == "hello"
    assert resp.size_bytes == 5


async def test_get_artifact_content_endpoint_races_returns_202() -> None:
    """Metadata projection lists the artifact but storage upload hasn't landed yet -> 202."""
    detail = ArtifactDetail(
        id="art-racing",
        artifact_type="other",
        content=None,
        content_type="text/plain",
        size_bytes=2303,
    )
    with (
        patch(
            "syn_api.prefix_resolver.resolve_or_raise",
            new_callable=AsyncMock,
            return_value="art-racing",
        ),
        patch("syn_api.routes.artifacts.get_projection_mgr"),
        patch(
            "syn_api.routes.artifacts.get_artifact",
            new_callable=AsyncMock,
            return_value=Ok(detail),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_artifact_content_endpoint("art-racing")
    assert exc_info.value.status_code == 202
    assert "not yet available" in str(exc_info.value.detail)
    assert (exc_info.value.headers or {}).get("Retry-After") == "2"


async def test_get_artifact_content_endpoint_missing_returns_404() -> None:
    """When get_artifact errors (artifact truly missing) the endpoint returns 404."""
    with (
        patch(
            "syn_api.prefix_resolver.resolve_or_raise",
            new_callable=AsyncMock,
            return_value="art-missing",
        ),
        patch("syn_api.routes.artifacts.get_projection_mgr"),
        patch(
            "syn_api.routes.artifacts.get_artifact",
            new_callable=AsyncMock,
            return_value=Err(ArtifactError.NOT_FOUND, message="missing"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_artifact_content_endpoint("art-missing")
    assert exc_info.value.status_code == 404


async def test_get_artifact_content_endpoint_empty_artifact_returns_200() -> None:
    """Zero-byte artifact (content None, size 0) is not a race - return 200."""
    detail = ArtifactDetail(
        id="art-empty",
        artifact_type="other",
        content=None,
        content_type="text/plain",
        size_bytes=0,
    )
    with (
        patch(
            "syn_api.prefix_resolver.resolve_or_raise",
            new_callable=AsyncMock,
            return_value="art-empty",
        ),
        patch("syn_api.routes.artifacts.get_projection_mgr"),
        patch(
            "syn_api.routes.artifacts.get_artifact",
            new_callable=AsyncMock,
            return_value=Ok(detail),
        ),
    ):
        resp = await get_artifact_content_endpoint("art-empty")
    assert resp.size_bytes == 0
    assert resp.content is None
