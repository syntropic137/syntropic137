import { api, unwrap } from "../client/typed.js";
import type { CommandDef } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { BOLD, DIM, GREEN, RED, YELLOW, style } from "../output/ansi.js";
import { print } from "../output/console.js";

export const healthCommand: CommandDef = {
  name: "health",
  description: "Check API server health status",
  handler: async () => {
    const data = unwrap(await api.GET("/health"), "Health check");

    // Health endpoint returns { [key: string]: string } in the spec
    const status = data["status"] ?? "";
    const mode = data["mode"] ?? "";

    if (status === "healthy" && mode === "full") {
      print(style("Healthy", BOLD, GREEN) + " — all systems operational");
    } else if (status === "healthy") {
      print(style("Degraded", BOLD, YELLOW) + ` — mode: ${mode}`);
      const reasons = data["degraded_reasons"];
      if (reasons && typeof reasons === "string") {
        for (const reason of reasons.split(",")) {
          print(style(`  \u2022 ${reason.trim()}`, YELLOW));
        }
      }
    } else {
      print(style("Unhealthy", BOLD, RED) + ` — status: ${status}`);
      throw new CLIError("API is unhealthy");
    }

    const subscription = data["subscription"];
    if (subscription) {
      print(style("  Event store: connected", DIM));
      const subStatus =
        typeof subscription === "object" && subscription !== null
          ? ((subscription as Record<string, unknown>)["status"] ?? "unknown")
          : subscription;
      print(style(`  Subscription: ${subStatus}`, DIM));
    }
  },
};
