export const RESET = "\x1b[0m";
export const BOLD = "\x1b[1m";
export const DIM = "\x1b[2m";
export const RED = "\x1b[31m";
export const GREEN = "\x1b[32m";
export const YELLOW = "\x1b[33m";
export const BLUE = "\x1b[34m";
export const MAGENTA = "\x1b[35m";
export const CYAN = "\x1b[36m";

const ANSI_REGEX = /\x1b\[[0-9;]*m/g;

export function isColorEnabled(): boolean {
  if (process.env["NO_COLOR"] !== undefined) return false;
  return process.stdout.isTTY === true;
}

export function style(text: string, ...codes: string[]): string {
  if (!isColorEnabled()) return text;
  return codes.join("") + text + RESET;
}

export function stripAnsi(text: string): string {
  return text.replace(ANSI_REGEX, "");
}
