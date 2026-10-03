/**
 * Reporting for commands that START or ACTIVATE work on a deployment.
 *
 * WHY this exists as one place: a workflow ID, a trigger ID and an execution
 * ID are all deployment-relative — the same string names different things on
 * localhost and on a VPS — so a report that gives back only an ID does not say
 * what was started (issue #1264). Naming the deployment was previously decided
 * command by command, and the commands that never got round to it are exactly
 * the ones that shipped the bug. Routing every such report through here makes
 * the deployment an invariant of the report instead of a judgement call at each
 * call site.
 *
 * Deliberately NOT for pause, cancel, stop or inject: those act on work that is
 * already running, and the caller already holds an ID it got from somewhere.
 */

import type { TypedClient } from "../client/typed.js";
import { print, printSuccess } from "./console.js";

/** One labelled line under the headline, e.g. `Execution ID: exec-1`. */
export interface StartedDetail {
  label: string;
  value: string;
}

const DEPLOYMENT_LABEL = "Deployment";

/**
 * Print a headline plus the deployment the work was started on, followed by
 * `details`, aligned.
 *
 * The deployment is read from `client`, never from the environment, so the
 * host named here is the host the request was actually sent to.
 */
export function printStarted(
  client: TypedClient,
  headline: string,
  details: StartedDetail[] = [],
): void {
  const width = Math.max(
    DEPLOYMENT_LABEL.length,
    ...details.map((d) => d.label.length),
  );
  const line = (label: string, value: string): string =>
    `  ${(label + ":").padEnd(width + 2)}${value}`;

  printSuccess(headline);
  print(line(DEPLOYMENT_LABEL, client.deployment));
  for (const detail of details) {
    print(line(detail.label, detail.value));
  }
}
