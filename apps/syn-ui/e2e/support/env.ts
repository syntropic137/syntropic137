/**
 * Where the suite points and what it may assume about the app under test.
 *
 *   E2E_BASE_URL / BASE_URL  App root, including any deploy base, e.g.
 *                            http://127.0.0.1:5173/ (React) or
 *                            http://127.0.0.1:8080/next/ (Skyline at /next).
 *                            Unset: Playwright starts syn-ui in fixtures mode.
 *   E2E_TARGET               'skyline' (default) or 'react'. Picks the few
 *                            selectors that cannot be shared (landmark names,
 *                            the phone dock) and the heading wording.
 *   E2E_DATA                 'fixtures' (default when the suite starts the
 *                            server) or 'live'. Data-specific checks (names,
 *                            models, fixture IDs) only run on fixtures.
 *   E2E_ID_<KIND>            Detail IDs for live data: WORKFLOW, EXECUTION,
 *                            EVAL, SESSION, ARTIFACT, TRIGGER. Unset on live
 *                            data: the ID is taken from the first matching
 *                            link on the list page.
 *   E2E_CONSOLE_IGNORE       Regex of console errors to tolerate (live API
 *                            noise, for example).
 */

export type Target = 'skyline' | 'react'
export type DataMode = 'fixtures' | 'live'

const rawBase = process.env.E2E_BASE_URL ?? process.env.BASE_URL ?? ''

/** Port the suite's own fixtures server listens on (not 5174, so a dev server there is never reused by mistake). */
export const E2E_PORT = Number(process.env.E2E_PORT ?? 5199)

/** True when Playwright should start syn-ui itself. */
export const startsOwnServer = rawBase === ''

/** Always ends with "/" so relative gotos keep the deploy base. */
export const BASE_URL = (rawBase || `http://127.0.0.1:${E2E_PORT}/`).replace(/\/?$/, '/')

export const TARGET: Target = process.env.E2E_TARGET === 'react' ? 'react' : 'skyline'

export const DATA: DataMode = (process.env.E2E_DATA as DataMode | undefined) ?? (startsOwnServer ? 'fixtures' : 'live')

export const CONSOLE_IGNORE: RegExp | null = process.env.E2E_CONSOLE_IGNORE ? new RegExp(process.env.E2E_CONSOLE_IGNORE) : null

export const isSkyline = TARGET === 'skyline'
export const isFixtures = DATA === 'fixtures'
