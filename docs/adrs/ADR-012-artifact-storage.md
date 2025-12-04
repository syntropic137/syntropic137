# ADR-012: Artifact Storage Architecture

## Status
**Proposed** - Not yet implemented

## Context
Workflow executions generate artifacts (markdown documents, code files, data files) that need to be:
1. Persisted reliably
2. Accessible from any UI instance (not tied to execution host)
3. Efficiently retrievable (potentially large files)
4. Cost-effective at scale

### Current State (Development)
- **Metadata** → PostgreSQL (via projections)
- **Content** → Local filesystem (`.aef-workspaces/`)

This works for single-machine development but **not for production**.

## Decision
Implement a two-tier storage architecture:

### Tier 1: Metadata (PostgreSQL)
Store in the existing projection store:
- `artifact_id` (UUID)
- `workflow_id`, `phase_id`, `session_id`
- `title`, `artifact_type`, `content_type`
- `size_bytes`, `content_hash` (SHA-256)
- `storage_uri` (pointer to content)
- `created_at`, `created_by`

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
