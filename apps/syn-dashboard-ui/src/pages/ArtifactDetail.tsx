import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { Card, EmptyState, PageLoader } from '../components'
import { useArtifactData } from '../hooks/useArtifactData'
import { ArtifactContentViewer } from './ArtifactDetail/ArtifactContentViewer'
import { ArtifactHeader } from './ArtifactDetail/ArtifactHeader'
import { ArtifactLineage } from './ArtifactDetail/ArtifactLineage'
import { ArtifactMetadata } from './ArtifactDetail/ArtifactMetadata'
import { buildBreadcrumbs } from './ArtifactDetail/artifactUtils'
import { Breadcrumbs } from '../components'
import { FileText } from 'lucide-react'

export function ArtifactDetail() {
  const { artifactId } = useParams<{ artifactId: string }>()
  const { artifact, loading, error } = useArtifactData(artifactId)
  const [copied, setCopied] = useState(false)
  const [viewMode, setViewMode] = useState<'rendered' | 'raw'>('rendered')

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

  const handleCopy = async () => {
    if (!artifact.content) return
    await navigator.clipboard.writeText(artifact.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = () => {
    if (!artifact.content) return
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

  return (
    <div className="space-y-6">
      <Breadcrumbs items={buildBreadcrumbs(artifact)} />
      <ArtifactHeader
        artifact={artifact}
        copied={copied}
        onCopy={handleCopy}
        onDownload={handleDownload}
      />
      <ArtifactMetadata artifact={artifact} />
      <ArtifactLineage artifact={artifact} />
      <ArtifactContentViewer
        artifact={artifact}
        viewMode={viewMode}
        setViewMode={setViewMode}
      />
    </div>
  )
}
