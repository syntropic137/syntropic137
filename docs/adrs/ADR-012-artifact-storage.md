# ADR-012: Artifact Storage Architecture

## Status
**Partially Implemented** - Core domain and query service implemented

## Context
Workflow executions generate artifacts (markdown documents, code files, data files) that need to be:
1. Persisted reliably
2. Accessible from any UI instance (not tied to execution host)
3. Efficiently retrievable (potentially large files)
4. Cost-effective at scale
5. **Linked to execution runs** for phase-to-phase injection

### Current State (Development)
- **Metadata** → PostgreSQL (via projections)
- **Content** → Event store (via ArtifactCreatedEvent)

### Critical Design Decision (2025-12)
**Phase outputs are NOT stored in-memory.** They are:
1. Persisted as `ArtifactCreatedEvent` with `execution_id` linking
2. Queried via `ArtifactQueryService` when building next phase's prompt
3. Never stored in mutable context (crash-safe, auditable)

This follows the same principle as LocalWorkspace: in-memory state is TEST ONLY.

## Decision
Implement a two-tier storage architecture:

### Tier 1: Metadata + Content (Event Store & Projections)
Store in the event store and project to read models:
- `artifact_id` (UUID)
- `workflow_id`, `phase_id`, `session_id`
- **`execution_id`** (NEW - links to specific workflow run)
- `title`, `artifact_type`, `content_type`
- `size_bytes`, `content_hash` (SHA-256)
- `content` (stored in event, projected for queries)
- `storage_uri` (pointer to external content, for large files)
- `created_at`

### ArtifactQueryService

```python
# Query artifacts for phase-to-phase injection
class ArtifactQueryService:
    """Service for querying artifacts from projection store."""

    async def get_by_execution(self, execution_id: str) -> list[ArtifactSummary]:
        """Get all artifacts for a specific execution run."""
        ...

    async def get_for_phase_injection(
        self,
        execution_id: str,
        completed_phase_ids: list[str],
    ) -> dict[str, str]:
        """Get phase outputs for prompt template substitution."""
        ...
```

This service is injected into `WorkflowExecutionEngine` to retrieve previous
phase outputs when building the next phase's prompt.

### Tier 2: Content (Object Storage - Future)

### Tier 2: Content (Object Storage)
Store actual file content in S3-compatible storage:
- **Recommended**: Supabase Storage (S3-compatible, pairs with Supabase PostgreSQL)
- **Alternative**: AWS S3 or Google Cloud Storage
- **Self-hosted**: MinIO (S3-compatible) - secondary option
- **Development**: Local filesystem fallback or Supabase free tier

### Storage URI Format
```
s3://aef-artifacts/{tenant_id}/{workflow_id}/{phase_id}/{artifact_id}/{filename}
```

### Access Pattern
```python
# Store artifact
async def store_artifact(artifact_id: str, content: bytes, metadata: dict) -> str:
    # 1. Upload to S3
    storage_uri = await s3_client.put_object(
        bucket="aef-artifacts",
        key=f"{workflow_id}/{phase_id}/{artifact_id}/output.md",
        body=content,
        content_type="text/markdown",
    )

    # 2. Store metadata with URI
    await projection_store.save("artifacts", artifact_id, {
        **metadata,
        "storage_uri": storage_uri,
        "content_hash": hashlib.sha256(content).hexdigest(),
    })

    return storage_uri

# Retrieve artifact
async def get_artifact_content(artifact_id: str) -> bytes:
    # 1. Get metadata
    metadata = await projection_store.get("artifacts", artifact_id)

    # 2. Generate presigned URL or fetch content
    if presigned_urls_enabled:
        return await s3_client.generate_presigned_url(metadata["storage_uri"])
    else:
        return await s3_client.get_object(metadata["storage_uri"])
```

## Consequences

### Positive
- UI can run anywhere (not tied to execution host)
- Horizontal scaling possible
- Large artifacts handled efficiently
- Built-in redundancy (S3 durability)
- Presigned URLs enable direct browser downloads

### Negative
- Additional infrastructure (S3/MinIO)
- Network latency for content retrieval
- Cost for storage and egress

### Neutral
- Need to handle S3 credentials/IAM
- Migration path from filesystem needed

## Implementation Plan

### ✅ Phase 0: Execution ID Linking (COMPLETED)
1. ✅ Add `execution_id` to `ArtifactCreatedEvent` (v2)
2. ✅ Add `execution_id` to `CreateArtifactCommand`
3. ✅ Add `execution_id` to `ArtifactAggregate`
4. ✅ Update `ArtifactSummary` read model
5. ✅ Update `ArtifactListProjection` with:
   - `get_by_execution()` query
   - `get_by_execution_and_phase()` query
   - `execution_id` filter in `query()`

### ✅ Phase 0.5: ArtifactQueryService (COMPLETED)
1. ✅ Create `ArtifactQueryService` for DB-backed queries
2. ✅ Add `get_for_phase_injection()` for prompt substitution
3. ✅ Remove in-memory `phase_outputs` from `ExecutionContext`
4. ✅ Update `WorkflowExecutionEngine._build_prompt()` to use service
5. ✅ Add comprehensive tests

### Phase 1: MinIO for Development
1. Add MinIO to `docker-compose.dev.yaml`
2. Create `ArtifactStorageProtocol` interface
3. Implement `MinioArtifactStorage`
4. Update `_persist_artifact` to upload content

### Phase 2: Production S3
1. Add AWS SDK dependencies
2. Implement `S3ArtifactStorage`
3. Add IAM role configuration
4. Enable presigned URLs

### Phase 3: Migration
1. Create migration script for existing filesystem artifacts
2. Update API to read from both sources during migration
3. Remove filesystem fallback

### Phase 4: Reference Artifacts (Future)
Support artifacts that are pointers to external resources:
- GitHub commits, PRs, issues, files, branches
- External URLs
- File paths

```python
class ArtifactType(Enum):
    # Content artifacts
    TEXT = "text"
    MARKDOWN = "markdown"
    CODE = "code"
    # ...

    # Reference artifacts (pointers)
    GITHUB_COMMIT = "github_commit"
    GITHUB_PR = "github_pr"
    GITHUB_ISSUE = "github_issue"
    GITHUB_FILE = "github_file"
    GITHUB_BRANCH = "github_branch"
    URL = "url"
    FILE_PATH = "file_path"
```

## Alternatives Considered

### Store in PostgreSQL (bytea)
- ❌ Not designed for large binary data
- ❌ Bloats database backups
- ❌ No streaming support

### Store in Event Store
- ❌ Events should be immutable facts, not file storage
- ❌ Would bloat event streams

### Keep Filesystem with NFS/EFS
- ⚠️ Possible but complex to manage
- ⚠️ Performance issues at scale
- ✅ Simpler for small deployments

## References
- [AWS S3 Best Practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html)
- [MinIO Documentation](https://min.io/docs/minio/linux/index.html)
- [Presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html)
