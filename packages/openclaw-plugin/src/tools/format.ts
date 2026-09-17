/**
 * Shared markdown formatting helpers for tool output.
 */

import type { SyntropicClient } from "../client.js";

/** Build a markdown table with a title and `| Field | Value |` rows. */
export function buildMarkdownTable(
  title: string,
  rows: readonly [string, string][],
): string[] {
  return [
    `## ${title}`,
    "",
    `| Field | Value |`,
    `|-------|-------|`,
    ...rows.map(([field, value]) => `| ${field} | ${value} |`),
  ];
}

/** Build a `### heading` section with a bullet list from key-value entries. */
export function buildBreakdownSection(
  heading: string,
  entries: readonly [string, unknown][],
): string[] {
  if (entries.length === 0) return [];
  return [
    "",
    `### ${heading}`,
    ...entries.map(([key, value]) => `- ${key}: $${value}`),
  ];
}

/** Format byte counts as human-readable sizes. */
export function formatSize(bytes: number): string {
  return bytes > 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${bytes} bytes`;
}

/**
 * Format the result of a tool that STARTED or ACTIVATED work on a deployment.
 *
 * WHY every such tool goes through here: a workflow ID, a trigger ID and an
 * execution ID are all deployment-relative — the same string names different
 * things on localhost and on a VPS — so a result that hands back only an ID
 * does not say what was started (issue #1264). Naming the deployment used to be
 * decided tool by tool, and the tools that never got round to it are exactly
 * the ones that shipped the bug. The deployment is read from `client`, never
 * resolved again here, so the host named is the host the request went to.
 *
 * Deliberately NOT for pause, cancel or inject: those act on work that is
 * already running.
 */
export function formatStarted(
  client: Pick<SyntropicClient, "baseUrl">,
  title: string,
  details: readonly [string, string][],
  footer: readonly string[] = [],
): { content: string } {
  return {
    content: [
      `## ${title}`,
      "",
      `- **Deployment:** ${client.baseUrl}`,
      ...details.map(([label, value]) => `- **${label}:** ${value}`),
      ...(footer.length > 0 ? ["", ...footer] : []),
    ].join("\n"),
  };
}
