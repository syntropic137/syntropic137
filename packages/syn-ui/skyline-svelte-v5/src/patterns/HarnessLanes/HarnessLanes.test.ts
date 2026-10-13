// @vitest-environment jsdom
// Harness Lanes
import '../../components/_test/setup'
import { render, screen } from '@testing-library/svelte'
import { describe, expect, it } from 'vitest'
import HarnessLanes from './HarnessLanes.svelte'

describe('Harness Lanes', () => {
  it('names each lane by what it runs', () => {
    render(HarnessLanes, {
      phases: [
        { name: 'implement', provider: 'claude', span: 3 },
        { name: 'review', provider: 'codex', span: 2 },
      ],
    })
    expect(screen.getAllByRole('listitem').map((l) => l.getAttribute('aria-label'))).toEqual(['claude runs implement', 'codex runs review'])
  })
})
