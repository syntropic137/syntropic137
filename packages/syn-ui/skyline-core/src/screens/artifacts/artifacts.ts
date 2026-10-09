/**
 * Artifacts screen helpers (boards: Artifacts, Artifact). The API title is
 * often "<phase label>: <path>" ("Open the pull request: artifacts/output/pr-body.md");
 * the boards show a short name in bold with the path in mono under it.
 */

export interface ArtifactName {
  /** Bold line: the file name when the title carries a path, else the title. */
  name: string
  /** The human label before the path, when the title had one ("Open the pull request"). */
  label: string | null
  /** The file path, from metadata or the title. Null when neither has one. */
  path: string | null
}

const TITLE_PATH = /^(.*?):\s+(\S*\/\S+)$/

/** Last path segment; the path itself when it has no slash. */
export function baseName(path: string): string {
  const parts = path.split('/').filter(Boolean)
  return parts[parts.length - 1] ?? path
}

/** Split an artifact title into a short name, its label and its path. `metaPath` (metadata.path) wins over a path in the title. */
export function artifactName(title: string | null | undefined, metaPath?: string | null, fallback = ''): ArtifactName {
  const t = (title ?? '').trim()
  const m = TITLE_PATH.exec(t)
  const label = m ? (m[1] ?? '').trim() || null : null
  const path = metaPath || (m ? (m[2] ?? null) : null)
  if (path) return { name: baseName(path), label: label ?? (t && !m && t !== path ? t : null), path }
  return { name: t || fallback, label: null, path: null }
}

/** Glyph family for an artifact type: doc, code or data. Drives the card icon only. */
export type ArtifactGlyph = 'doc' | 'code' | 'data'

export function artifactGlyph(type: string, path?: string | null): ArtifactGlyph {
  if (/code|patch|diff/.test(type) || /\.(py|ts|js|rs|go|diff|patch|sh)$/i.test(path ?? '')) return 'code'
  if (/json|data|csv|yaml/.test(type) || /\.(json|csv|ya?ml)$/i.test(path ?? '')) return 'data'
  return 'doc'
}
