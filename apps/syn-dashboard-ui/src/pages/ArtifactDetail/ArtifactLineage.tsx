import { FileText } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader } from '../../components'
import type { ArtifactResponse } from '../../types'

interface ArtifactLineageProps {
  artifact: ArtifactResponse
}

export function ArtifactLineage({ artifact }: ArtifactLineageProps) {
  if (artifact.derived_from.length === 0) return null

  return (
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
  )
}
