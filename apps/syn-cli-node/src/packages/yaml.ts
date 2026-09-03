/**
 * Minimal YAML subset parser — zero dependencies.
 *
 * Supports: maps, lists, plain and quoted strings on a single line, block
 * scalars introduced by a bare `|` or `>`, numbers, booleans, null. Enough for
 * workflow.yaml and syntropic137.yaml files.
 *
 * Does NOT support: quoted scalars spanning more than one line, block scalars
 * with a chomping or indentation indicator (`|-`, `>-`, `>2`), anchors,
 * aliases, tags, flow sequences/maps on multiple lines, complex keys, merge
 * keys.
 *
 * The previous version of this list said "multiline" without qualification,
 * which is what #1056 was really about: the parser did not support a wrapped
 * quoted scalar and did not say so, it just stopped reading and returned what
 * it had. Anything in the second list now raises. This is a strict subset of
 * YAML, so a document it accepts parses identically under a real YAML loader —
 * that equivalence is the point, since the API loads these same bytes with
 * PyYAML. Widening the first list is fine; letting the two drift apart in
 * silence is not.
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
  const { value, nextLine } = parseNode(lines, 0, -1);
  assertFullyConsumed(lines, nextLine);
  return value;
}

/**
 * Fail closed on anything this parser cannot place.
 *
 * Every container loop here stops at the first line whose indent it does not
 * recognise, and that stop propagates all the way up to the document. Handing
 * back the partial document at that point is the defect behind #1056: a
 * workflow package whose `phases:` block had been discarded still parsed
 * "successfully", so `syn workflow validate` called it valid with zero phases
 * and every per-phase content rule passed vacuously.
 *
 * So leftover input means the document was not fully understood, whatever the
 * construct that tripped it. Refusing the whole document closes that class
 * rather than the one trigger, and keeps the zero-dependency choice intact.
 */
function assertFullyConsumed(lines: string[], nextLine: number): void {
  const i = skipBlanksAndComments(lines, nextLine);
  if (i >= lines.length) return;
  throw new Error(
    `YAML line ${i + 1}: unsupported construct \u2014 parsing stopped here, ` +
      `which would discard the rest of the document. Got: ${lines[i]!.trim()}`,
  );
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

  return { value: parseInlineValue(afterColon, i), nextLine: i + 1 };
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

  return { value: parseInlineValue(afterDash, i), nextLine: i + 1 };
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

function parseInlineValue(raw: string, lineNo: number): YamlValue {
  const value = stripInlineComment(raw);

  if (value.startsWith("[") && value.endsWith("]")) {
    const inner = value.slice(1, -1).trim();
    if (inner === "") return [];
    return splitFlow(inner).map((item) => parseScalar(item.trim()));
  }

  assertQuoteClosed(value, lineNo);
  return parseScalar(value);
}

/**
 * Reject a quoted scalar that opens on one line and closes on another.
 *
 * `assertFullyConsumed` already catches the common shape of this, because the
 * continuation line is indented past the map and so ends the document early.
 * It cannot catch the one where the wrapped scalar is the LAST entry: nothing
 * is left over, and `parseScalar` quietly keeps the fragment complete with its
 * dangling quote (`description: 'oops` became the string `'oops`). Same defect
 * as #1056 — an unsupported construct accepted as data — so it is refused in
 * the same breath, and this is where the offending line is still known.
 */
function assertQuoteClosed(value: string, lineNo: number): void {
  const quote = value[0];
  if (quote !== "'" && quote !== '"') return;
  if (value.length > 1 && value.endsWith(quote)) return;
  throw new Error(
    `YAML line ${lineNo + 1}: quoted string is never closed on this line. ` +
      `Multi-line quoted scalars are not supported \u2014 put the value on one ` +
      `line, or use a block scalar (| or >). Got: ${value}`,
  );
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

const QUOTE_CHARS = new Set(["'", '"']);

function toggleQuote(current: string, ch: string): string {
  if (current === "") return QUOTE_CHARS.has(ch) ? ch : "";
  return ch === current ? "" : current;
}

function buildQuoteMask(text: string): boolean[] {
  const mask = new Array<boolean>(text.length);
  let quote = "";
  for (let i = 0; i < text.length; i++) {
    quote = toggleQuote(quote, text[i]!);
    mask[i] = quote !== "";
  }
  return mask;
}

function findUnquotedColon(text: string): number {
  const mask = buildQuoteMask(text);
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== ":" || mask[i]) continue;
    if (i + 1 >= text.length || text[i + 1] === " ") return i;
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
  const mask = buildQuoteMask(text);
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== " " || mask[i]) continue;
    if (text[i + 1] === "#") return text.slice(0, i).trim();
  }
  return text;
}

const DEPTH_CHANGE: Record<string, number> = { "[": 1, "]": -1 };

function buildDepthMap(text: string, mask: boolean[]): Int8Array {
  const depths = new Int8Array(text.length);
  let depth = 0;
  for (let i = 0; i < text.length; i++) {
    if (!mask[i]) depth += DEPTH_CHANGE[text[i]!] ?? 0;
    depths[i] = depth;
  }
  return depths;
}

function splitFlow(text: string): string[] {
  const mask = buildQuoteMask(text);
  const depths = buildDepthMap(text, mask);
  const items: string[] = [];
  let start = 0;

  for (let i = 0; i < text.length; i++) {
    if (text[i] === "," && !mask[i] && depths[i] === 0) {
      items.push(text.slice(start, i));
      start = i + 1;
    }
  }

  const last = text.slice(start);
  if (last.trim()) items.push(last);
  return items;
}
