import type { components } from '../generated/api-types'
import type { RepoSummary, SystemSummary } from '../resources/repos'

type GitHubRepoListResponse = components['schemas']['GitHubRepoListResponse']
import { type FixtureRoute, route } from './define'
import { WEEK, ago } from './seed'

export const REPOS: RepoSummary[] = [
  {
    repo_id: 'repo-syn137',
    organization_id: 'org-syntropic137',
    system_id: 'sys-platform',
    provider: 'github',
    full_name: 'syntropic137/syntropic137',
    owner: 'syntropic137',
    default_branch: 'main',
    installation_id: 'inst-1',
    is_private: false,
    created_by: 'neural',
    created_at: ago(20 * WEEK),
  },
  {
    repo_id: 'repo-sandbox',
    organization_id: 'org-syntropic137',
    system_id: 'sys-platform',
    provider: 'github',
    full_name: 'syntropic137/sandbox_syn-engineer-beta',
    owner: 'syntropic137',
    default_branch: 'main',
    installation_id: 'inst-1',
    is_private: true,
    created_by: 'neural',
    created_at: ago(12 * WEEK),
  },
]

const SYSTEMS: SystemSummary[] = [
  { system_id: 'sys-platform', organization_id: 'org-syntropic137', name: 'Platform', description: 'The Syntropic137 platform', created_by: 'neural', created_at: ago(20 * WEEK), repo_count: 2 },
]

export const repoRoutes: FixtureRoute[] = [
  route('GET', '/repos', () => ({ repos: REPOS, total: REPOS.length })),
  route('GET', '/systems', () => ({ systems: SYSTEMS, total: SYSTEMS.length })),
  route('GET', '/github/repos', (): GitHubRepoListResponse => ({
    repos: REPOS.map((r, i) => ({
      github_id: 1000 + i,
      name: r.full_name.split('/')[1] ?? r.full_name,
      full_name: r.full_name,
      private: r.is_private,
      default_branch: r.default_branch,
      owner: r.owner,
      installation_id: r.installation_id,
    })),
    total: REPOS.length,
    installation_id: 'inst-1',
    lookup: 'complete',
  })),
]
