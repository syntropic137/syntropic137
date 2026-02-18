# Supabase Local Development Setup

This directory contains configuration for running Supabase locally for object storage development.

## Quick Start

```bash
# Start main AEF services first
just dev

# Then add Supabase services
docker compose -f docker/docker-compose.dev.yaml -f docker/docker-compose.supabase.yaml up -d
```

## Services

| Service | URL | Description |
|---------|-----|-------------|
| Supabase API | http://localhost:54321 | Main Supabase API endpoint |
| Supabase Studio | http://localhost:54323 | Admin UI |
| Supabase DB | localhost:54329 | PostgreSQL (separate from AEF DB) |

## Environment Variables

Add these to your `.env` file:

```bash
# Object Storage Configuration
SYN_STORAGE_PROVIDER=supabase
SYN_STORAGE_SUPABASE_URL=http://localhost:54321
SYN_STORAGE_SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU
SYN_STORAGE_BUCKET_NAME=syn-artifacts
```

## Default Credentials

For local development only:

- **Anon Key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0`
- **Service Role Key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU`

⚠️ **Never use these keys in production!**

## Bucket Structure

Artifacts are stored with the following key structure:

```
workflows/{workflow_id}/bundles/{bundle_id}/{filename}
workflows/{workflow_id}/bundles/{bundle_id}/manifest.json
```

## Usage in Code

```python
from syn_adapters.object_storage import get_storage

# Get storage (auto-selects based on SYN_STORAGE_PROVIDER)
storage = await get_storage()

# Upload artifact
result = await storage.upload(
    "workflows/123/bundles/abc/report.md",
    report_content.encode()
)

# Download artifact
content = await storage.download("workflows/123/bundles/abc/report.md")

# List artifacts
artifacts = await storage.list_objects("workflows/123/bundles/abc/")
```

## Troubleshooting

### Storage API not responding

Check if Kong is running:
```bash
docker logs aef-supabase-kong
```

### Bucket not found

The `syn-artifacts` bucket is created automatically by the init script.
If missing, create it in Studio at http://localhost:54323.

### Authentication errors

Ensure you're using the **service_role** key, not the anon key.
