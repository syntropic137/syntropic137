// @vitest-environment jsdom
// Harness Chip
import '../../components/_test/setup'
import { render, screen } from '@testing-library/svelte'
import { describe, expect, it } from 'vitest'
import HarnessChip from './HarnessChip.svelte'

describe('Harness Chip', () => {
  it('colours the chip dot from the harness gradient token', () => {
    const { container } = render(HarnessChip, { provider: 'codex', label: 'review · codex' })
    expect(screen.getByText('review · codex')).toBeTruthy()
    expect(container.querySelector<HTMLElement>('.sky-harness-chip__dot')!.style.background).toBe('var(--sky-harness-codex-gradient)')
  })
})
