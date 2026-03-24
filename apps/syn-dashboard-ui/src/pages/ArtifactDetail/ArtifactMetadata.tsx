import { Link } from 'react-router-dom'

import { Card, CardContent } from '../../components'
import type { ArtifactResponse } from '../../types'

interface ArtifactMetadataProps {
  artifact: ArtifactResponse
}

export function ArtifactMetadata({ artifact }: ArtifactMetadataProps) {
  return (
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
  )
}
