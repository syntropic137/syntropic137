import '@testing-library/jest-dom/vitest'

/**
 * jsdom ships no `matchMedia`, and every page renders `useIsMobile`.
 *
 * Reports a desktop viewport, which is the layout the table-based assertions
 * in the page tests are written against. Tests that care about the breakpoint
 * itself install their own (see `useMediaQuery.test.ts`).
 */
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string): MediaQueryList =>
      ({
        matches: query.includes('min-width'),
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  })
}
