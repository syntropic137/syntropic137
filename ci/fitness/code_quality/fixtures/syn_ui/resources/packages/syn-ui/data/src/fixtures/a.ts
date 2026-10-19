// CLEAN: composed fixture routes, plus routes that must not count
import { route, type FixtureRoute } from './define'
const h = () => ({})
const shared = [route('GET', '/via-helper-array', h)]
export const aRoutes: FixtureRoute[] = [
  route('GET', '/things/:id', h),
  route('POST', '/things/:id/make', h),
  route('GET', '/things', h),
  route('GET', '/hidden/:id', h),
  route('GET', '/arrow', h),
  route('GET', '/exported-arrow/:id', h),
  route('GET', '/covered/uncovered', h),
  route('GET', '/covered', h),
  route('PUT', '/a/:x/b', h),
  route('GET', '/indented', h),
  ...shared,
  // A string that looks like a route serves nothing (review 2).
  "route('GET', '/fabricated', h)" as unknown as FixtureRoute,
]
route('GET', '/outside-array', h)
const extra = [route('GET', '/never', h)]
void extra
