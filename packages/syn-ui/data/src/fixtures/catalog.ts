/**
 * The fixture world: workflows and the runs of them, transcribed from the
 * Executions and Workflows canvas boards. Resource fixture files derive
 * their API shapes from these rows, so a run, its sessions and its
 * artifacts always agree.
 *
 * Screen agents: add rows here (or richer per-screen data in the resource
 * fixture file) rather than inventing disconnected records.
 */
import { DAY, HOUR, REPO_SANDBOX, REPO_SYN, WEEK, ago, after, fakeId } from './seed'

export interface CatalogPhase {
  id: string
  name: string
  model: string
  provider: 'claude' | 'codex'
}

export interface CatalogWorkflow {
  id: string
  name: string
  type: string
  description: string
  phases: CatalogPhase[]
}

const claude = (id: string, name: string, model = 'claude-sonnet-4-5'): CatalogPhase => ({ id, name, model, provider: 'claude' })
const codex = (id: string, name: string, model = 'gpt-5-codex'): CatalogPhase => ({ id, name, model, provider: 'codex' })

export const WORKFLOWS: CatalogWorkflow[] = [
  {
    id: 'research-workflow',
    name: 'Research Workflow',
    type: 'research',
    description: 'Researches a topic, synthesises findings and writes a report.',
    phases: [claude('research', 'Research'), claude('synthesize', 'Synthesize'), claude('report', 'Report')],
  },
  { id: 'codex-delegates-to-claude', name: 'Codex delegates to Claude', type: 'custom', description: 'Codex plans and hands the work to Claude.', phases: [codex('delegate', 'Delegate')] },
  { id: 'claude-delegates-to-codex', name: 'Claude delegates to Codex', type: 'custom', description: 'Claude plans and hands the work to Codex.', phases: [claude('delegate', 'Delegate')] },
  {
    id: 'skills-matrix',
    name: 'Skills Matrix',
    type: 'custom',
    description: 'Exercises each declared skill once and records what loaded.',
    phases: [claude('inventory', 'Inventory'), claude('probe', 'Probe'), claude('verify', 'Verify'), claude('summarize', 'Summarize')],
  },
  { id: 'skill-probe', name: 'Skill Probe', type: 'custom', description: 'Checks that pinned skills resolve inside the workspace.', phases: [claude('setup', 'Setup'), claude('probe', 'Probe'), claude('report', 'Report')] },
  { id: 'starter-research', name: 'Starter Research', type: 'research', description: 'A two-phase research starter.', phases: [claude('research', 'Research'), claude('report', 'Report')] },
  { id: 'pr-review', name: 'PR Review', type: 'review', description: 'Reviews a pull request and posts findings.', phases: [claude('read', 'Read diff'), claude('review', 'Review'), claude('comment', 'Comment')] },
  { id: 'starter-pr-review', name: 'Starter PR Review', type: 'review', description: 'A two-phase PR review starter.', phases: [claude('review', 'Review'), claude('comment', 'Comment')] },
  { id: 'subagent-observability-demo', name: 'Subagent Observability Demo', type: 'custom', description: 'Spawns subagents to show their lifecycle events.', phases: [claude('spawn', 'Spawn'), claude('collect', 'Collect')] },
  { id: 'codex-bridge-demo', name: 'Codex Bridge Demo', type: 'custom', description: 'One Codex phase through the bridge.', phases: [codex('bridge', 'Bridge')] },
  {
    id: 'multi-agent',
    name: 'Multi-agent (claude plans, codex implements)',
    type: 'custom',
    description: 'Claude writes the plan; Codex implements it.',
    phases: [claude('plan', 'Plan', 'claude-opus-4-1'), codex('implement', 'Implement')],
  },
]

export type RunStatus = 'completed' | 'failed' | 'cancelled' | 'running'

export interface CatalogRun {
  id: string
  workflowId: string
  status: RunStatus
  /** Phases that completed. */
  done: number
  repo: string | null
  tokens: number
  cost: number
  seconds: number
  startedAt: string
}

let seq = 0
const run = (status: RunStatus, workflowId: string, done: number, repo: string | null, tokens: number, cost: number, seconds: number, agoMs: number): CatalogRun => {
  seq++
  const startedAt = ago(agoMs + seq * 7 * 60_000)
  return { id: fakeId(`run-${seq}-${workflowId}`), workflowId, status, done, repo, tokens, cost, seconds, startedAt }
}

/** Newest first, as the Executions board lists them. */
export const RUNS: CatalogRun[] = [
  run('running', 'research-workflow', 1, REPO_SYN, 143_900, 0.09, 95, 20 * 60_000),
  run('completed', 'pr-review', 3, REPO_SYN, 176_000, 0.21, 118, 1 * HOUR),
  run('completed', 'research-workflow', 3, null, 396_791, 0.2162, 227, 1 * DAY),
  run('failed', 'starter-pr-review', 0, REPO_SYN, 0, 0, 5, 1 * WEEK),
  run('failed', 'pr-review', 0, REPO_SYN, 0, 0, 8, 1 * WEEK),
  run('completed', 'codex-delegates-to-claude', 1, null, 261_734, 0.33, 62, 6 * WEEK),
  run('completed', 'codex-delegates-to-claude', 1, null, 243_400, 0.29, 66, 6 * WEEK),
  run('failed', 'codex-delegates-to-claude', 0, null, 0, 0, 3, 6 * WEEK),
  run('completed', 'codex-delegates-to-claude', 1, null, 348_300, 0.22, 92, 6 * WEEK),
  run('completed', 'research-workflow', 3, null, 479_400, 0.22, 222, 6 * WEEK),
  run('completed', 'research-workflow', 3, null, 365_300, 0.16, 157, 6 * WEEK),
  run('cancelled', 'research-workflow', 2, null, 156_600, 0.17, 241, 6 * WEEK),
  run('cancelled', 'research-workflow', 0, null, 0, 0, 56, 6 * WEEK),
  run('completed', 'claude-delegates-to-codex', 1, null, 127_900, 0.06, 37, 6 * WEEK),
  run('completed', 'skills-matrix', 4, null, 106_900, 0.1, 85, 6 * WEEK),
  run('failed', 'skills-matrix', 3, null, 92_500, 0.07, 52, 6 * WEEK),
  run('completed', 'skill-probe', 3, REPO_SANDBOX, 92_700, 0.07, 61, 6 * WEEK),
  run('completed', 'starter-research', 2, REPO_SANDBOX, 162_300, 0.12, 77, 7 * WEEK),
  run('failed', 'subagent-observability-demo', 0, null, 0, 0, 1, 7 * WEEK),
  run('completed', 'codex-bridge-demo', 1, null, 162_200, 0.04, 56, 7 * WEEK),
  run('completed', 'multi-agent', 2, null, 229_000, 0.09, 86, 7 * WEEK),
  // Appended (not inserted) so every id above keeps its seq: today's runs, so
  // the 24h default on Executions and Sessions has a list to show. List
  // routes sort by start time, newest first.
  run('completed', 'pr-review', 3, REPO_SYN, 188_400, 0.23, 131, 3 * HOUR),
  run('failed', 'research-workflow', 1, null, 84_200, 0.05, 44, 6 * HOUR),
  run('completed', 'codex-delegates-to-claude', 1, null, 251_900, 0.31, 64, 11 * HOUR),
  run('completed', 'skills-matrix', 4, null, 112_300, 0.11, 88, 17 * HOUR),
]

export function workflowOf(id: string): CatalogWorkflow | undefined {
  return WORKFLOWS.find((w) => w.id === id)
}

export function runOf(id: string): CatalogRun | undefined {
  return RUNS.find((r) => r.id === id)
}

export interface CatalogPhaseRun {
  run: CatalogRun
  phase: CatalogPhase
  index: number
  status: 'completed' | 'failed' | 'cancelled' | 'running' | 'pending'
  sessionId: string | null
  artifactId: string | null
  startedAt: string | null
  completedAt: string | null
  seconds: number | null
  tokens: { input: number; output: number; cacheWrite: number; cacheRead: number }
  cost: number
}

/** Split a run into its phases: completed ones share the run's time, tokens and cost. */
export function phaseRuns(r: CatalogRun): CatalogPhaseRun[] {
  const wf = workflowOf(r.workflowId)
  if (!wf) return []
  const started = phasesStarted(r, wf.phases.length)
  const share = (v: number) => (started ? v / started : 0)
  let cursor = r.startedAt
  return wf.phases.map((phase, index) => {
    const pr = phaseRunAt(r, phase, index, index < started, share, cursor)
    if (pr.completedAt) cursor = pr.completedAt
    return pr
  })
}

/** How many phases of the run have started: a running or failed run includes its current phase. */
function phasesStarted(r: CatalogRun, phaseCount: number): number {
  if (r.status === 'running') return r.done + 1
  if (r.status === 'completed') return r.done
  return Math.min(phaseCount, r.done + 1)
}

function phaseStatusAt(r: CatalogRun, index: number, ran: boolean): CatalogPhaseRun['status'] {
  if (index < r.done) return 'completed'
  if (!ran) return 'pending'
  return r.status === 'completed' ? 'completed' : r.status
}

function splitTokens(tokens: number): CatalogPhaseRun['tokens'] {
  const input = Math.round(tokens * 0.02)
  const output = Math.round(tokens * 0.05)
  const cacheWrite = Math.round(tokens * 0.13)
  return { input, output, cacheWrite, cacheRead: tokens - input - output - cacheWrite }
}

function phaseRunAt(r: CatalogRun, phase: CatalogPhase, index: number, ran: boolean, share: (v: number) => number, cursor: string): CatalogPhaseRun {
  const status = phaseStatusAt(r, index, ran)
  const seconds = ran ? Math.max(1, Math.round(share(r.seconds))) : null
  const completedAt = ran && status !== 'running' && seconds !== null ? after(cursor, seconds * 1000) : null
  return {
    run: r,
    phase,
    index,
    status,
    sessionId: ran ? fakeId(`session-${r.id}-${phase.id}`) : null,
    artifactId: status === 'completed' ? fakeId(`artifact-${r.id}-${phase.id}`) : null,
    startedAt: ran ? cursor : null,
    completedAt,
    seconds,
    tokens: splitTokens(ran ? Math.round(share(r.tokens)) : 0),
    cost: ran ? share(r.cost) : 0,
  }
}
