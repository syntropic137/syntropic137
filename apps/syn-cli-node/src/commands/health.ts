import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
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

function projectionName(entry: Record<string, unknown> | undefined): string {
  return String(entry?.["projection"] ?? "unknown");
}

/** What the read-model block means for whoever is staring at a 404: which
 * projection is behind, how far, and — the part that decides what they do next —
 * whether it is a rebuild that will finish by itself or a projection that has
 * stopped moving and needs them. The API reports those as two independent flags
 * and a wedged rebuild sets both, so this returns a line per condition rather
 * than picking one. */
function readModelLines(subscription: Record<string, unknown>): string[] {
  const lagging = subscription["lagging_projections"];
  const entries = Array.isArray(lagging) ? (lagging as Record<string, unknown>[]) : [];
  const lines: string[] = [];

  if (subscription["is_catching_up"] === true) {
    const lag = subscription["lag"];
    const unit = subscription["lag_unit"] ?? "events";
    const behind = typeof lag === "number" ? `${lag} ${unit} behind` : "lag unknown";
    lines.push(
      `  Rebuilding read models: ${projectionName(entries[0])} is ${behind}. Recently dispatched executions may 404 until this finishes.`,
    );
  }

  if (subscription["is_stalled"] === true) {
    const stuck = entries.filter((entry) => entry["stalled"] === true);
    const names = stuck.length > 0 ? stuck.map(projectionName).join(", ") : "unknown";
    const age = stuck[0]?.["checkpoint_age_seconds"];
    const since = typeof age === "number" ? `, no progress for ${age}s` : "";
    lines.push(
      `  Stalled read models: ${names}${since}. This will NOT clear on its own — check that projection's logs.`,
    );
  }

  return lines;
}

/** Which build answered. The release always; the image tag and commit only
 * when the image build stamped them, since an unstamped build reports null and
 * printing "commit: null" tells a reader nothing they can act on. */
function buildLine(build: components["schemas"]["BuildInfo"]): string {
  const stamps = [build.image_tag, build.commit].filter((s): s is string => Boolean(s));
  return `syn-api ${build.version}` + (stamps.length > 0 ? ` (${stamps.join(", ")})` : "");
}

export const healthCommand: CommandDef = {
  name: "health",
  description: "Check API server health status",
  handler: async () => {
    const data = unwrap(await api.GET("/health"), "Health check");

    const status = data.status ?? "";
    const mode = data.mode ?? "";

    // FIRST, above the verdict. `syn health` is how an agent or an operator
    // answers "is the new build live yet?", and until #1380 the API could not
    // tell them: openapi.json claimed 0.5.1 against a 0.29.1b3 deployment and
    // /health said nothing, leaving `docker inspect` over SSH as the only
    // read. Printing it below a "Degraded" line would bury the answer in the
    // case it is most needed.
    print(style(buildLine(data.build), DIM));

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

      for (const line of readModelLines(record)) print(style(line, YELLOW));
    }
  },
};
