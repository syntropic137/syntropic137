"""Tests for aef_api.v1.artifacts — stub functions return NOT_IMPLEMENTED.

All artifact operations are stubs in Phase 1.
"""

from aef_api.types import ArtifactError, Err


async def test_list_artifacts_not_implemented():
    """list_artifacts returns NOT_IMPLEMENTED."""
    from aef_api.v1.artifacts import list_artifacts

    result = await list_artifacts()
    assert isinstance(result, Err)
    assert result.error == ArtifactError.NOT_IMPLEMENTED


async def test_create_artifact_not_implemented():
    """create_artifact returns NOT_IMPLEMENTED."""
    from aef_api.v1.artifacts import create_artifact

    result = await create_artifact(
        workflow_id="wf-1",
        artifact_type="code",
        title="test",
        content="hello",
    )
    assert isinstance(result, Err)
    assert result.error == ArtifactError.NOT_IMPLEMENTED


async def test_upload_artifact_not_implemented():
    """upload_artifact returns NOT_IMPLEMENTED."""
    from aef_api.v1.artifacts import upload_artifact

    result = await upload_artifact(
        artifact_id="art-1",
        data=b"bytes",
        filename="test.txt",
    )
    assert isinstance(result, Err)
    assert result.error == ArtifactError.NOT_IMPLEMENTED
