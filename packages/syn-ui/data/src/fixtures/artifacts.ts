import type { ArtifactListResponse, ArtifactResponse } from '../types'
import type { CatalogPhaseRun } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { countBy, paginate } from './seed'
import { allPhaseRuns } from './sessions'

type ArtifactRow = NonNullable<ArtifactListResponse['artifacts']>[number]

const withArtifacts = () => allPhaseRuns().filter((p) => p.artifactId !== null)

const contentOf = (p: CatalogPhaseRun) =>
  `# ${p.phase.name}\n\nOutput of the **${p.phase.name}** phase.\n\n## Findings\n\n- Claude and Codex both report cache reads separately from input.\n- Cache writes are billed at a premium.\n\n## Next\n\nHand the findings to the next phase.\n`

function row(p: CatalogPhaseRun): ArtifactRow {
  return {
    id: p.artifactId!,
    workflow_id: p.run.workflowId,
    execution_id: p.run.id,
    phase_id: p.phase.id,
    artifact_type: p.phase.id === 'report' ? 'report' : 'markdown',
    title: `${p.phase.name} output`,
    size_bytes: contentOf(p).length * 37,
    created_at: p.completedAt,
    agent_provider: p.phase.provider,
    agent_model: p.phase.model,
  }
}

function detail(p: CatalogPhaseRun, includeContent: boolean): ArtifactResponse {
  const r = row(p)
  return {
    id: r.id,
    workflow_id: r.workflow_id,
    phase_id: r.phase_id,
    session_id: p.sessionId,
    artifact_type: r.artifact_type,
    is_primary_deliverable: p.phase.id === 'report',
    content: includeContent ? contentOf(p) : null,
    content_type: 'text/markdown',
    content_hash: `sha256:${p.artifactId}`,
    size_bytes: r.size_bytes,
    title: r.title ?? null,
    derived_from: [],
    created_at: r.created_at ?? null,
    created_by: p.sessionId,
    metadata: {},
  }
}

const find = (id: string) => withArtifacts().find((p) => p.artifactId === id) ?? notFound('Artifact')

export const artifactRoutes: FixtureRoute[] = [
  route('GET', '/artifacts', ({ query }): ArtifactListResponse => {
    let rows = withArtifacts().map(row)
    for (const key of ['workflow_id', 'phase_id', 'artifact_type'] as const) {
      const v = query.get(key)
      if (v) rows = rows.filter((r) => r[key] === v)
    }
    const q = query.get('q')?.toLowerCase()
    if (q) rows = rows.filter((r) => `${r.title ?? ''} ${r.id}`.toLowerCase().includes(q))
    const page = paginate(rows, query, 50)
    return {
      artifacts: page.rows,
      total: page.total,
      page: page.page,
      page_size: page.page_size,
      excluded_undated: 0,
      type_counts: countBy(rows, (r) => r.artifact_type),
    }
  }),
  route('GET', '/artifacts/:artifactId', ({ params, query }) => detail(find(params.artifactId!), query.get('include_content') === 'true')),
  route('GET', '/artifacts/:artifactId/content', ({ params }) => {
    const p = find(params.artifactId!)
    return { artifact_id: p.artifactId, content: contentOf(p), content_type: 'text/markdown' }
  }),
]
