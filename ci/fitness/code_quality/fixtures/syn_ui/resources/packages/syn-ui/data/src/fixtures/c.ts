// CLEAN: composed under a renamed import
import { route, type FixtureRoute } from './define'
export const cRoutes: FixtureRoute[] = [route('GET', '/renamed-spread', () => ({}))]
