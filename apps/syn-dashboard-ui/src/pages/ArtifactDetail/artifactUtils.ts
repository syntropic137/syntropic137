import type { BreadcrumbItem } from '../../components/Breadcrumbs'
import type { ArtifactResponse } from '../../types'

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Check if artifact should be rendered as markdown */
export function isMarkdown(artifact: ArtifactResponse): boolean {
  if (artifact.artifact_type === 'markdown') return true
  if (artifact.content_type?.includes('markdown')) return true
  if (artifact.title?.endsWith('.md')) return true
  if (artifact.content) {
    const firstLine = artifact.content.split('\n')[0] || ''
    if (firstLine.startsWith('# ')) return true
  }
  return false
}

export function buildBreadcrumbs(artifact: ArtifactResponse): BreadcrumbItem[] {
  const items: BreadcrumbItem[] = []
  if (artifact.workflow_id) {
    items.push({ label: artifact.workflow_id, href: `/workflows/${artifact.workflow_id}` })
  }
  if (artifact.session_id) {
    items.push({
      label: artifact.phase_id || 'Session',
      href: `/sessions/${artifact.session_id}`,
    })
  }
  items.push({ label: artifact.title || `Artifact ${artifact.id.slice(0, 8)}` })
  return items
}
