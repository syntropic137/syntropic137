/**
 * How a skill's source and version read on screen (#772, #1454).
 *
 * A declared version is whatever the workflow author wrote: usually a full
 * commit SHA, but a tag or branch is legal too, and a local ref
 * (`./skills/repo-conventions`) has no source or version at all. So a SHA is
 * shortened only when it IS one, and a link is built only when the source is
 * a host whose URL scheme for "this repo at this ref" we actually know.
 */

/** A hex string this long is a commit SHA, not a tag that happens to be hex. */
const FULL_SHA = /^[0-9a-f]{12,64}$/i

/** Git's own default abbreviation. */
const SHORT_SHA_LENGTH = 7

/** A full SHA as git abbreviates it; any other ref (a tag, a branch) unchanged. */
export function shortRef(ref: string): string {
  return FULL_SHA.test(ref) ? ref.slice(0, SHORT_SHA_LENGTH) : ref
}

function githubRepoPath(sourceUrl: string): string | null {
  let url: URL
  try {
    url = new URL(sourceUrl)
  } catch {
    return null
  }
  if (url.protocol !== 'https:' || url.hostname !== 'github.com') return null
  const path = url.pathname.replace(/^\/+|\/+$/g, '').replace(/\.git$/, '')
  return /^[^/]+\/[^/]+$/.test(path) ? path : null
}

/** "org/repo" for a GitHub source; the source as given for anything else. */
export function sourceRepoLabel(sourceUrl: string): string {
  return githubRepoPath(sourceUrl) ?? sourceUrl
}

/**
 * The source tree at exactly `ref`, or null when we cannot build one honestly.
 *
 * GitHub only: other hosts spell "tree at ref" differently, and a link that
 * 404s is worse than no link.
 */
export function sourceUrlAtRef(sourceUrl: string, ref: string): string | null {
  const repo = githubRepoPath(sourceUrl)
  if (repo === null || ref === '') return null
  return `https://github.com/${repo}/tree/${encodeURIComponent(ref)}`
}
