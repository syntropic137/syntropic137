/**
 * Outside links the shell offers (palette Help group, the `?` overlay).
 * The one place these URLs live in syn-ui; the React Layout's footer links
 * to the same feature board. Docs host per ADR-052.
 */
import type { HelpLinks } from '@syn137/skyline-core/screens/palette'

export const DOCS_URL = 'https://docs.syntropic137.com'
export const FEATURE_REQUESTS_URL = 'https://syntropic137.canny.io/'
export const ISSUES_URL = 'https://github.com/syntropic137/syntropic137/issues'

export const HELP_LINKS: HelpLinks = { docs: DOCS_URL, featureRequests: FEATURE_REQUESTS_URL, issues: ISSUES_URL }
