// @vitest-environment jsdom
// Tool Log Ticker: plays only while visible
import '../../components/_test/setup'
import { render } from '@testing-library/svelte'
import { tick } from 'svelte'
import { describe, expect, it, vi } from 'vitest'
import { TOOL_LOG_EXAMPLE_ROWS } from './examples'
import ToolLogTicker from './ToolLogTicker.svelte'

describe('Tool Log Ticker', () => {
  it('scrolls a duplicated list only while it is on screen', async () => {
    let report: ((visible: boolean) => void) | undefined
    class FakeObserver {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        report = (visible) => cb([{ isIntersecting: visible }])
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('IntersectionObserver', FakeObserver)
    try {
      const { container } = render(ToolLogTicker, { rows: TOOL_LOG_EXAMPLE_ROWS })
      const track = container.querySelector<HTMLElement>('.sky-scroll')!
      expect(track.style.animationDuration).toBe('14s')
      expect(track.style.animationIterationCount).toBe('1')
      expect(track.style.animationPlayState).toBe('paused')
      report?.(true)
      await tick()
      expect(track.style.animationPlayState).toBe('running')
      report?.(false)
      await tick()
      expect(track.style.animationPlayState).toBe('paused')
      expect(container.querySelectorAll('ol')).toHaveLength(2)
      expect(container.querySelectorAll('ol[aria-hidden="true"]')).toHaveLength(1)
    } finally {
      vi.unstubAllGlobals()
    }
  })
  it('stands still at speed 0', () => {
    const { container } = render(ToolLogTicker, { rows: TOOL_LOG_EXAMPLE_ROWS, speed: 0 })
    expect(container.querySelector('.sky-scroll')).toBeNull()
    expect(container.querySelectorAll('ol')).toHaveLength(1)
  })
})
