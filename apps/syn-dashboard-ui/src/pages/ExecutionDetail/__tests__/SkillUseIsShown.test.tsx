/**
 * Execution detail shows which declared skills each phase invoked (#1269,
 * feedback 01308bcf), and never reads an unobservable use as "0 used".
 *
 * Fixtures carry the strings the server sends (`status_display`,
 * `summary_display`): the dashboard renders them verbatim, so a component that
 * wrote its own would print something these tests do not expect. Each status
 * is paired with another, because a component that always said one thing
 * would pass a test of that path alone.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { SkillUseLine, SkillUseOverview } from '../../../components/provenance/SkillUse'
import type { ExecutionDetailResponse, ExecutionSkillUse, PhaseSkillUse } from '../../../types'
import { withPlanOfPhases } from '../../../test/phasePlanFixtures'

const useExecutionData = vi.fn()

vi.mock('../../../hooks', () => ({
  useExecutionData: (executionId: string | undefined) => useExecutionData(executionId),
}))

const { ExecutionDetail } = await import('../ExecutionDetail')

const OBSERVED: PhaseSkillUse = {
  status: 'observed',
  provider: 'claude',
  declared: ['architecture', 'principles-and-patterns'],
  invoked: [{ name: 'architecture', count: 3 }],
  declared_not_invoked: ['principles-and-patterns'],
  status_display: "observed: read from this phase's Skill tool calls",
  summary_display: '1 of 2 declared skills invoked',
}

const ALL_INVOKED: PhaseSkillUse = {
  ...OBSERVED,
  invoked: [
    { name: 'architecture', count: 3 },
    { name: 'principles-and-patterns', count: 1 },
  ],
  declared_not_invoked: [],
  summary_display: '2 of 2 declared skills invoked',
}

const CODEX: PhaseSkillUse = {
  status: 'not_observable',
  provider: 'codex',
  declared: ['architecture', 'types'],
  invoked: [],
  declared_not_invoked: [],
  status_display: 'not observable: codex has no Skill tool',
  summary_display: '2 skills declared; use not observable: codex has no Skill tool',
}

const UNAVAILABLE: PhaseSkillUse = {
  status: 'unavailable',
  provider: null,
  declared: [],
  invoked: [],
  declared_not_invoked: [],
  status_display: 'unavailable: no record for this run',
  summary_display: 'skill use unavailable: no record for this run',
}

describe('SkillUseLine', () => {
  it('lists invoked skills with counts on an observed phase', () => {
    const { container } = render(<SkillUseLine use={ALL_INVOKED} />)
    expect(container.querySelector('summary')?.textContent).toBe('2 of 2 declared skills invoked')
    expect(container.textContent).toContain('architecture ×3')
    expect(container.textContent).toContain('principles-and-patterns ×1')
    expect(screen.queryByTestId('skill-use-not-invoked')).toBeNull()
    expect(container.querySelector('.skill-use--warn')).toBeNull()
  })

  it('flags declared-but-not-invoked skills as a warning', () => {
    const { container } = render(<SkillUseLine use={OBSERVED} />)
    expect(container.querySelector('summary')).toHaveClass('skill-use--warn')
    const missed = screen.getByTestId('skill-use-not-invoked')
    expect(missed).toHaveClass('skill-use--warn')
    expect(missed.textContent).toBe('principles-and-patterns')
  })

  it('explains a codex phase and never shows an invoked count for it', () => {
    const { container } = render(<SkillUseLine use={CODEX} />)
    const text = container.textContent ?? ''
    expect(text).toContain('not observable: codex has no Skill tool')
    expect(text).toContain('types')
    expect(text).not.toMatch(/\b0\b|Invoked|Not invoked|×/)
    expect(container.querySelector('.skill-use--warn')).toBeNull()
  })

  it('says unavailable for a run with no record, rather than nothing', () => {
    const { container } = render(<SkillUseLine use={UNAVAILABLE} />)
    expect(container.querySelector('summary')?.textContent).toBe(
      'skill use unavailable: no record for this run',
    )
    expect(container.textContent).not.toMatch(/\b0\b|Invoked/)
  })

  it('reads a server that sends no skill_use as unavailable', () => {
    const { container } = render(<SkillUseLine use={undefined} />)
    expect(container.textContent).toBe('skill use unavailable: no record for this run')
  })
})

describe('SkillUseOverview', () => {
  const SUMMARY: ExecutionSkillUse = {
    declared: ['architecture', 'principles-and-patterns', 'types'],
    invoked: [{ name: 'architecture', count: 3 }],
    never_invoked: ['principles-and-patterns'],
    not_known: ['types'],
    summary_display: '3 skills declared · 1 invoked · 1 never invoked · 1 use unknown',
  }

  it('separates never invoked from use that could not be seen', () => {
    const { container } = render(<SkillUseOverview use={SUMMARY} />)
    expect(container.textContent).toContain(SUMMARY.summary_display)
    expect(screen.getByTestId('skill-use-never-invoked').textContent).toBe('principles-and-patterns')
    expect(screen.getByTestId('skill-use-never-invoked')).toHaveClass('skill-use--warn')
    expect(container.textContent).toContain('Use unknown')
  })

  it('reads a server that sends no summary as unavailable', () => {
    const { container } = render(<SkillUseOverview use={undefined} />)
    expect(container.textContent).toContain('skill use unavailable: no record for this run')
  })
})

function phase(id: string, use: PhaseSkillUse): ExecutionDetailResponse['phases'][number] {
  return {
    phase_id: id,
    name: id,
    status: 'completed',
    session_id: null,
    agent_session_id: null,
    artifact_id: null,
    input_tokens: 0,
    output_tokens: 0,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    duration_seconds: 1,
    cost_usd: 0,
    unpriced_observation_count: 0,
    started_at: null,
    completed_at: null,
    model: null,
    requested_model: null,
    model_display: 'unknown',
    cost_by_model: {},
    pinned_at_start: null,
    start_pins_status: 'unavailable',
    skill_use: use,
  }
}

describe('execution detail page', () => {
  it('shows the run summary and each phase its own skill use', () => {
    const execution = {
      workflow_execution_id: 'exec-skills',
      workflow_id: 'wf',
      workflow_name: 'wf',
      status: 'completed',
      started_at: null,
      completed_at: null,
      phases: [phase('implement', OBSERVED), phase('review', CODEX), phase('legacy', UNAVAILABLE)],
      skill_use: {
        declared: ['architecture', 'principles-and-patterns', 'types'],
        invoked: [{ name: 'architecture', count: 3 }],
        never_invoked: [],
        not_known: ['principles-and-patterns', 'types'],
        summary_display: '3 skills declared · 1 invoked · 0 never invoked · 2 use unknown',
      },
      total_phases: 3,
      completed_phases: 3,
      phase_progress: { completed: 3, skipped: 0, possible: 3, remaining_possible: 0, percent: 100, display: '3 of 3' },
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_cache_creation_tokens: 0,
      total_cache_read_tokens: 0,
      total_tokens: 0,
      total_cost_usd: 0,
      unpriced_observation_count: 0,
      artifact_ids: [],
      error_message: null,
      repos: [],
    } as unknown as ExecutionDetailResponse // test fixture: only the fields the page reads
    useExecutionData.mockReturnValue({
      execution: withPlanOfPhases(execution),
      artifactDetails: {},
      loading: false,
      error: null,
      isConnected: true,
      now: 0,
      refreshExecution: vi.fn(),
    })
    render(
      <MemoryRouter initialEntries={['/executions/exec-skills']}>
        <ExecutionDetail />
      </MemoryRouter>,
    )

    const overview = screen.getByRole('region', { name: 'Skill use' })
    expect(overview.textContent).toContain('3 skills declared · 1 invoked · 0 never invoked · 2 use unknown')

    const timeline = document.getElementById('phase-timeline')
    if (!timeline) throw new Error('phase timeline not rendered')
    const lines = Array.from(timeline.querySelectorAll('.skill-use summary')).map((s) => s.textContent)
    expect(lines).toEqual([
      '1 of 2 declared skills invoked',
      '2 skills declared; use not observable: codex has no Skill tool',
      'skill use unavailable: no record for this run',
    ])
    expect(within(timeline).getByTestId('skill-use-not-invoked').textContent).toBe(
      'principles-and-patterns',
    )
  })
})

describe('at a phone width (411px)', () => {
  // jsdom does no layout, so this pins the rules that keep a long skill name
  // from widening the page: names wrap anywhere, and the overview's two-column
  // list collapses to one column on a phone.
  const css = readFileSync(
    resolve(__dirname, '../../../components/provenance/provenance.css'),
    'utf8',
  )

  it('lets skill names wrap', () => {
    expect(css).toMatch(/\.skill-use \{[^}]*overflow-wrap: anywhere/)
    expect(css).toMatch(/\.skill-use-overview \{[^}]*overflow-wrap: anywhere/)
    expect(css).toMatch(/\.skill-use__names \{[^}]*flex-wrap: wrap/)
  })

  it('stacks the overview list on a phone', () => {
    expect(css).toMatch(
      /@media \(max-width: 768px\) \{\s*\.skill-use-overview \.provenance-pins__list \{\s*grid-template-columns: 1fr;/,
    )
  })
})
