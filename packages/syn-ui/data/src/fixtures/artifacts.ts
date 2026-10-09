import type { ArtifactListResponse, ArtifactResponse } from '../types'
import type { CatalogPhaseRun } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { countBy, paginate } from './seed'
import { allPhaseRuns } from './sessions'

type ArtifactRow = NonNullable<ArtifactListResponse['artifacts']>[number]

const withArtifacts = () => allPhaseRuns().filter((p) => p.artifactId !== null)

/** Board copy (Artifact canvas): the synthesis deliverable, plus siblings per phase. */
const SYNTHESIS = [
  '# Sorting: Research Synthesis & Recommendations',
  '',
  '## Executive Summary',
  '',
  'Sorting is a foundational computational primitive with profound implications across algorithm design, systems engineering, and user experience. This synthesis consolidates two phases of research (discovery and deep-dive analysis) into actionable insights for decision-makers, engineers, and architects.',
  '',
  '**Key Insight**: Optimal sorting strategies are **context-dependent**. There is no universally superior approach—success requires matching algorithm selection, implementation strategy, and correctness guarantees to specific workload characteristics.',
  '',
  '**Bottom Line**: 95% of applications should use language standard library sorting. Custom implementations are justified only when specific input characteristics guarantee substantial speedup or when extreme performance requirements demand specialized algorithms.',
  '',
  '## Research Scope & Methodology',
  '',
  'This research investigated sorting across three interconnected domains:',
  '',
  '1. **Computational Algorithms** — Algorithmic approaches (Quicksort, Mergesort, Timsort, etc.)',
  '2. **Systems Implementation** — Sorting in data structures, databases, and distributed systems',
  '3. **User Experience & Data Presentation** — Sorting as a user-facing feature in applications',
  '',
  'The analysis addressed five research questions:',
  '',
  '- **RQ1**: What is the scope of "sorting"?',
  '- **RQ2**: What are the performance constraints?',
  '- **RQ3**: What sorting patterns already exist in codebases?',
  '',
  '## Findings',
  '',
  '| Algorithm | Best case | Stable | Notes |',
  '|---|---|---|---|',
  '| Timsort | `O(n)` | yes | Default in Python and Java objects |',
  '| Pdqsort | `O(n)` | no | Default in Rust `sort_unstable` |',
  '| Radix | `O(nk)` | yes | Wins on fixed-width integer keys |',
  '',
  '> Measure before replacing the standard library: most "slow sorts" are slow comparators.',
  '',
  '## Recommendations',
  '',
  '- Use the standard library sort and a key function.',
  '- Reach for radix sort only on large fixed-width integer keys.',
  '- Keep comparators pure; `cmp` with side effects breaks stability guarantees.',
  '',
  '```python',
  'rows.sort(key=lambda r: (r.priority, r.created_at))',
  '```',
  '',
].join('\n')

const contentOf = (p: CatalogPhaseRun) => {
  if (p.phase.id === 'synthesize' || p.phase.id === 'report') return SYNTHESIS
  return `# ${p.phase.name}\n\nOutput of the **${p.phase.name}** phase of \`${p.run.workflowId}\`.\n\n## Findings\n\n- Claude and Codex both report cache reads separately from input.\n- Cache writes are billed at a premium.\n\n## Next\n\nHand the findings to the next phase.\n`
}

const TYPE_OF: Record<string, string> = { synthesize: 'research_summary', report: 'report', review: 'code_review', comment: 'markdown', probe: 'json', delegate: 'code', bridge: 'code' }
const TITLE_OF: Record<string, string> = { synthesize: 'deliverable.md', report: 'report.md', research: 'discovery.md' }

/** Earlier artifacts of the same run: what this one was derived from. */
const parentsOf = (p: CatalogPhaseRun) =>
  withArtifacts()
    .filter((o) => o.run.id === p.run.id && o.index < p.index)
    .map((o) => o.artifactId!)

function row(p: CatalogPhaseRun): ArtifactRow {
  return {
    id: p.artifactId!,
    workflow_id: p.run.workflowId,
    execution_id: p.run.id,
    phase_id: p.phase.id,
    artifact_type: TYPE_OF[p.phase.id] ?? 'markdown',
    title: TITLE_OF[p.phase.id] ?? `${p.phase.name} output`,
    size_bytes: contentOf(p).length * 9 + p.index * 1311,
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
    is_primary_deliverable: p.phase.id === 'report' || p.phase.id === 'synthesize',
    content: includeContent ? contentOf(p) : null,
    content_type: 'text/markdown',
    content_hash: `sha256:${p.artifactId}`,
    size_bytes: r.size_bytes,
    title: r.title ?? null,
    derived_from: parentsOf(p),
    created_at: r.created_at ?? null,
    created_by: p.sessionId,
    metadata: { path: `artifacts/output/${r.title ?? r.id}`, phase_name: p.phase.name, execution_id: p.run.id },
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

/** One artifact as the list (and GET /workflows/{id}/latest-outputs) returns it. */
export { row as artifactRow }
