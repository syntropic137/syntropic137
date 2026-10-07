/**
 * How a skill's source and version read on screen (#772, #1454).
 *
 * A declared version is whatever the workflow author wrote: usually a full
 * commit SHA, but a tag or branch is legal too, and a local ref
 * (`./skills/repo-conventions`) has no source or version at all. So a SHA is
 * shortened only when it IS one, and a link is built only when the source is
 * a host whose URL scheme for "this repo at this ref" we actually know.
 *
 * A pinned skill's `resolved_sha` is NOT a git ref: the server computes it as
 * a SHA-256 over the skill's files (`_compute_tree_sha`), so it is shown as a
 * content digest and never linked. Nor is a `sha256-<hash>` version.
 */

/** A hex string this long is a commit SHA, not a tag that happens to be hex. */
const FULL_SHA = /^[0-9a-f]{12,64}$/i

/** A version pinned by content hash, not by a git ref (`RegisterSkillHandler`). */
const CONTENT_HASH_VERSION_PREFIX = 'sha256-'

/** Git's own default abbreviation. */
const SHORT_SHA_LENGTH = 7

/** A full SHA as git abbreviates it; any other ref (a tag, a branch) unchanged. */
export function shortRef(ref: string): string {
  return FULL_SHA.test(ref) ? ref.slice(0, SHORT_SHA_LENGTH) : ref
}

/** `git@github.com:org/repo`, the scp-like spelling git uses for ssh. */
const GITHUB_SCP = /^git@github\.com:(.+)$/

/** The `org/repo` a GitHub source names, over https or either ssh spelling. */
function githubRepoPath(sourceUrl: string): string | null {
  const scp = GITHUB_SCP.exec(sourceUrl)
  let path: string
  if (scp) {
    path = scp[1]
  } else {
    let url: URL
    try {
      url = new URL(sourceUrl)
    } catch {
      return null
    }
    const transport = ['https:', 'ssh:', 'git+ssh:'].includes(url.protocol)
    if (!transport || url.hostname !== 'github.com') return null
    path = url.pathname
  }
  path = path.replace(/^\/+|\/+$/g, '').replace(/\.git$/, '')
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
 * 404s is worse than no link. An ssh source gets an https link: the browser
 * cannot follow the transport, but it names the same repo.
 */
export function sourceUrlAtRef(sourceUrl: string, ref: string): string | null {
  const repo = githubRepoPath(sourceUrl)
  if (repo === null || ref === '' || ref.startsWith(CONTENT_HASH_VERSION_PREFIX)) return null
  return `https://github.com/${repo}/tree/${encodeURIComponent(ref)}`
}
