import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { HEALTHY_READ_PATH } from '../../hooks/useReadPathHealth'
import { REBUILDING_EXECUTIONS } from '../../test/readPathFixtures'
import { ReadModelNotice, ReadPathBanner } from '../ReadPathBanner'

describe('ReadPathBanner', () => {
  it('renders nothing while the read path is healthy', () => {
    const { container } = render(<ReadPathBanner health={HEALTHY_READ_PATH} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the API-computed progress while a read model catches up', () => {
    render(<ReadPathBanner health={{ ...HEALTHY_READ_PATH, rebuilding: [REBUILDING_EXECUTIONS] }} />)

    expect(screen.getByTestId('read-path-rebuilding')).toHaveTextContent(
      'Rebuilding execution history - 28% (29,476 events behind). Recent results will appear shortly.',
    )
    expect(screen.queryByTestId('read-path-stuck')).toBeNull()
  })

  it('names every other read model that is rebuilding at the same time', () => {
    const details = {
      ...REBUILDING_EXECUTIONS,
      projection: 'workflow_execution_details',
      label_display: 'execution details',
      progress_display: '61%',
    }
    render(<ReadPathBanner health={{ ...HEALTHY_READ_PATH, rebuilding: [REBUILDING_EXECUTIONS, details] }} />)

    expect(screen.getByTestId('read-path-rebuilding')).toHaveTextContent('Also rebuilding: execution details (61%).')
  })

  it('shows a held projection as an error alert, naming where it is stuck', () => {
    render(
      <ReadPathBanner
        health={{
          ...HEALTHY_READ_PATH,
          held: [{ projection: 'evals', event_type: 'EvalScored', global_nonce: 812 }],
        }}
      />,
    )

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('evals is stuck at event #812 (EvalScored)')
    expect(screen.queryByTestId('read-path-rebuilding')).toBeNull()
  })

  it('shows a halted subscription as an error alert', () => {
    render(<ReadPathBanner health={{ ...HEALTHY_READ_PATH, haltedAt: 4410 }} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Event processing is halted at event #4410')
  })

  it('shows both banners when a projection is held during a rebuild', () => {
    render(
      <ReadPathBanner
        health={{
          rebuilding: [REBUILDING_EXECUTIONS],
          held: [{ projection: 'evals', event_type: 'EvalScored', global_nonce: 812 }],
          haltedAt: null,
        }}
      />,
    )

    expect(screen.getByTestId('read-path-stuck')).toBeInTheDocument()
    expect(screen.getByTestId('read-path-rebuilding')).toBeInTheDocument()
  })
})

describe('ReadModelNotice', () => {
  it('renders nothing for a read model that is not rebuilding', () => {
    const { container } = render(
      <ReadModelNotice status={{ rebuilding: false, projection: 'evals', label_display: 'evals', events_behind: 0 }} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('says the page is incomplete, with the API display strings', () => {
    render(<ReadModelNotice status={REBUILDING_EXECUTIONS} />)
    expect(screen.getByTestId('read-model-notice')).toHaveTextContent(
      'This page may be incomplete while execution history is rebuilt (28%, 29,476 events behind).',
    )
  })
})
