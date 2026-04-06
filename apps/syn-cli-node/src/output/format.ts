import {
  BLUE,
  BOLD,
  DIM,
  GREEN,
  RED,
  YELLOW,
  style,
} from "./ansi.js";

export function formatCost(cost: number | string): string {
  const n = typeof cost === "string" ? Number(cost) : cost;
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
  return String(tokens);
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  if (minutes < 60) return secs ? `${minutes}m ${secs}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins ? `${hours}h ${mins}m` : `${hours}h`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "-";
  try {
    const date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

const STATUS_COLORS: Record<string, string> = {
  active: GREEN,
  completed: GREEN,
  paused: YELLOW,
  deleted: RED,
  failed: RED,
  blocked: YELLOW,
  running: BLUE,
  pending: DIM,
};

export function statusStyle(status: string): string {
  return STATUS_COLORS[status] ?? "";
}

export function formatStatus(status: string): string {
  const color = statusStyle(status);
  return color ? style(status, color) : status;
}

export function formatBreakdown(
  breakdown: Record<string, string>,
  title: string,
  valueFn?: (v: string) => string,
): string {
  const lines: string[] = [style(title, BOLD)];
  for (const [key, value] of Object.entries(breakdown)) {
    const formatted = valueFn ? valueFn(value) : value;
    lines.push(`  ${key}: ${formatted}`);
  }
  return lines.join("\n");
}
