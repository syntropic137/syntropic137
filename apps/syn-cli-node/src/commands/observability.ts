/**
 * Observability commands: operational telemetry about the platform itself.
 *
 * "Observability" here means how the running system behaves (request latency).
 * It is NOT "insights": insights are learning-loop analytics about how to
 * improve workflows, speed and cost. See
 * docs/architecture/organization-ubiquitous-language.md.
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { api, unwrap } from "../client/typed.js";
import { print, printDim } from "../output/console.js";
import { style, CYAN, YELLOW } from "../output/ansi.js";
import { Table } from "../output/table.js";

const LATENCY_WINDOWS = ["1h", "24h", "7d", "30d"] as const;
type LatencyWindow = (typeof LATENCY_WINDOWS)[number];

function isLatencyWindow(value: string): value is LatencyWindow {
  return (LATENCY_WINDOWS as readonly string[]).includes(value);
}

const latencyCommand: CommandDef = {
  name: "latency",
  description: "Show API latency to response start (p50/p95/p99) per route",
  options: {
    window: { type: "string", short: "w", description: "1h, 24h, 7d or 30d", default: "24h" },
    route: { type: "string", short: "r", description: "One route template as the API reports it, e.g. /evals" },
  },
  handler: async (parsed: ParsedArgs) => {
    const window = (parsed.values["window"] as string | undefined) ?? "24h";
    if (!isLatencyWindow(window)) {
      throw new Error(`--window must be one of ${LATENCY_WINDOWS.join(", ")}`);
    }
    const route = parsed.values["route"] as string | undefined;
    const d = unwrap(await api.GET("/observability/latency", {
      params: { query: { window, ...(route ? { route } : {}) } },
    }), "Fetch latency");

    // Recorder health first: an empty table is exactly when the drop counters matter.
    const rec = d.recorder;
    if (!rec.running || rec.dropped > 0 || rec.write_failures > 0 || rec.discarded > 0 || rec.cleanup_failures > 0) {
      print(style(
        `  recorder ${rec.running ? "running" : "NOT running"} on this API process: `
          + `${rec.dropped} dropped, ${rec.write_failures} failed writes, ${rec.discarded} discarded, `
          + `${rec.cleanup_failures} connection cleanups failed`,
        YELLOW,
      ));
    }
    if (!d.available) { printDim("Latency store unavailable."); return; }
    if (d.routes.length === 0) { printDim(`No requests recorded in the last ${d.window}.`); return; }

    const ms = (v: number) => `${Math.round(v)}`;
    const table = new Table({ title: `Latency, arrival to response start, last ${d.window} (ms)` });
    table.addColumn("Method");
    table.addColumn("Route", { style: CYAN });
    table.addColumn("Count", { align: "right" });
    table.addColumn("p50", { align: "right" });
    table.addColumn("p95", { align: "right" });
    table.addColumn("p99", { align: "right" });
    table.addColumn("Max", { align: "right" });
    for (const r of d.routes) {
      table.addRow(r.method, r.route, String(r.count), ms(r.p50_ms), ms(r.p95_ms), ms(r.p99_ms), ms(r.max_ms));
    }
    table.print();
  },
};

export const observabilityGroup = new CommandGroup("observability", "Platform observability: API request latency");
observabilityGroup.command(latencyCommand);
