/**
 * Minimal YAML subset parser — zero dependencies.
 *
 * Supports: maps, lists, strings (plain/quoted/multiline), numbers,
 * booleans, null. Enough for workflow.yaml and syntropic137.yaml files.
 *
 * Does NOT support: anchors, aliases, tags, flow sequences/maps on
 * multiple lines, complex keys, merge keys.
 */

type YamlValue =
  | string
  | number
  | boolean
  | null
  | YamlValue[]
  | { [key: string]: YamlValue };

export function parseYaml(input: string): YamlValue {
  const lines = input.split("\n");
  const { value } = parseNode(lines, 0, -1);
  return value;
}

interface ParseResult {
  value: YamlValue;
  nextLine: number;
}

function parseNode(
  lines: string[],
  startLine: number,
  _parentIndent: number,
): ParseResult {
  // Skip blank lines and comments
  let i = startLine;
  while (i < lines.length) {
    const trimmed = lines[i]!.trim();
    if (trimmed === "" || trimmed.startsWith("#")) {
      i++;
      continue;
    }
    break;
  }

  if (i >= lines.length) {
    return { value: null, nextLine: i };
  }

  const line = lines[i]!;
  const indent = getIndent(line);
  const trimmed = line.trim();

  // List item
  if (trimmed.startsWith("- ") || trimmed === "-") {
    return parseList(lines, i, indent);
  }

  // Map key
  if (trimmed.includes(":")) {
    return parseMap(lines, i, indent);
  }

  // Scalar
  return { value: parseScalar(trimmed), nextLine: i + 1 };
}

function parseMap(
  lines: string[],
  startLine: number,
  mapIndent: number,
): ParseResult {
  const result: Record<string, YamlValue> = {};
  let i = startLine;

  while (i < lines.length) {
    const line = lines[i]!;
    const trimmed = line.trim();

    if (trimmed === "" || trimmed.startsWith("#")) {
      i++;
      continue;
    }

    const indent = getIndent(line);
    if (indent < mapIndent) break;
    if (indent > mapIndent) break; // Shouldn't happen at map level

    const colonIdx = findUnquotedColon(trimmed);
    if (colonIdx === -1) break;

    const key = trimmed.slice(0, colonIdx).trim();
    const afterColon = trimmed.slice(colonIdx + 1).trim();

    if (afterColon === "" || afterColon.startsWith("#")) {
      // Block value on next line(s)
      i++;
      const { value, nextLine } = parseNode(lines, i, mapIndent);
      result[key] = value;
      i = nextLine;
    } else if (afterColon === "|" || afterColon === ">") {
      // Multiline string
      i++;
      const { value, nextLine } = parseMultilineString(
        lines,
        i,
        afterColon as "|" | ">",
      );
      result[key] = value;
      i = nextLine;
    } else {
      // Inline value — could be a flow list [a, b, c]
      result[key] = parseInlineValue(afterColon);
      i++;
    }
  }

  return { value: result, nextLine: i };
}

function parseList(
  lines: string[],
  startLine: number,
  listIndent: number,
): ParseResult {
  const result: YamlValue[] = [];
  let i = startLine;

  while (i < lines.length) {
    const line = lines[i]!;
    const trimmed = line.trim();

    if (trimmed === "" || trimmed.startsWith("#")) {
      i++;
      continue;
    }

    const indent = getIndent(line);
    if (indent < listIndent) break;
    if (indent > listIndent) break;

    if (!trimmed.startsWith("- ") && trimmed !== "-") break;

    const afterDash = trimmed.slice(2).trim();

    if (afterDash === "" || trimmed === "-") {
      // Block item on next line(s)
      i++;
      const { value, nextLine } = parseNode(lines, i, listIndent);
      result.push(value);
      i = nextLine;
    } else if (afterDash.includes(":") && !isQuoted(afterDash)) {
      // Inline map start: `- key: value`
      // Re-parse lines starting from this dash as a map with increased indent
      const itemIndent = indent + 2;
      // Rewrite the line temporarily to remove "- " prefix
      const originalLine = lines[i]!;
      lines[i] = " ".repeat(itemIndent) + afterDash;
      const { value, nextLine } = parseMap(lines, i, itemIndent);
      lines[i] = originalLine; // Restore
      result.push(value);
      i = nextLine;
    } else {
      result.push(parseInlineValue(afterDash));
      i++;
    }
  }

  return { value: result, nextLine: i };
}

function parseMultilineString(
  lines: string[],
  startLine: number,
  style: "|" | ">",
): ParseResult {
  let i = startLine;
  const contentLines: string[] = [];
  let blockIndent = -1;

  while (i < lines.length) {
    const line = lines[i]!;
    if (line.trim() === "") {
      contentLines.push("");
      i++;
      continue;
    }
    const indent = getIndent(line);
    if (blockIndent === -1) blockIndent = indent;
    if (indent < blockIndent) break;
    contentLines.push(line.slice(blockIndent));
    i++;
  }

  // Trim trailing empty lines
  while (contentLines.length > 0 && contentLines[contentLines.length - 1] === "") {
    contentLines.pop();
  }

  const value =
    style === "|"
      ? contentLines.join("\n")
      : contentLines.join(" ").replace(/\s+/g, " ").trim();

  return { value, nextLine: i };
}

function parseInlineValue(raw: string): YamlValue {
  // Strip inline comments
  const value = stripInlineComment(raw);

  // Flow sequence: [a, b, c]
  if (value.startsWith("[") && value.endsWith("]")) {
    const inner = value.slice(1, -1).trim();
    if (inner === "") return [];
    return splitFlow(inner).map((item) => parseScalar(item.trim()));
  }

  return parseScalar(value);
}

function parseScalar(raw: string): string | number | boolean | null {
  if (raw === "null" || raw === "~" || raw === "") return null;
  if (raw === "true" || raw === "True" || raw === "TRUE") return true;
  if (raw === "false" || raw === "False" || raw === "FALSE") return false;

  // Quoted strings
  if (
    (raw.startsWith('"') && raw.endsWith('"')) ||
    (raw.startsWith("'") && raw.endsWith("'"))
  ) {
    return raw.slice(1, -1);
  }

  // Numbers
  if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^-?\d+\.\d+$/.test(raw)) return parseFloat(raw);

  return raw;
}

function getIndent(line: string): number {
  let count = 0;
  for (const ch of line) {
    if (ch === " ") count++;
    else break;
  }
  return count;
}

function findUnquotedColon(text: string): number {
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "'" && !inDouble) inSingle = !inSingle;
    else if (ch === '"' && !inSingle) inDouble = !inDouble;
    else if (ch === ":" && !inSingle && !inDouble) {
      // Must be followed by space, end of string, or nothing
      if (i + 1 >= text.length || text[i + 1] === " ") return i;
    }
  }
  return -1;
}

function isQuoted(text: string): boolean {
  return (
    (text.startsWith('"') && text.endsWith('"')) ||
    (text.startsWith("'") && text.endsWith("'"))
  );
}

function stripInlineComment(text: string): string {
  // Only strip " #" (space + hash) outside quotes
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "'" && !inDouble) inSingle = !inSingle;
    else if (ch === '"' && !inSingle) inDouble = !inDouble;
    else if (ch === " " && !inSingle && !inDouble && text[i + 1] === "#") {
      return text.slice(0, i).trim();
    }
  }
  return text;
}

function splitFlow(text: string): string[] {
  const items: string[] = [];
  let current = "";
  let depth = 0;
  let inSingle = false;
  let inDouble = false;

  for (const ch of text) {
    if (ch === "'" && !inDouble) inSingle = !inSingle;
    else if (ch === '"' && !inSingle) inDouble = !inDouble;
    else if (ch === "[" && !inSingle && !inDouble) depth++;
    else if (ch === "]" && !inSingle && !inDouble) depth--;

    if (ch === "," && depth === 0 && !inSingle && !inDouble) {
      items.push(current);
      current = "";
    } else {
      current += ch;
    }
  }

  if (current.trim()) items.push(current);
  return items;
}
