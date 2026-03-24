/**
 * Shared markdown formatting helpers for tool output.
 */

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
