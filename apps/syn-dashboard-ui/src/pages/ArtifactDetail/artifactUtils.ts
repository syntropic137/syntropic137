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

/**
 * The backend's binary `ContentType` members (#990). Their JSON `content` is
 * always null: the bytes are only served by `/raw`.
 */
const BINARY_CONTENT_TYPES: ReadonlySet<string> = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'application/pdf',
  'application/octet-stream',
])

/** Check if artifact is bytes with no text form, so is read from `/raw` */
export function isBinary(artifact: ArtifactResponse): boolean {
  return BINARY_CONTENT_TYPES.has(artifact.content_type)
}

/** Check if artifact should be rendered as an image from its bytes */
export function isImage(artifact: ArtifactResponse): boolean {
  return isBinary(artifact) && artifact.content_type.startsWith('image/')
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
