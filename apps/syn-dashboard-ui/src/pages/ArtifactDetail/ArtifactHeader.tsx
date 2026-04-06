import {
  Clipboard,
  ClipboardCheck,
  Download,
  FileCode,
  FileText,
  Hash,
  Image,
} from 'lucide-react'

import type { ArtifactResponse } from '../../types'
import { formatSize } from './artifactUtils'

const artifactIcons: Record<string, typeof FileText> = {
  code: FileCode,
  image: Image,
  text: FileText,
  markdown: FileText,
  json: FileCode,
}

interface ArtifactHeaderProps {
  artifact: ArtifactResponse
  copied: boolean
  onCopy: () => void
  onDownload: () => void
}

export function ArtifactHeader({ artifact, copied, onCopy, onDownload }: ArtifactHeaderProps) {
  const Icon = artifactIcons[artifact.artifact_type] ?? FileText

  return (
    <div>
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4 min-w-0">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20">
            <Icon className="h-6 w-6 text-amber-400" />
          </div>
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-[var(--color-text-primary)] break-words">
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
              <span className="font-mono break-all">{artifact.content_hash?.slice(0, 16) ?? 'N/A'}...</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onCopy}
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
            onClick={onDownload}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--color-accent-hover)]"
          >
            <Download className="h-4 w-4" />
            Download
          </button>
        </div>
      </div>
    </div>
  )
}
