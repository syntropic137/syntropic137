/**
 * Artifacts page — composition only.
 *
 * Mirrors the Executions page: heading + connection indicator, search, a
 * filter row, and the shared pager. The pager is the point of #1204: before
 * it, one page of artifacts rendered with no statement of what it was a page
 * OF, and there was no interaction that reached row 201.
 *
 * Artifacts carry no status, so the status chips do not apply here; the
 * dimension operators filter on is the artifact type, and its counts come
 * from the server over the whole collection.
 */

import { ChevronRight, FileCode, FileText, Image } from 'lucide-react'
import { Link } from 'react-router-dom'

import {
  Card,
  CardContent,
  EmptyState,
  ListPageHeader,
  ListPagination,
  ListToolbar,
  PageLoader,
  TimeWindowPicker,
} from '../components'
import { useArtifactList } from '../hooks/useArtifactList'
import type { ArtifactSummary } from '../types'

const artifactIcons: Record<string, typeof FileText> = {
  code: FileCode,
  image: Image,
  text: FileText,
  markdown: FileText,
  json: FileCode,
}

const TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'code', label: 'Code' },
  { value: 'text', label: 'Text' },
  { value: 'markdown', label: 'Markdown' },
  { value: 'json', label: 'JSON' },
  { value: 'image', label: 'Image' },
  { value: 'other', label: 'Other' },
]

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function ArtifactCard({ artifact, idx }: { artifact: ArtifactSummary; idx: number }) {
  const Icon = artifactIcons[artifact.artifact_type] ?? FileText

  return (
    <Link
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
                {artifact.artifact_type} &bull; {formatSize(artifact.size_bytes)}
              </p>
            </div>
            <ChevronRight className="h-4 w-4 text-[var(--color-text-muted)] flex-shrink-0" />
          </div>
          <div className="mt-3 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
            {artifact.workflow_id && <span>wf:{artifact.workflow_id.slice(0, 8)}</span>}
            {artifact.phase_id && <span>{artifact.phase_id}</span>}
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

export function ArtifactList() {
  const {
    artifacts,
    loading,
    searchQuery,
    setSearchQuery,
    typeFilter,
    setTypeFilter,
    typeCounts,
    timeWindow,
    setTimeWindow,
    page,
    pageSize,
    total,
    excludedUndated,
    setPage,
    connected,
    lastEventAt,
  } = useArtifactList()

  return (
    <div className="space-y-6">
      <ListPageHeader
        title="Artifacts"
        description="Browse workflow outputs and generated files"
        connected={connected}
        lastEventAt={lastEventAt}
      />

      <ListToolbar
        searchPlaceholder="Search artifacts..."
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
      />

      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <select
          aria-label="Artifact type"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]"
        >
          <option value="">All types</option>
          {TYPE_OPTIONS.map((t) => (
            <option key={t.value} value={t.value}>
              {/* Counted by the server over the collection, so an unselected
                  option says what selecting it would get you. */}
              {typeCounts[t.value] ? `${t.label} (${typeCounts[t.value]})` : t.label}
            </option>
          ))}
        </select>
        <TimeWindowPicker value={timeWindow} onChange={setTimeWindow} />
      </div>

      {loading ? (
        <PageLoader />
      ) : artifacts.length === 0 ? (
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
          {artifacts.map((artifact, idx) => (
            <ArtifactCard key={artifact.id} artifact={artifact} idx={idx} />
          ))}
        </div>
      )}

      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        excludedUndated={excludedUndated}
        onPageChange={setPage}
        itemLabel="artifact"
      />
    </div>
  )
}
