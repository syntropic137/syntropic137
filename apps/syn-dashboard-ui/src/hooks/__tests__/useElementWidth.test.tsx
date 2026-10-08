import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useElementWidth } from '../useElementWidth'

function Probe() {
  const [ref, width] = useElementWidth<HTMLDivElement>(600)
  return <div ref={ref}>{width}</div>
}

describe('useElementWidth', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is the fallback where there is no ResizeObserver', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    render(<Probe />)
    expect(screen.getByText('600')).toBeInTheDocument()
  })

  it('follows the measured width, so a 411px phone gets a 411-unit viewBox', () => {
    let report: ResizeObserverCallback = () => {}
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb: ResizeObserverCallback) {
          report = cb
        }
        observe() {}
        disconnect() {}
        unobserve() {}
      },
    )
    render(<Probe />)
    act(() => report([{ contentRect: { width: 411.4 } } as ResizeObserverEntry], {} as ResizeObserver))
    expect(screen.getByText('411')).toBeInTheDocument()
  })
})
