/**
 * Every fixture route, in one table. Add a resource's routes here when you
 * add its fixture file. Order matters only when two patterns overlap: put
 * the more specific path first.
 */
import { artifactRoutes } from './artifacts'
import { evalRoutes } from './evals'
import { executionRoutes } from './executions'
import { insightRoutes } from './insights'
import { observabilityRoutes } from './observability'
import { repoRoutes } from './repos'
import type { FixtureRoute } from './define'
import { sessionRoutes } from './sessions'
import { trendRoutes } from './trends'
import { triggerRoutes } from './triggers'
import { workflowRoutes } from './workflows'

export const routes: FixtureRoute[] = [
  ...trendRoutes,
  ...workflowRoutes,
  ...executionRoutes,
  ...sessionRoutes,
  ...evalRoutes,
  ...artifactRoutes,
  ...triggerRoutes,
  ...repoRoutes,
  ...observabilityRoutes,
  ...insightRoutes,
]
