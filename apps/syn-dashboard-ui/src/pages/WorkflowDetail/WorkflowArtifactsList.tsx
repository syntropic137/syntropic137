import { FileText } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader } from '../../components'
import type { ArtifactSummary } from '../../types'

interface WorkflowArtifactsListProps {
  artifacts: ArtifactSummary[]
  workflowId: string
}

export function WorkflowArtifactsList({ artifacts, workflowId }: WorkflowArtifactsListProps) {
  return (
    <Card>
      <CardHeader
        title="Artifacts"
        subtitle="Generated outputs"
        action={
          artifacts.length > 0 && (
            <Link
              to={`/artifacts?workflow_id=${workflowId}`}
              className="text-xs text-[var(--color-accent)] hover:underline"
            >
              View all →
            </Link>
          )
        }
      />
      <CardContent noPadding>
        {artifacts.length === 0 ? (
          <div className="p-8 text-center">
            <FileText className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">
              No artifacts generated yet
            </p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--color-border)]">
            {artifacts.slice(0, 5).map((artifact) => (
              <Link
                key={artifact.id}
                to={`/artifacts/${artifact.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-[var(--color-surface-elevated)] transition-colors"
              >
                <div className="flex items-center gap-3">
                  <FileText className="h-4 w-4 text-[var(--color-text-secondary)]" />
                  <div>
                    <p className="text-sm font-medium text-[var(--color-text-primary)]">
                      {artifact.title || artifact.id.slice(0, 12)}
                    </p>
                    <p className="text-xs text-[var(--color-text-muted)]">
                      {artifact.artifact_type} • {(artifact.size_bytes / 1024).toFixed(1)} KB
                    </p>
                  </div>
                </div>
                <span className="text-xs text-[var(--color-text-muted)]">
                  {artifact.phase_id}
                </span>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
