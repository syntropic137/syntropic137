# artifacts

Artifact storage and retrieval.

**Status:** Implemented — list, get, create, and upload operations with event-sourced aggregate and artifact storage.

## list_artifacts()

List artifacts, optionally filtered, as one page of a known collection.

**Signature:**

```python
async def list_artifacts(
    workflow_id: str | None = None,
    session_id: str | None = None,
    phase_id: str | None = None,
    artifact_type: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    search: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> Result[Page[ArtifactSummary], ArtifactError]
```

Returns a `Page` - rows plus the `total` and the per-type facet counts, each
counted over every filter - rather than a bare list (#1204). `DEFAULT_PAGE_SIZE`
is 50.

---

## create_artifact()

Create a new artifact.

**Signature:**

```python
async def create_artifact(
    workflow_id: str,
    artifact_type: str,
    title: str,
    content: str,
    phase_id: str | None = None,
    session_id: str | None = None,
    content_type: str = "text/markdown",
    auth: AuthContext | None = None,
) -> Result[str, ArtifactError]
```

---

## upload_artifact()

Upload binary content for an existing artifact.

**Signature:**

```python
async def upload_artifact(
    artifact_id: str,
    data: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    auth: AuthContext | None = None,
) -> Result[str, ArtifactError]
```
