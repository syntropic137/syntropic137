import { ChevronRight, FileCode, FileText, Image, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { listArtifacts } from '../api/client'
import { Card, CardContent, EmptyState, PageLoader } from '../components'
import type { ArtifactSummary } from '../types'

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

export function ArtifactList() {
  const [searchParams] = useSearchParams()
  const workflowIdFilter = searchParams.get('workflow_id') ?? ''
  const phaseIdFilter = searchParams.get('phase_id') ?? ''

  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    listArtifacts({
      workflow_id: workflowIdFilter || undefined,
      phase_id: phaseIdFilter || undefined,
      artifact_type: typeFilter || undefined,
      limit: 100,
    })
      .then((data) => { if (!cancelled) { setArtifacts(data); setLoading(false) } })
      .catch((err) => { if (!cancelled) { console.error(err); setLoading(false) } })
    return () => { cancelled = true }
  }, [workflowIdFilter, phaseIdFilter, typeFilter])

  const filteredArtifacts = searchQuery
    ? artifacts.filter((a) =>
        a.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        a.title?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : artifacts

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Artifacts</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          Browse workflow outputs and generated files
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            type="text"
            placeholder="Search artifacts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] py-2 pl-10 pr-4 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]"
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]"
        >
          <option value="">All types</option>
          <option value="code">Code</option>
          <option value="text">Text</option>
          <option value="markdown">Markdown</option>
          <option value="json">JSON</option>
          <option value="image">Image</option>
          <option value="other">Other</option>
        </select>
      </div>

      {/* Artifact grid */}
      {loading ? (
        <PageLoader />
      ) : filteredArtifacts.length === 0 ? (
        <Card>
          <EmptyState
            icon={FileText}
            title={searchQuery ? 'No matching artifacts' : 'No artifacts yet'}
            description={
              searchQuery
                ? 'Try adjusting your search query'
                : 'Artifacts will appear here when workflows generate outputs'
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredArtifacts.map((artifact, idx) => {
            const Icon = artifactIcons[artifact.artifact_type] ?? FileText

            return (
              <Link
                key={artifact.id}
                to={`/artifacts/${artifact.id}`}
                className="animate-fade-in"
                style={{ animationDelay: `${idx * 20}ms` }}
              >
                <Card hover className="h-full">
                  <CardContent className="flex flex-col h-full">
                    <div className="flex items-start gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--color-surface-elevated)]">
                        <Icon className="h-5 w-5 text-amber-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                          {artifact.title || `Artifact ${artifact.id.slice(0, 8)}`}
                        </p>
                        <p className="text-xs text-[var(--color-text-muted)]">
                          {artifact.artifact_type} • {formatSize(artifact.size_bytes)}
                        </p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-[var(--color-text-muted)] flex-shrink-0" />
                    </div>
                    <div className="mt-3 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
                      {artifact.workflow_id && (
                        <span>wf:{artifact.workflow_id.slice(0, 8)}</span>
                      )}
                      {artifact.phase_id && <span>{artifact.phase_id}</span>}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

