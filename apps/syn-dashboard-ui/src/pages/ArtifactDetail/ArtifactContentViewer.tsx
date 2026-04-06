import { clsx } from 'clsx'
import { Code, Eye, FileText } from 'lucide-react'

import { Card, CardContent, CardHeader } from '../../components'
import { MarkdownViewer } from '../../components/MarkdownViewer'
import type { ArtifactResponse } from '../../types'
import { isMarkdown } from './artifactUtils'

interface ArtifactContentViewerProps {
  artifact: ArtifactResponse
  viewMode: 'rendered' | 'raw'
  setViewMode: (mode: 'rendered' | 'raw') => void
}

function ViewModeToggle({
  viewMode,
  setViewMode,
}: {
  viewMode: 'rendered' | 'raw'
  setViewMode: (mode: 'rendered' | 'raw') => void
}) {
  return (
    <div className="flex items-center gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5">
      <button
        onClick={() => setViewMode('rendered')}
        className={clsx(
          'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
          viewMode === 'rendered'
            ? 'bg-[var(--color-accent)] text-white'
            : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
        )}
      >
        <Eye className="h-3.5 w-3.5" />
        Rendered
      </button>
      <button
        onClick={() => setViewMode('raw')}
        className={clsx(
          'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
          viewMode === 'raw'
            ? 'bg-[var(--color-accent)] text-white'
            : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
        )}
      >
        <Code className="h-3.5 w-3.5" />
        Raw
      </button>
    </div>
  )
}

function ContentPreview({
  artifact,
  viewMode,
}: {
  artifact: ArtifactResponse
  viewMode: 'rendered' | 'raw'
}) {
  if (!artifact.content) {
    return (
      <div className="p-8 text-center">
        <FileText className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          Content not available for preview
        </p>
      </div>
    )
  }

  if (isMarkdown(artifact) && viewMode === 'rendered') {
    return (
      <div className="p-4 max-h-[800px] overflow-auto min-w-0">
        <MarkdownViewer content={artifact.content} />
      </div>
    )
  }

  return (
    <div className="relative min-w-0 overflow-hidden">
      <pre
        className={clsx(
          'overflow-auto p-4 text-sm text-[var(--color-text-secondary)]',
          'max-h-[600px] font-mono whitespace-pre-wrap break-words'
        )}
      >
        <code>{artifact.content}</code>
      </pre>
    </div>
  )
}

export function ArtifactContentViewer({ artifact, viewMode, setViewMode }: ArtifactContentViewerProps) {
  const showToggle = artifact.content && isMarkdown(artifact)

  return (
    <Card>
      <CardHeader
        title="Content"
        subtitle="Artifact content preview"
        action={showToggle ? <ViewModeToggle viewMode={viewMode} setViewMode={setViewMode} /> : undefined}
      />
      <CardContent noPadding>
        <ContentPreview artifact={artifact} viewMode={viewMode} />
      </CardContent>
    </Card>
  )
}
