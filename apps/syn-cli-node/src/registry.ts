/**
 * Single source of truth for all CLI command groups and root commands.
 *
 * Both the CLI entrypoint (index.ts) and the doc generator
 * (scripts/generate-cli-docs.ts) import from here. Adding a new command
 * group here automatically registers it everywhere — no second file to update.
 */

import type { CommandDef } from "./framework/command.js";
import type { CommandGroup } from "./framework/command.js";

// Command groups (alphabetical)
import { artifactsGroup } from "./commands/artifacts.js";
import { configGroup } from "./commands/config.js";
import { controlGroup } from "./commands/control.js";
import { conversationsGroup } from "./commands/conversations.js";
import { costsGroup } from "./commands/costs.js";
import { eventsGroup } from "./commands/events.js";
import { executionGroup } from "./commands/execution.js";
import { githubGroup } from "./commands/github.js";
import { insightsGroup } from "./commands/insights.js";
import { marketplaceGroup } from "./commands/marketplace/index.js";
import { metricsGroup } from "./commands/metrics.js";
import { observeGroup } from "./commands/observe.js";
import { orgGroup } from "./commands/org.js";
import { repoGroup } from "./commands/repo.js";
import { sessionsGroup } from "./commands/sessions.js";
import { systemGroup } from "./commands/system.js";
import { triggersGroup } from "./commands/triggers.js";
import { watchGroup } from "./commands/watch.js";
import { workflowGroup } from "./commands/workflow/index.js";

// Root commands
import { healthCommand } from "./commands/health.js";
import { versionCommand } from "./commands/version.js";
import { runCommand } from "./commands/workflow/run.js";

/** All command groups, registered in alphabetical order. */
export const commandGroups: readonly CommandGroup[] = [
  artifactsGroup,
  configGroup,
  controlGroup,
  conversationsGroup,
  costsGroup,
  eventsGroup,
  executionGroup,
  githubGroup,
  insightsGroup,
  marketplaceGroup,
  metricsGroup,
  observeGroup,
  orgGroup,
  repoGroup,
  sessionsGroup,
  systemGroup,
  triggersGroup,
  watchGroup,
  workflowGroup,
];

/** Root-level commands (not in a group). */
export const rootCommands: readonly CommandDef[] = [
  healthCommand,
  {
    ...runCommand,
    description: "Execute a workflow (shortcut for 'syn workflow run')",
  },
  versionCommand,
];
