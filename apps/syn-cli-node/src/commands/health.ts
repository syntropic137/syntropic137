import { apiGet } from "../client/api.js";
import type { CommandDef } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { BOLD, DIM, GREEN, RED, YELLOW, style } from "../output/ansi.js";
import { print } from "../output/console.js";

interface HealthResponse {
  status: string;
  mode: string;
  degraded_reasons?: string[];
  subscription?: { status: string };
}

export const healthCommand: CommandDef = {
  name: "health",
  description: "Check API server health status",
  handler: async () => {
    const data = await apiGet<HealthResponse>("/health");

    const { status, mode } = data;

    if (status === "healthy" && mode === "full") {
      print(style("Healthy", BOLD, GREEN) + " — all systems operational");
    } else if (status === "healthy") {
      print(style("Degraded", BOLD, YELLOW) + ` — mode: ${mode}`);
      if (data.degraded_reasons) {
        for (const reason of data.degraded_reasons) {
          print(style(`  \u2022 ${reason}`, YELLOW));
        }
      }
    } else {
      print(style("Unhealthy", BOLD, RED) + ` — status: ${status}`);
      throw new CLIError("API is unhealthy");
    }

    if (data.subscription) {
      print(style("  Event store: connected", DIM));
      print(style(`  Subscription: ${data.subscription.status}`, DIM));
    }
  },
};
