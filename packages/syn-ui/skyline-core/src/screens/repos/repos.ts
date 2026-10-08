/**
 * Repos screen: merge registered repos, systems and GitHub App reach into
 * rows. Ported from apps/syn-dashboard-ui/src/hooks/useRepoList.ts.
 */

export type RepoAttachment = 'attached' | 'not-attached' | 'unknown'
export type RepoPrivacy = 'private' | 'public' | 'unknown'

export interface RegisteredRepo {
  repo_id: string
  full_name?: string | null
  provider?: string | null
  system_id?: string | null
  is_private?: boolean | null
  default_branch?: string | null
  created_at?: string | null
}

export interface SystemRef {
  system_id: string
  name: string
}

export interface AppReach {
  repos: { fullName: string; isPrivate: boolean }[]
  /** False when GitHub failed for some installation. */
  complete: boolean
}

export interface RepoRow {
  key: string
  fullName: string
  owner: string
  name: string
  registered: boolean
  system: string | null
  attachment: RepoAttachment
  privacy: RepoPrivacy
  defaultBranch: string | null
  createdAt: string | null
}

const GITHUB = 'github'

const split = (fullName: string) => {
  const i = fullName.indexOf('/')
  return i === -1 ? { owner: '', name: fullName } : { owner: fullName.slice(0, i), name: fullName.slice(i + 1) }
}

export function repoRows(repos: readonly RegisteredRepo[], systems: readonly SystemRef[], access: AppReach): RepoRow[] {
  const systemNames = new Map(systems.map((s) => [s.system_id, s.name]))
  const app = new Map(access.repos.map((r) => [r.fullName.toLowerCase(), r.isPrivate ? ('private' as const) : ('public' as const)]))
  const rows: RepoRow[] = repos.map((repo) => registeredRow(repo, systemNames, app, access.complete))
  const registeredNames = new Set(repos.filter((repo) => repoProvider(repo) === GITHUB).map((repo) => repoFullName(repo).toLowerCase()))
  for (const reach of access.repos) {
    if (!registeredNames.has(reach.fullName.toLowerCase())) rows.push(appOnlyRow(reach))
  }
  return rows.sort((a, b) => a.fullName.localeCompare(b.fullName) || a.key.localeCompare(b.key))
}

const repoFullName = (repo: RegisteredRepo): string => repo.full_name || repo.repo_id
const repoProvider = (repo: RegisteredRepo): string => (repo.provider || GITHUB).toLowerCase()

function repoAttachment(appPrivacy: RepoPrivacy | undefined, provider: string, complete: boolean): RepoAttachment {
  if (appPrivacy) return 'attached'
  return provider !== GITHUB || complete ? 'not-attached' : 'unknown'
}

function registeredRow(repo: RegisteredRepo, systemNames: Map<string, string>, app: Map<string, 'private' | 'public'>, complete: boolean): RepoRow {
  const fullName = repoFullName(repo)
  const provider = repoProvider(repo)
  const appPrivacy = provider === GITHUB ? app.get(fullName.toLowerCase()) : undefined
  return {
    key: repo.repo_id,
    fullName,
    ...split(fullName),
    registered: true,
    system: repo.system_id ? (systemNames.get(repo.system_id) ?? repo.system_id) : null,
    attachment: repoAttachment(appPrivacy, provider, complete),
    // Registration always sends is_private=false, so only a stored true is news.
    privacy: appPrivacy ?? (repo.is_private ? 'private' : 'unknown'),
    defaultBranch: repo.default_branch ?? null,
    createdAt: repo.created_at ?? null,
  }
}

function appOnlyRow({ fullName, isPrivate }: AppReach['repos'][number]): RepoRow {
  return {
    key: `@github-app|${fullName.toLowerCase()}`,
    fullName,
    ...split(fullName),
    registered: false,
    system: null,
    attachment: 'attached',
    privacy: isPrivate ? 'private' : 'public',
    defaultBranch: null,
    createdAt: null,
  }
}

export interface RepoCounts {
  total: number
  attached: number
  unregistered: number
}

export function repoCounts(rows: readonly RepoRow[]): RepoCounts {
  return {
    total: rows.length,
    attached: rows.filter((r) => r.attachment === 'attached').length,
    unregistered: rows.filter((r) => !r.registered).length,
  }
}

/** Group rows by owner (organization), owners sorted. */
export function groupReposByOwner(rows: readonly RepoRow[]): { owner: string; repos: RepoRow[] }[] {
  const m = new Map<string, RepoRow[]>()
  for (const r of rows) m.set(r.owner || '—', [...(m.get(r.owner || '—') ?? []), r])
  return [...m.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([owner, repos]) => ({ owner, repos }))
}
