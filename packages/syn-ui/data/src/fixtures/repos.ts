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
  {
    repo_id: 'repo-design',
    organization_id: 'org-syntropic137',
    system_id: 'sys-design',
    provider: 'github',
    full_name: 'syntropic137/design-contracts',
    owner: 'syntropic137',
    default_branch: 'main',
    installation_id: '',
    is_private: false,
    created_by: 'neural',
    created_at: ago(6 * WEEK),
  },
  {
    repo_id: 'repo-primitives',
    organization_id: 'org-agentparadise',
    system_id: '',
    provider: 'github',
    full_name: 'AgentParadise/agentic-primitives',
    owner: 'AgentParadise',
    default_branch: 'main',
    installation_id: 'inst-2',
    is_private: false,
    created_by: 'neural',
    created_at: ago(30 * WEEK),
  },
]

/** Reachable by the GitHub App but never registered with `syn repo register`. */
const APP_ONLY = [{ full_name: 'syntropic137/homelab-infra', owner: 'syntropic137', private: true }]

const SYSTEMS: SystemSummary[] = [
  { system_id: 'sys-platform', organization_id: 'org-syntropic137', name: 'Platform', description: 'The Syntropic137 platform', created_by: 'neural', created_at: ago(20 * WEEK), repo_count: 2 },
  { system_id: 'sys-design', organization_id: 'org-syntropic137', name: 'Design system', description: 'Tokens and contracts', created_by: 'neural', created_at: ago(6 * WEEK), repo_count: 1 },
]

export const repoRoutes: FixtureRoute[] = [
  route('GET', '/repos', () => ({ repos: REPOS, total: REPOS.length })),
  route('GET', '/systems', () => ({ systems: SYSTEMS, total: SYSTEMS.length })),
  route('GET', '/github/repos', (): GitHubRepoListResponse => ({
    repos: [
      ...REPOS.filter((r) => r.installation_id).map((r, i) => ({
      github_id: 1000 + i,
      name: r.full_name.split('/')[1] ?? r.full_name,
      full_name: r.full_name,
      private: r.is_private,
      default_branch: r.default_branch,
      owner: r.owner,
      installation_id: r.installation_id!,
    })),
      ...APP_ONLY.map((r, i) => ({
        github_id: 2000 + i,
        name: r.full_name.split('/')[1] ?? r.full_name,
        full_name: r.full_name,
        private: r.private,
        default_branch: 'main',
        owner: r.owner,
        installation_id: 'inst-1',
      })),
    ],
    total: REPOS.length,
    installation_id: 'inst-1',
    lookup: 'complete',
  })),
]
