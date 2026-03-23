import { FileText } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader } from '../../components'
import type { ArtifactResponse, ExecutionDetailResponse } from '../../types'

interface ArtifactSectionProps {
  phases: ExecutionDetailResponse['phases']
  artifactDetails: Record<string, ArtifactResponse>
}

export function ArtifactSection({ phases, artifactDetails }: ArtifactSectionProps) {
  return (
    <Card>
      <CardHeader
        title="Artifacts"
        subtitle={`${Object.keys(artifactDetails).length || phases.filter(p => p.artifact_id).length} artifact${phases.filter(p => p.artifact_id).length === 1 ? '' : 's'} produced`}
      />
      <CardContent>
        <div className="space-y-2">
          {phases
            .filter((p) => p.artifact_id)
            .map((p) => {
              const detail = artifactDetails[p.artifact_id!]
              return (
                <Link
                  key={p.artifact_id}
                  to={`/artifacts/${p.artifact_id}`}
                  className="flex items-center gap-3 p-3 rounded-lg border border-[var(--color-border)] hover:bg-[var(--color-surface-elevated)] transition-colors group"
                >
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-accent)]/10 shrink-0">
                    <FileText className="h-4 w-4 text-[var(--color-accent)]" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                      {detail?.title ?? `${p.name} output`}
                    </p>
                    <p className="text-xs text-[var(--color-text-muted)] font-mono truncate">
                      {p.artifact_id}
                    </p>
                  </div>
                  {detail && (
                    <span className="text-xs text-[var(--color-text-muted)] shrink-0">
                      {(detail.size_bytes / 1024).toFixed(1)} KB
                    </span>
                  )}
                  <span className="text-[var(--color-accent)] opacity-0 group-hover:opacity-100 transition-opacity text-sm">→</span>
                </Link>
              )
            })}
        </div>
      </CardContent>
    </Card>
  )
}
