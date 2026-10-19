// HELPER: routes in a test file never count (review 1)
import { route } from './define'
export const testRoutes = [route('GET', '/in-test-file', () => ({}))]
