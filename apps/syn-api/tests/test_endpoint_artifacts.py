"""Tests for artifact HTTP endpoint wrappers."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from syn_api.routes.artifacts import (
    CreateArtifactRequest,
    create_artifact_endpoint,
    upload_artifact_endpoint,
)
from syn_api.types import ArtifactError, Err, Ok

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
    assert result["id"] == "art-abc-123"
    assert result["title"] == "Test Doc"
    assert result["artifact_type"] == "document"
    assert result["status"] == "created"


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
    assert result["artifact_id"] == "art-1"
    assert result["storage_url"] == "s3://bucket/art-1"
    assert result["status"] == "uploaded"


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
