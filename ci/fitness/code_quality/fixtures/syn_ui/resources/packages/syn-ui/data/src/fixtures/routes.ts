// HELPER: planted registry; spreads a and c (renamed), imports b without spreading it
import { aRoutes } from './a'
import { bRoutes } from './b'
import { cRoutes as renamed } from './c'
import type { FixtureRoute } from './define'
export const routes: FixtureRoute[] = [...aRoutes, ...renamed]
export const unused = bRoutes.length
