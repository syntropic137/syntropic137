/**
 * The workflow's Phase Pipeline card says what each phase will run and what it
 * has cost, without laundering either.
 *
 * Phases are the real definitions from GET /workflows/multi-agent-programmatic
 * (beta.7). The card used to show only "Claude"/"Codex" - the alias resolution
 * lived on the editor alone - and a per-phase "$0.0000" for work nobody could
 * price.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { PhaseDefinition, PhaseMetrics } from '../../../types'
import { PhasePipeline } from '../PhasePipeline'

const PLAN: PhaseDefinition = {
  phase_id: 'plan',
  name: 'Plan (claude)',
  order: 1,
  description: null,
  agent_type: '',
  prompt_template: 'Write a one-paragraph plan.',
  timeout_seconds: 300,
  allowed_tools: [],
  argument_hint: null,
  model: 'opus',
  resolved_model: 'claude-opus-5-5',
  resolution_basis: 'expected',
  model_display: 'opus → claude-opus-5-5',
  provider: 'claude',
}

const IMPLEMENT: PhaseDefinition = {
  ...PLAN,
  phase_id: 'implement',
  name: 'Implement (codex)',
  order: 2,
  model: 'gpt-sol',
  resolved_model: 'gpt-6-sol',
  resolution_basis: 'translated',
  model_display: 'gpt-sol → gpt-6-sol',
  provider: 'codex',
}

function metric(overrides: Partial<PhaseMetrics> & { phase_id: string }): PhaseMetrics {
  return {
    phase_name: overrides.phase_id,
    status: 'completed',
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 68233,
    cost_usd: '0',
    unpriced_observation_count: 0,
    cost_in_progress: false,
    duration_seconds: 26.6,
    artifact_count: 1,
    ...overrides,
  }
}

describe('workflow Phase Pipeline card', () => {
  it('shows what the model alias resolves to, beside the provider', () => {
    render(<PhasePipeline phases={[PLAN, IMPLEMENT]} phaseMetrics={undefined} />)
    expect(screen.getByText('opus → claude-opus-5-5')).toBeTruthy()
    expect(screen.getByText('gpt-sol → gpt-6-sol')).toBeTruthy()
    expect(screen.getByText('Claude')).toBeTruthy()
    expect(screen.getByText('Codex')).toBeTruthy()
  })

  it('falls back to the raw model when the API sends no display', () => {
    render(
      <PhasePipeline phases={[{ ...PLAN, model_display: null, model: 'sonnet' }]} phaseMetrics={undefined} />,
    )
    expect(screen.getByText('sonnet')).toBeTruthy()
  })

  it('renders a priced phase cost from its decimal string', () => {
    render(
      <PhasePipeline
        phases={[PLAN]}
        phaseMetrics={[metric({ phase_id: 'plan', cost_usd: '0.30566780000000005' })]}
      />,
    )
    expect(screen.getByText('$0.3057')).toBeTruthy()
  })

  it('says unpriced, not $0.0000, when nothing in the phase could be priced', () => {
    const { container } = render(
      <PhasePipeline
        phases={[IMPLEMENT]}
        phaseMetrics={[metric({ phase_id: 'implement', cost_usd: '0', unpriced_observation_count: 4 })]}
      />,
    )
    expect(screen.getByText('unpriced')).toBeTruthy()
    expect(container.textContent).not.toContain('$0.0000')
  })

  it('marks a partly-priced phase as a lower bound', () => {
    render(
      <PhasePipeline
        phases={[IMPLEMENT]}
        phaseMetrics={[metric({ phase_id: 'implement', cost_usd: '0.1324232', unpriced_observation_count: 2 })]}
      />,
    )
    expect(screen.getByText('≥$0.1324 (partial)')).toBeTruthy()
  })

  it('marks a running phase cost as counted so far, not settled', () => {
    render(
      <PhasePipeline
        phases={[IMPLEMENT]}
        phaseMetrics={[metric({ phase_id: 'implement', status: 'running', cost_usd: '0.1324232', cost_in_progress: true })]}
      />,
    )
    const cost = screen.getByTitle('Counted so far; this phase is still running')
    expect(cost.textContent).toBe('$0.1324 so far')
  })

  it('shows a settled phase cost without the so-far marker', () => {
    render(
      <PhasePipeline
        phases={[IMPLEMENT]}
        phaseMetrics={[metric({ phase_id: 'implement', cost_usd: '0.1324232' })]}
      />,
    )
    expect(screen.getByText('$0.1324')).toBeTruthy()
    expect(screen.queryByText(/so far/)).toBeNull()
  })

  it('lists each declared skill with its repo, short SHA and a link to that version', () => {
    const sha = '7e48aad9c7186bb03b8b0df899f56b7cd3b2a454'
    render(
      <PhasePipeline
        phases={[
          {
            ...PLAN,
            skills: [
              {
                name: 'architecture',
                source_url: 'https://github.com/syntropic137/software-leverage-points',
                version: sha,
                name_overridden: false,
                raw: null,
              },
              // `PhaseRefDetail.from_stored("acme/skills/foo@v1")`: a remote
              // shorthand the API keeps whole, which is not a local skill.
              { name: null, source_url: null, version: null, name_overridden: false, raw: 'acme/skills/foo@v1' },
              // `SkillRef("git@github.com:org/skills@v1")` through `from_stored`.
              { name: 'skills', source_url: 'git@github.com:org/skills', version: 'v1', name_overridden: false, raw: null },
            ],
          },
        ]}
        phaseMetrics={undefined}
      />,
    )
    const [pinned, shorthand, ssh] = screen.getAllByTestId('skill-ref')
    expect(pinned.textContent).toContain('architecture')
    expect(pinned.textContent).toContain('syntropic137/software-leverage-points')
    expect(pinned.textContent).toContain('7e48aad')
    expect(pinned.textContent).not.toContain(sha)
    expect(screen.getByRole('link', { name: 'Source of architecture at 7e48aad' }).getAttribute('href')).toBe(
      `https://github.com/syntropic137/software-leverage-points/tree/${sha}`,
    )
    expect(shorthand.textContent).toContain('acme/skills/foo@v1')
    expect(shorthand.textContent).not.toMatch(/local/i)
    expect(ssh.textContent).toContain('org/skills @ v1')
    expect(screen.getByRole('link', { name: 'Source of skills at v1' }).getAttribute('href')).toBe(
      'https://github.com/org/skills/tree/v1',
    )
  })

  it('says a phase declares no skills rather than leaving it blank', () => {
    render(<PhasePipeline phases={[PLAN]} phaseMetrics={undefined} />)
    expect(screen.getByTestId('phase-skills').textContent).toBe('Skillsnone')
  })
})
