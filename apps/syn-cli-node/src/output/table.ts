import { BOLD, DIM, stripAnsi, style } from "./ansi.js";

export interface ColumnDef {
  name: string;
  align?: "left" | "right";
  maxWidth?: number;
  style?: string;
}

export class Table {
  private readonly columns: ColumnDef[] = [];
  private readonly rows: string[][] = [];
  private readonly title: string | undefined;

  constructor(options?: { title?: string }) {
    this.title = options?.title;
  }

  addColumn(name: string, options?: Omit<ColumnDef, "name">): this {
    this.columns.push({ name, ...options });
    return this;
  }

  addRow(...values: string[]): this {
    this.rows.push(values);
    return this;
  }

  render(): string {
    const widths = this.columns.map((col, i) => {
      const headerLen = stripAnsi(col.name).length;
      const cellLens = this.rows.map((row) =>
        stripAnsi(row[i] ?? "").length,
      );
      const maxCell = cellLens.length > 0 ? Math.max(...cellLens) : 0;
      const natural = Math.max(headerLen, maxCell);
      return col.maxWidth !== undefined ? Math.min(natural, col.maxWidth) : natural;
    });

    const lines: string[] = [];

    if (this.title) {
      lines.push(style(this.title, BOLD));
    }

    // Header
    const header = this.columns
      .map((col, i) => pad(style(col.name, BOLD), widths[i]!, col.align))
      .join("  ");
    lines.push(header);

    // Separator
    const sep = widths.map((w) => "─".repeat(w)).join("  ");
    lines.push(style(sep, DIM));

    // Rows
    for (const row of this.rows) {
      const cells = this.columns.map((col, i) => {
        const raw = row[i] ?? "";
        const truncated = truncate(raw, widths[i]!);
        const styled = col.style ? style(truncated, col.style) : truncated;
        return pad(styled, widths[i]!, col.align);
      });
      lines.push(cells.join("  "));
    }

    return lines.join("\n");
  }

  print(): void {
    process.stdout.write(this.render() + "\n");
  }
}

function truncate(text: string, maxWidth: number): string {
  const visible = stripAnsi(text);
  if (visible.length <= maxWidth) return text;
  return visible.slice(0, maxWidth - 1) + "\u2026";
}

function pad(text: string, width: number, align?: "left" | "right"): string {
  const visible = stripAnsi(text).length;
  const diff = width - visible;
  if (diff <= 0) return text;
  const spaces = " ".repeat(diff);
  return align === "right" ? spaces + text : text + spaces;
}
