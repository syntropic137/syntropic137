import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import type { BuildInfo } from '../../api'
import { deployedTooltipText } from '../../utils/serverBuild'
import { Layout } from '../Layout'
import { ServerVersion } from '../ServerVersion'

vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  getBuildInfo: vi.fn(),
}))

import { getBuildInfo } from '../../api'

const STARTED_AT = '2031-02-03T04:05:06Z'
/** Two hours and a minute after STARTED_AT. */
const NOW = Date.parse('2031-02-03T06:06:00Z')

const makeBuild = (overrides: Partial<BuildInfo> = {}): BuildInfo => ({
  version: '0.33.0b1',
  version_status: 'installed',
  image_tag: 'v0.33.0-beta.1',
  commit: '9f3c1ab2d4e5f60718293a4b5c6d7e8f90a1b2c3',
  started_at: STARTED_AT,
  started_at_display: '2031-02-03 04:05 UTC',
  ...overrides,
})

/** The viewer's locale and zone, the same way the dashboard renders every timestamp. */
const localStart = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
  new Date(STARTED_AT),
)

describe('deployedTooltipText', () => {
  it('names the local deploy time, how long ago it was, and the short commit', () => {
    expect(deployedTooltipText(makeBuild(), NOW)).toBe(`Deployed ${localStart} (2h ago) · commit 9f3c1ab`)
  })

  it('leaves the commit out rather than inventing one when the image did not stamp it', () => {
    expect(deployedTooltipText(makeBuild({ commit: null }), NOW)).toBe(`Deployed ${localStart} (2h ago)`)
  })
})

describe('ServerVersion', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("labels the server's image tag, not the bundle's version", () => {
    render(<ServerVersion build={makeBuild({ image_tag: 'v9.9.9' })} bundleIsStale={false} />)
    expect(screen.getByText('v9.9.9')).toBeInTheDocument()
    expect(screen.queryByText(`v${__APP_VERSION__}`)).not.toBeInTheDocument()
  })

  it('falls back to the release when the image is not tagged', () => {
    render(<ServerVersion build={makeBuild({ image_tag: null, version: '9.9.9' })} bundleIsStale={false} />)
    expect(screen.getByText('v9.9.9')).toBeInTheDocument()
  })

  it('shows the deploy tooltip on hover and hides it on leave', () => {
    render(<ServerVersion build={makeBuild()} bundleIsStale={false} />)
    const label = screen.getByText('v0.33.0-beta.1')
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    fireEvent.mouseEnter(label)
    expect(screen.getByRole('tooltip')).toHaveTextContent(`Deployed ${localStart} (2h ago) · commit 9f3c1ab`)

    fireEvent.mouseLeave(label)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('shows the tooltip on keyboard focus, describes the label with it, and Escape dismisses it', () => {
    render(<ServerVersion build={makeBuild()} bundleIsStale={false} />)
    const label = screen.getByText('v0.33.0-beta.1')
    expect(label).toHaveAttribute('tabindex', '0')

    fireEvent.focus(label)
    const tooltip = screen.getByRole('tooltip')
    expect(label).toHaveAttribute('aria-describedby', tooltip.id)
    expect(label).toHaveAccessibleDescription(/^Deployed .* \(2h ago\) · commit 9f3c1ab$/)

    fireEvent.keyDown(label, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('offers a reload only when the bundle is stale', () => {
    const reload = vi.fn()
    const original = window.location
    Object.defineProperty(window, 'location', { configurable: true, value: { ...original, reload } })
    try {
      const { rerender } = render(<ServerVersion build={makeBuild()} bundleIsStale={false} />)
      expect(screen.queryByRole('button', { name: /new version/i })).not.toBeInTheDocument()

      rerender(<ServerVersion build={makeBuild()} bundleIsStale />)
      fireEvent.click(screen.getByRole('button', { name: 'New version: reload' }))
      expect(reload).toHaveBeenCalledTimes(1)
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original })
    }
  })
})

describe('Layout', () => {
  it("shows the server's build in the sidebar, not the bundle's", async () => {
    vi.mocked(getBuildInfo).mockResolvedValue(makeBuild({ image_tag: 'v42.0.0', version: '42.0.0' }))

    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    )

    expect(await screen.findByText('v42.0.0')).toBeInTheDocument()
    // The deployed release differs from the bundle's, so the page is stale.
    expect(screen.getByRole('button', { name: 'New version: reload' })).toBeInTheDocument()
  })
})
