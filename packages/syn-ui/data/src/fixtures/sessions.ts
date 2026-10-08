import type { SessionListItem, SessionListResponse } from '../resources/sessions'
import type { OperationInfo, SessionResponse } from '../types'
import { type CatalogPhaseRun, RUNS, phaseRuns, workflowOf } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { after, costDisplay, countBy, durationDisplay, filterList, paginate, tokensDisplay } from './seed'

export function allPhaseRuns(): CatalogPhaseRun[] {
  return RUNS.flatMap(phaseRuns).filter((p) => p.sessionId !== null)
}

const total = (p: CatalogPhaseRun) => p.tokens.input + p.tokens.output + p.tokens.cacheWrite + p.tokens.cacheRead

export function sessionListItem(p: CatalogPhaseRun): SessionListItem {
  const w = workflowOf(p.run.workflowId)
  return {
    id: p.sessionId!,
    workflow_id: p.run.workflowId,
    workflow_name: w?.name ?? null,
    execution_id: p.run.id,
    phase_id: p.phase.id,
    phase_display: p.phase.name,
    status: p.status,
    agent_provider: p.phase.provider,
    agent_model: p.phase.model,
    requested_model: p.phase.model,
    agent_model_display: p.phase.model,
    repos: p.run.repo ? [p.run.repo] : [],
    repos_display: p.run.repo ? p.run.repo.replace('https://github.com/', '') : null,
    input_tokens: p.tokens.input,
    output_tokens: p.tokens.output,
    cache_creation_tokens: p.tokens.cacheWrite,
    cache_read_tokens: p.tokens.cacheRead,
    total_tokens: total(p),
    total_tokens_display: tokensDisplay(total(p)),
    total_cost_usd: p.cost.toFixed(6),
    total_cost_display: costDisplay(p.cost),
    unpriced_observation_count: 0,
    duration_seconds: p.seconds,
    duration_display: durationDisplay(p.seconds),
    started_at: p.startedAt,
    completed_at: p.completedAt,
  }
}

type Step = { tool: string; input: Record<string, unknown>; out?: string; fail?: boolean; dur?: number; gap: number }

/** Canvas Session board: Codex builds a palindrome checker and hands review to Claude. */
const DELEGATE_SCRIPT: Step[] = [
  { tool: 'Bash', gap: 0, input: { command: "sed -n '1,240p' /workspace/.agents/skills/delegating-to-claude-p/SKILL.md && printf '\\n--- AGENTS ---\\n' && sed -n '1,200p' /workspace/AGENTS.md" }, out: '---\nname: delegating-to-claude-p\ndescription: Hand a bounded task to Claude Code in print mode.\n---' },
  { tool: 'Bash', gap: 6, input: { command: "find /workspace/artifacts/input -maxdepth 1 -type f -print -exec sed -n '1,240p' {} \\; ; find /workspace -maxdepth 1 -type f" }, out: '/workspace/skills-lock.json' },
  { tool: 'Edit', gap: 3, input: { file_path: '/workspace/palindrome.py' } },
  { tool: 'Bash', gap: 5, input: { command: "python -m py_compile /workspace/palindrome.py && python - <<'PY'\nfrom palindrome import is_palindrome\nprint(is_palindrome('Racecar'))\nPY" }, out: '/bin/bash: line 1: python: command not found', fail: true },
  { tool: 'Bash', gap: 6, input: { command: "python3 -m py_compile /workspace/palindrome.py && python3 - <<'PY'\nfrom palindrome import is_palindrome\nprint(is_palindrome('Racecar'))\nPY" }, out: '/bin/bash: line 1: python3: command not found', fail: true },
  { tool: 'Bash', gap: 4, dur: 6, input: { command: 'claude -p --permission-mode bypassPermissions --output-format stream-json --verbose "Review /workspace/palindrome.py and write the findings to /workspace/artifacts/output/deliverable.md"' }, out: '{"type":"system","subtype":"init","cwd":"/workspace","session_id":"35468ba1-dca4-4f8c-9012-4fb500342e79","tools":["Task","Bash","CronCreate","Edit","Read","Write"]}\n{"type":"assistant","message":{"content":[{"type":"text","text":"Reviewing palindrome.py"}]}}\n{"type":"result","subtype":"success","duration_ms":5980}' },
  { tool: 'Edit', gap: 13, input: { file_path: '/workspace/artifacts/output/deliverable.md' } },
  { tool: 'Bash', gap: 4, input: { command: "sed -n '1,120p' /workspace/palindrome.py && sed -n '1,200p' /workspace/artifacts/output/deliverable.md" }, out: '"""Utilities for identifying palindromic strings."""\n\ndef is_palindrome(text: str) -> bool:\n    cleaned = [c.lower() for c in text if c.isalnum()]\n    return cleaned == cleaned[::-1]\n\n# Review\n- Handles punctuation and case.\n- Empty string counts as a palindrome; documented.\n- Unicode digits pass isalnum(); acceptable for this task.' },
]

const GENERIC_SCRIPT: Step[] = [
  { tool: 'Read', gap: 0, input: { file_path: '/workspace/README.md' }, out: '# Workspace\n\nTask inputs live in artifacts/input.' },
  { tool: 'Glob', gap: 2, input: { pattern: 'src/**/*.ts' }, out: 'src/index.ts\nsrc/api/client.ts\nsrc/api/client.test.ts' },
  { tool: 'Grep', gap: 3, input: { pattern: 'listExecutions', path: 'src' }, out: 'src/api/client.ts:42:export function listExecutions(query) {' },
  { tool: 'Read', gap: 2, input: { file_path: '/workspace/src/api/client.ts' }, out: Array.from({ length: 24 }, (_, i) => `${i + 1}\t// line ${i + 1} of client.ts`).join('\n') },
  { tool: 'Edit', gap: 6, input: { file_path: '/workspace/src/api/client.ts' } },
  { tool: 'Bash', gap: 4, dur: 9, input: { command: 'pnpm test --run src/api' }, out: ' RUN  v4.1.11\n ✓ src/api/client.test.ts (12 tests) 31ms\n Test Files  1 passed (1)\n      Tests  12 passed (12)' },
  { tool: 'WebFetch', gap: 3, input: { url: 'https://docs.github.com/en/rest/checks/runs' }, out: 'Check runs: list check runs for a Git reference.' },
  { tool: 'Bash', gap: 5, input: { command: 'git add -A && git commit -m "fix: coalesce execution list requests"' }, out: '[main 4f2a9c1] fix: coalesce execution list requests\n 2 files changed, 18 insertions(+), 4 deletions(-)' },
]

function hash(text: string): number {
  let h = 0
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0
  return Math.abs(h)
}

function operations(p: CatalogPhaseRun): OperationInfo[] {
  const sid = p.sessionId!
  const t0 = p.startedAt ?? new Date(0).toISOString()
  const delegating = p.run.workflowId.includes('delegates')
  const script = sessionScript(sid, delegating)
  const ops: OperationInfo[] = [
    { operation_id: `${sid}-0`, operation_type: 'message_request', timestamp: t0, success: true, message_role: 'user', message_content: `Run the ${p.phase.name} phase of ${p.run.workflowId}.\nRead the inputs in /workspace/artifacts/input and write the deliverable to /workspace/artifacts/output.` },
  ]
  let at = 2_000
  script.forEach((step, i) => {
    at += step.gap * 1_000
    const failed = !!step.fail || (p.status === 'failed' && i === script.length - 1)
    ops.push(...toolOperations(sid, t0, at, step, i, failed))
  })
  if (p.status === 'running') ops.pop()
  ops.push(...closingOperations(p, sid, t0, at, delegating))
  return ops
}

function sessionScript(sid: string, delegating: boolean): Step[] {
  const base = delegating ? DELEGATE_SCRIPT : GENERIC_SCRIPT
  // One in seven sessions is a long one, so the timeline's chunked rendering has work to do.
  const repeats = hash(sid) % 7 === 0 ? 30 : 1
  return repeats === 1 ? base : Array.from({ length: repeats }, () => base).flat()
}

function toolOperations(sid: string, t0: string, at: number, step: Step, i: number, failed: boolean): OperationInfo[] {
  const use = `toolu_${sid.slice(0, 6)}_${i}`
  const dur = step.dur ?? 0.4
  return [
    { operation_id: `${sid}-s${i}`, operation_type: 'tool_execution_started', timestamp: after(t0, at), success: true, tool_name: step.tool, tool_use_id: use, tool_input: step.input },
    {
      operation_id: `${sid}-c${i}`,
      operation_type: 'tool_execution_completed',
      timestamp: after(t0, at + dur * 1_000),
      duration_seconds: dur,
      success: !failed,
      tool_name: step.tool,
      tool_use_id: use,
      tool_output: failed && !step.out ? 'Process exited with status 1' : (step.out ?? null),
      error_message: failed ? (step.out ?? 'Process exited with status 1') : null,
    },
  ]
}

/** The git commit (completed non-delegating sessions) and session end (finished sessions). */
function closingOperations(p: CatalogPhaseRun, sid: string, t0: string, at: number, delegating: boolean): OperationInfo[] {
  const ops: OperationInfo[] = []
  if (!delegating && p.status === 'completed') {
    ops.push({ operation_id: `${sid}-git`, operation_type: 'git_commit', timestamp: after(t0, at + 2_000), success: true, git_sha: '4f2a9c1e88d07b3a', git_branch: 'main', git_repo: p.run.repo ? p.run.repo.replace('https://github.com/', '') : null, git_message: 'fix: coalesce execution list requests' })
  }
  if (p.status !== 'running') ops.push({ operation_id: `${sid}-end`, operation_type: 'session_completed', timestamp: after(t0, at + 3_000), success: p.status !== 'failed' })
  return ops
}

export function sessionDetail(p: CatalogPhaseRun): SessionResponse {
  const item = sessionListItem(p)
  return {
    id: item.id,
    workflow_id: item.workflow_id,
    workflow_name: item.workflow_name ?? null,
    execution_id: p.run.id,
    phase_id: p.phase.id,
    phase_display: p.phase.name,
    milestone_id: null,
    agent_provider: p.phase.provider,
    agent_model: p.phase.model,
    requested_model: p.phase.model,
    agent_model_display: p.phase.model,
    status: p.status,
    input_tokens: p.tokens.input,
    output_tokens: p.tokens.output,
    cache_creation_tokens: p.tokens.cacheWrite,
    cache_read_tokens: p.tokens.cacheRead,
    total_tokens: total(p),
    total_cost_usd: p.cost,
    unpriced_observation_count: 0,
    cost_by_model: p.phase.provider === 'codex' && p.cost > 0.1 ? { [p.phase.model]: (p.cost * 0.82).toFixed(6), 'claude-sonnet-4-5': (p.cost * 0.18).toFixed(6) } : { [p.phase.model]: p.cost.toFixed(6) },
    cache_read_rate_display: '0.1× rate',
    cache_write_rate_display: '1.25× rate',
    operations: operations(p),
    started_at: p.startedAt,
    completed_at: p.completedAt,
    duration_seconds: p.seconds,
    error_message: p.status === 'failed' ? 'Phase exited with a non-zero status' : null,
    metadata: {},
  }
}

export const sessionRoutes: FixtureRoute[] = [
  route('GET', '/sessions', ({ query }): SessionListResponse => {
    const items = allPhaseRuns().map(sessionListItem)
    const workflowId = query.get('workflow_id')
    const scoped = workflowId ? items.filter((s) => s.workflow_id === workflowId) : items
    const textOf = (s: SessionListItem) => `${s.id} ${s.workflow_name ?? ''} ${s.phase_display ?? ''}`
    const rows = filterList(scoped, query, (s) => s.status, textOf)
    const page = paginate(rows, query, 50)
    return {
      sessions: page.rows,
      total: page.total,
      page: page.page,
      page_size: page.page_size,
      excluded_undated: 0,
      status_counts: countBy(filterList(scoped, new URLSearchParams({ q: query.get('q') ?? '' }), (s) => s.status, textOf), (s) => s.status),
    }
  }),
  route('GET', '/sessions/:sessionId', ({ params }) => {
    const p = allPhaseRuns().find((x) => x.sessionId === params.sessionId) ?? notFound('Session')
    return sessionDetail(p)
  }),
]
