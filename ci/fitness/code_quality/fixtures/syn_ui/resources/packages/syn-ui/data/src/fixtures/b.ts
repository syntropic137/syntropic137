// PROBE: fixture routes imported by routes.ts but never spread (review 1)
import { route, type FixtureRoute } from './define'
export const bRoutes: FixtureRoute[] = [route('GET', '/imported-not-spread', () => ({}))]
