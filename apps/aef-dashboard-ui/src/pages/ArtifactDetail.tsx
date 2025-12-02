import { clsx } from 'clsx'
import {
  ArrowLeft,
  Clipboard,
  ClipboardCheck,
  Download,
  FileCode,
  FileText,
  Hash,
  Image,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { getArtifact } from '../api/client'
import { Card, CardContent, CardHeader, EmptyState, PageLoader } from '../components'
import type { ArtifactResponse } from '../types'

const artifactIcons: Record<string, typeof FileText> = {
  code: FileCode,
  image: Image,
  text: FileText,
  markdown: FileText,
  json: FileCode,
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ArtifactDetail() {
  const { artifactId } = useParams<{ artifactId: string }>()
  const [artifact, setArtifact] = useState<ArtifactResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!artifactId) return

    let cancelled = false
    getArtifact(artifactId, true)
      .then((data) => { if (!cancelled) setArtifact(data) })
      .catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [artifactId])

  const handleCopy = async () => {
    if (!artifact?.content) return
    await navigator.clipboard.writeText(artifact.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = () => {
    if (!artifact?.content) return
    const blob = new Blob([artifact.content], { type: artifact.content_type })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = artifact.title || `artifact-${artifact.id.slice(0, 8)}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  if (loading) return <PageLoader />

  if (error || !artifact) {
    return (
      <Card>
        <EmptyState
          icon={FileText}
          title="Artifact not found"
          description={error || `Could not find artifact with ID: ${artifactId}`}
        />
      </Card>
    )
  }

  const Icon = artifactIcons[artifact.artifact_type] ?? FileText

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link
          to="/artifacts"
          className="inline-flex items-center gap-1 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Artifacts
        </Link>
        <div className="mt-4 flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20">
              <Icon className="h-6 w-6 text-amber-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
                {artifact.title || `Artifact ${artifact.id.slice(0, 12)}`}
              </h1>
              <div className="mt-2 flex items-center gap-4 text-sm text-[var(--color-text-secondary)]">
                <span>{artifact.artifact_type}</span>
                <span>•</span>
                <span>{artifact.content_type}</span>
                <span>•</span>
                <span>{formatSize(artifact.size_bytes)}</span>
              </div>
              <div className="mt-1 flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                <Hash className="h-3 w-3" />
                <span className="font-mono">{artifact.content_hash?.slice(0, 16) ?? 'N/A'}...</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)] hover:text-[var(--color-text-primary)]"
            >
              {copied ? (
                <>
                  <ClipboardCheck className="h-4 w-4 text-emerald-400" />
                  Copied!
                </>
              ) : (
                <>
                  <Clipboard className="h-4 w-4" />
                  Copy
                </>
              )}
            </button>
            <button
              onClick={handleDownload}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--color-accent-hover)]"
            >
              <Download className="h-4 w-4" />
              Download
            </button>
          </div>
        </div>
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {artifact.workflow_id && (
          <Card>
            <CardContent>
              <p className="text-xs text-[var(--color-text-muted)]">Workflow</p>
              <Link
                to={`/workflows/${artifact.workflow_id}`}
                className="mt-1 text-sm font-medium text-[var(--color-accent)] hover:underline"
              >
                {artifact.workflow_id.slice(0, 16)}...
              </Link>
            </CardContent>
          </Card>
        )}
        {artifact.phase_id && (
          <Card>
            <CardContent>
              <p className="text-xs text-[var(--color-text-muted)]">Phase</p>
              <p className="mt-1 text-sm font-medium text-[var(--color-text-primary)]">
                {artifact.phase_id}
              </p>
            </CardContent>
          </Card>
        )}
        {artifact.session_id && (
          <Card>
            <CardContent>
              <p className="text-xs text-[var(--color-text-muted)]">Session</p>
              <Link
                to={`/sessions/${artifact.session_id}`}
                className="mt-1 text-sm font-medium text-[var(--color-accent)] hover:underline"
              >
                {artifact.session_id.slice(0, 16)}...
              </Link>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Lineage */}
      {artifact.derived_from.length > 0 && (
        <Card>
          <CardHeader title="Derived From" subtitle="Parent artifacts this was generated from" />
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {artifact.derived_from.map((parentId) => (
                <Link
                  key={parentId}
                  to={`/artifacts/${parentId}`}
                  className="inline-flex items-center gap-1 rounded-md bg-[var(--color-surface-elevated)] px-2 py-1 text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-accent)]/10 hover:text-[var(--color-accent)]"
                >
                  <FileText className="h-3 w-3" />
                  {parentId.slice(0, 12)}...
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Content */}
      <Card>
        <CardHeader title="Content" subtitle="Artifact content preview" />
        <CardContent noPadding>
          {artifact.content ? (
            <div className="relative">
              <pre
                className={clsx(
                  'overflow-auto p-4 text-sm text-[var(--color-text-secondary)]',
                  'max-h-[600px] font-mono'
                )}
              >
                <code>{artifact.content}</code>
              </pre>
            </div>
          ) : (
            <div className="p-8 text-center">
              <FileText className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
              <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                Content not available for preview
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

