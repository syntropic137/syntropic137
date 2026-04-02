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

function skipBlanksAndComments(lines: string[], start: number): number {
  let i = start;
  while (i < lines.length) {
    const trimmed = lines[i]!.trim();
    if (trimmed !== "" && !trimmed.startsWith("#")) break;
    i++;
  }
  return i;
}

function parseNode(
  lines: string[],
  startLine: number,
  _parentIndent: number,
): ParseResult {
  const i = skipBlanksAndComments(lines, startLine);

  if (i >= lines.length) {
    return { value: null, nextLine: i };
  }

  const line = lines[i]!;
  const indent = getIndent(line);
  const trimmed = line.trim();

  if (trimmed.startsWith("- ") || trimmed === "-") {
    return parseList(lines, i, indent);
  }

  if (trimmed.includes(":")) {
    return parseMap(lines, i, indent);
  }

  return { value: parseScalar(trimmed), nextLine: i + 1 };
}

function parseMapEntry(
  lines: string[],
  i: number,
  afterColon: string,
  mapIndent: number,
): ParseResult {
  if (afterColon === "" || afterColon.startsWith("#")) {
    return parseNode(lines, i + 1, mapIndent);
  }

  if (afterColon === "|" || afterColon === ">") {
    return parseMultilineString(lines, i + 1, afterColon as "|" | ">");
  }

  return { value: parseInlineValue(afterColon), nextLine: i + 1 };
}

function parseMap(
  lines: string[],
  startLine: number,
  mapIndent: number,
): ParseResult {
  const result: Record<string, YamlValue> = {};
  let i = startLine;

  while (i < lines.length) {
    const trimmed = lines[i]!.trim();

    if (trimmed === "" || trimmed.startsWith("#")) {
      i++;
      continue;
    }

    const indent = getIndent(lines[i]!);
    if (indent !== mapIndent) break;

    const colonIdx = findUnquotedColon(trimmed);
    if (colonIdx === -1) break;

    const key = trimmed.slice(0, colonIdx).trim();
    const afterColon = trimmed.slice(colonIdx + 1).trim();

    const { value, nextLine } = parseMapEntry(lines, i, afterColon, mapIndent);
    result[key] = value;
    i = nextLine;
  }

  return { value: result, nextLine: i };
}

function parseListItem(
  lines: string[],
  i: number,
  trimmed: string,
  indent: number,
): ParseResult {
  const afterDash = trimmed.slice(2).trim();

  if (afterDash === "" || trimmed === "-") {
    const { value, nextLine } = parseNode(lines, i + 1, indent);
    return { value, nextLine };
  }

  if (afterDash.includes(":") && !isQuoted(afterDash)) {
    return parseInlineMapItem(lines, i, afterDash, indent);
  }

  return { value: parseInlineValue(afterDash), nextLine: i + 1 };
}

function parseInlineMapItem(
  lines: string[],
  i: number,
  afterDash: string,
  indent: number,
): ParseResult {
  const itemIndent = indent + 2;
  const originalLine = lines[i]!;
  lines[i] = " ".repeat(itemIndent) + afterDash;
  const { value, nextLine } = parseMap(lines, i, itemIndent);
  lines[i] = originalLine;
  return { value, nextLine };
}

function parseList(
  lines: string[],
  startLine: number,
  listIndent: number,
): ParseResult {
  const result: YamlValue[] = [];
  let i = startLine;

  while (i < lines.length) {
    const trimmed = lines[i]!.trim();

    if (trimmed === "" || trimmed.startsWith("#")) {
      i++;
      continue;
    }

    const indent = getIndent(lines[i]!);
    if (indent !== listIndent) break;
    if (!trimmed.startsWith("- ") && trimmed !== "-") break;

    const { value, nextLine } = parseListItem(lines, i, trimmed, indent);
    result.push(value);
    i = nextLine;
  }

  return { value: result, nextLine: i };
}

function collectMultilineContent(
  lines: string[],
  startLine: number,
): { contentLines: string[]; nextLine: number } {
  const contentLines: string[] = [];
  let i = startLine;
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

  while (contentLines.length > 0 && contentLines[contentLines.length - 1] === "") {
    contentLines.pop();
  }

  return { contentLines, nextLine: i };
}

function parseMultilineString(
  lines: string[],
  startLine: number,
  blockStyle: "|" | ">",
): ParseResult {
  const { contentLines, nextLine } = collectMultilineContent(lines, startLine);

  const value =
    blockStyle === "|"
      ? contentLines.join("\n")
      : contentLines.join(" ").replace(/\s+/g, " ").trim();

  return { value, nextLine };
}

function parseInlineValue(raw: string): YamlValue {
  const value = stripInlineComment(raw);

  if (value.startsWith("[") && value.endsWith("]")) {
    const inner = value.slice(1, -1).trim();
    if (inner === "") return [];
    return splitFlow(inner).map((item) => parseScalar(item.trim()));
  }

  return parseScalar(value);
}

const TRUE_VALUES = new Set(["true", "True", "TRUE"]);
const FALSE_VALUES = new Set(["false", "False", "FALSE"]);
const NULL_VALUES = new Set(["null", "~", ""]);

function parseQuoted(raw: string): string | null {
  if (
    (raw.startsWith('"') && raw.endsWith('"')) ||
    (raw.startsWith("'") && raw.endsWith("'"))
  ) {
    return raw.slice(1, -1);
  }
  return null;
}

function parseNumber(raw: string): number | null {
  if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^-?\d+\.\d+$/.test(raw)) return parseFloat(raw);
  return null;
}

function parseScalar(raw: string): string | number | boolean | null {
  if (NULL_VALUES.has(raw)) return null;
  if (TRUE_VALUES.has(raw)) return true;
  if (FALSE_VALUES.has(raw)) return false;

  const quoted = parseQuoted(raw);
  if (quoted !== null) return quoted;

  const num = parseNumber(raw);
  if (num !== null) return num;

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

interface ScanState {
  ch: string;
  index: number;
  inQuote: boolean;
}

function* scanQuoteAware(text: string): Generator<ScanState> {
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (ch === "'" && !inDouble) inSingle = !inSingle;
    else if (ch === '"' && !inSingle) inDouble = !inDouble;
    yield { ch, index: i, inQuote: inSingle || inDouble };
  }
}

function findUnquotedColon(text: string): number {
  for (const { ch, index, inQuote } of scanQuoteAware(text)) {
    if (ch === ":" && !inQuote) {
      if (index + 1 >= text.length || text[index + 1] === " ") return index;
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
  for (const { ch, index, inQuote } of scanQuoteAware(text)) {
    if (ch === " " && !inQuote && text[index + 1] === "#") {
      return text.slice(0, index).trim();
    }
  }
  return text;
}

function findFlowSplitPositions(text: string): number[] {
  const positions: number[] = [];
  let depth = 0;
  let inSingle = false;
  let inDouble = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (ch === "'" && !inDouble) inSingle = !inSingle;
    else if (ch === '"' && !inSingle) inDouble = !inDouble;
    if (inSingle || inDouble) continue;
    if (ch === "[") depth++;
    else if (ch === "]") depth--;
    else if (ch === "," && depth === 0) positions.push(i);
  }

  return positions;
}

function splitFlow(text: string): string[] {
  const positions = findFlowSplitPositions(text);
  if (positions.length === 0) return [text];

  const items: string[] = [];
  let start = 0;
  for (const pos of positions) {
    items.push(text.slice(start, pos));
    start = pos + 1;
  }
  items.push(text.slice(start));

  return items.filter((s) => s.trim() !== "");
}
