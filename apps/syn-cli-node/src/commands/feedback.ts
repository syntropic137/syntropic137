/**
 * Feedback commands — list.
 *
 * In-app feedback (ADR-016, #105) is captured by the dashboard widget and
 * triaged from here, so an agent can ask what the owner reported without a
 * browser. The feature is off by default; when it is, the API answers a
 * typed 404 naming the flag and this reports that rather than an error.
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printDim } from "../output/console.js";
import { style, CYAN, DIM, GREEN, RED, YELLOW } from "../output/ansi.js";
import { formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";

type FeedbackList = components["schemas"]["FeedbackList"];
type FeatureDisabled = components["schemas"]["FeatureDisabledResponse"];

const STATUS_COLOURS: Record<string, string> = {
  open: YELLOW,
  in_progress: CYAN,
  resolved: GREEN,
  closed: DIM,
  wont_fix: DIM,
};

/** The typed 404 the API answers with when SYN_UI_FEEDBACK_ENABLED is off. */
function disabledNotice(result: { response?: Response; error?: unknown }): string | null {
  if (result.response?.status !== 404) return null;
  const detail = (result.error as FeatureDisabled | undefined)?.detail;
  if (!detail || typeof detail !== "object" || !("feature" in detail)) return null;
  return `${detail.reason} Enable it with ${detail.enable_with ?? "the feature flag"}.`;
}

const listCommand: CommandDef = {
  name: "list",
  description: "List in-app feedback, newest first",
  options: {
    status: { type: "string", short: "s", description: "Filter by status (open, in_progress, resolved, closed, wont_fix)" },
    type: { type: "string", short: "t", description: "Filter by type (bug, feature, ui_ux, performance, question, other)" },
    route: { type: "string", short: "r", description: "Filter by the page path the feedback was left on" },
    execution: { type: "string", short: "e", description: "Filter by the execution the page was about" },
    since: { type: "string", description: "Only feedback created at or after this instant (ISO 8601)" },
    search: { type: "string", description: "Search in comments" },
    page: { type: "string", description: "Page number", default: "1" },
    limit: { type: "string", description: "Items per page (max 100)", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const page = parseInt((parsed.values["page"] as string | undefined) ?? "1", 10);
    const limit = parseInt((parsed.values["limit"] as string | undefined) ?? "50", 10);
    const execution = parsed.values["execution"] as string | undefined;

    const result = await api.GET("/feedback", {
      params: {
        query: {
          status: (parsed.values["status"] as string | undefined) ?? null,
          type: (parsed.values["type"] as string | undefined) ?? null,
          route: (parsed.values["route"] as string | undefined) ?? null,
          subject_kind: execution ? "execution" : null,
          subject_id: execution ?? null,
          created_after: (parsed.values["since"] as string | undefined) ?? null,
          search: (parsed.values["search"] as string | undefined) ?? null,
          page,
          limit,
        },
      },
    });

    const disabled = disabledNotice(result);
    if (disabled) { printDim(disabled); return; }

    const data: FeedbackList = unwrap(result, "List feedback");
    const items = data.items ?? [];
    if (items.length === 0) { printDim("No feedback found."); return; }

    const table = new Table({ title: `Feedback (page ${page}, ${data.total} total)` });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Status");
    table.addColumn("Type");
    table.addColumn("Page");
    table.addColumn("Comment");
    table.addColumn("Created");

    for (const item of items) {
      table.addRow(
        item.id.slice(0, 12),
        style(item.status, STATUS_COLOURS[item.status] ?? RED),
        item.feedback_type,
        item.route ?? item.url,
        (item.comment ?? "—").split("\n")[0]!.slice(0, 60),
        formatTimestamp(item.created_at),
      );
    }
    table.print();

    if (data.total > page * limit) {
      printDim(`Showing page ${page}. Use --page ${page + 1} for more.`);
    }
    print(style(`  ${items.filter((i) => i.media_count > 0).length} with attachments`, DIM));
  },
};

export const feedbackGroup = new CommandGroup("feedback", "Triage in-app feedback from the dashboard");
feedbackGroup.command(listCommand);
