import { CLI_DESCRIPTION, CLI_NAME, CLI_VERSION } from "./config.js";
import { healthCommand } from "./commands/health.js";
import { versionCommand } from "./commands/version.js";
import { workflowGroup } from "./commands/workflow/index.js";
import { marketplaceGroup } from "./commands/marketplace/index.js";
import { agentGroup } from "./commands/agent.js";
import { artifactsGroup } from "./commands/artifacts.js";
import { configGroup } from "./commands/config.js";
import { controlGroup } from "./commands/control.js";
import { conversationsGroup } from "./commands/conversations.js";
import { costsGroup } from "./commands/costs.js";
import { eventsGroup } from "./commands/events.js";
import { executionGroup } from "./commands/execution.js";
import { insightsGroup } from "./commands/insights.js";
import { metricsGroup } from "./commands/metrics.js";
import { observeGroup } from "./commands/observe.js";
import { orgGroup } from "./commands/org.js";
import { repoGroup } from "./commands/repo.js";
import { sessionsGroup } from "./commands/sessions.js";
import { systemGroup } from "./commands/system.js";
import { triggersGroup } from "./commands/triggers.js";
import { watchGroup } from "./commands/watch.js";
import { CLI } from "./framework/cli.js";

// Import run command handler for the top-level "run" shortcut
import { runCommand } from "./commands/workflow/run.js";

const cli = new CLI({
  name: CLI_NAME,
  description: CLI_DESCRIPTION,
  version: CLI_VERSION,
});

// Root-level commands
cli.addCommand(healthCommand);
cli.addCommand(versionCommand);
cli.addCommand({
  ...runCommand,
  description: "Execute a workflow (shortcut for 'syn workflow run')",
});

// Command groups
cli.addGroup(workflowGroup);
cli.addGroup(marketplaceGroup);
cli.addGroup(agentGroup);
cli.addGroup(artifactsGroup);
cli.addGroup(configGroup);
cli.addGroup(controlGroup);
cli.addGroup(conversationsGroup);
cli.addGroup(costsGroup);
cli.addGroup(eventsGroup);
cli.addGroup(executionGroup);
cli.addGroup(insightsGroup);
cli.addGroup(metricsGroup);
cli.addGroup(observeGroup);
cli.addGroup(orgGroup);
cli.addGroup(repoGroup);
cli.addGroup(sessionsGroup);
cli.addGroup(systemGroup);
cli.addGroup(triggersGroup);
cli.addGroup(watchGroup);

cli.run();
