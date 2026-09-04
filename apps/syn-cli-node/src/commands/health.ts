import { api, unwrap } from "../client/typed.js";
import type { CommandDef } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { BOLD, DIM, GREEN, RED, YELLOW, style } from "../output/ansi.js";
import { print } from "../output/console.js";

/** `degraded_reasons` is a JSON array of strings. It was previously read as a
 * comma-joined string, so every reason the API sent was silently dropped and
 * `syn health` said "Degraded" without ever saying why. */
function reasonsOf(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === "string") return value.split(",").map((r) => r.trim());
  return [];
}

/** The lagging projection furthest behind — the answer to "which one is holding
 * this up" — plus how far behind it is, in the unit the API names. */
function catchUpLine(subscription: Record<string, unknown>): string | null {
  if (subscription["is_catching_up"] !== true) return null;

  const lag = subscription["lag"];
  const unit = subscription["lag_unit"] ?? "events";
  const behind = typeof lag === "number" ? `${lag} ${unit} behind` : "lag unknown";

  const lagging = subscription["lagging_projections"];
  const worst =
    Array.isArray(lagging) && lagging.length > 0
      ? ((lagging[0] as Record<string, unknown>)["projection"] ?? "unknown")
      : "unknown";

  return `  Rebuilding read models: ${worst} is ${behind}. Recently dispatched executions may 404 until this finishes.`;
}

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
      for (const reason of reasonsOf(data["degraded_reasons"])) {
        print(style(`  • ${reason}`, YELLOW));
      }
    } else {
      print(style("Unhealthy", BOLD, RED) + ` — status: ${status}`);
      throw new CLIError("API is unhealthy");
    }

    const subscription = data["subscription"];
    if (subscription) {
      print(style("  Event store: connected", DIM));
      const isObject = typeof subscription === "object" && subscription !== null;
      const record = isObject ? (subscription as Record<string, unknown>) : {};
      const subStatus = isObject ? (record["status"] ?? "unknown") : subscription;
      print(style(`  Subscription: ${subStatus}`, DIM));

      const catchUp = catchUpLine(record);
      if (catchUp) print(style(catchUp, YELLOW));
    }
  },
};
