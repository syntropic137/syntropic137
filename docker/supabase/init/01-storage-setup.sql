-- Supabase Storage Initialization
-- Creates the syn-artifacts bucket for artifact storage
--
-- NOTE: This is for LOCAL DEVELOPMENT only. The RLS policies here are
-- permissive for ease of development. In production, implement proper
-- per-user/per-tenant authorization using auth.uid() or similar.

-- Insert default bucket for AEF artifacts
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'syn-artifacts',
    'syn-artifacts',
    false,  -- Private bucket, requires auth
    52428800,  -- 50MB max file size
    ARRAY[
        'text/plain',
        'text/markdown',
        'text/html',
        'application/json',
        'application/yaml',
        'application/x-yaml',
        'application/octet-stream',
        'image/png',
        'image/jpeg',
        'image/gif'
    ]::text[]
)
ON CONFLICT (id) DO NOTHING;

-- Create storage policies for the bucket (idempotent)
-- Allow service role full access
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'storage'
          AND tablename = 'objects'
          AND policyname = 'Service role can manage all artifacts'
    ) THEN
        CREATE POLICY "Service role can manage all artifacts"
        ON storage.objects
        FOR ALL
        TO service_role
        USING (bucket_id = 'syn-artifacts')
        WITH CHECK (bucket_id = 'syn-artifacts');
    END IF;
END $$;

-- Allow authenticated users to read workflow artifacts
-- NOTE: For production, add auth.uid() scoping for per-user access control
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'storage'
          AND tablename = 'objects'
          AND policyname = 'Users can read their workflow artifacts'
    ) THEN
        CREATE POLICY "Users can read their workflow artifacts"
        ON storage.objects
        FOR SELECT
        TO authenticated
        USING (
            bucket_id = 'syn-artifacts'
            AND (storage.foldername(name))[1] = 'workflows'
        );
    END IF;
END $$;

-- Log that storage is initialized
DO $$
BEGIN
    RAISE NOTICE 'AEF artifact storage bucket created successfully';
END $$;
