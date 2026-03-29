# artifacts

Artifact storage and retrieval.

**Status:** Implemented — CRUD operations with event-sourced aggregate and artifact storage.

## list_artifacts()

List artifacts, optionally filtered by workflow or session.

**Signature:**

```python
async def list_artifacts(
    workflow_id: str | None = None,
    session_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[ArtifactSummary], ArtifactError]
```

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
