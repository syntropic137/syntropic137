import { describe, expect, it } from "vitest";
import { Table } from "../../src/output/table.js";
import { stripAnsi } from "../../src/output/ansi.js";

describe("Table", () => {
  it("renders header and rows with alignment", () => {
    const table = new Table()
      .addColumn("Name")
      .addColumn("Value")
      .addRow("foo", "123")
      .addRow("barbaz", "4");

    const output = stripAnsi(table.render());
    const lines = output.split("\n");

    expect(lines.length).toBe(4); // header + separator + 2 rows
    expect(lines[0]).toContain("Name");
    expect(lines[0]).toContain("Value");
    expect(lines[1]).toContain("─");
    expect(lines[2]).toContain("foo");
    expect(lines[3]).toContain("barbaz");
  });

  it("renders title when provided", () => {
    const table = new Table({ title: "My Table" })
      .addColumn("A")
      .addRow("1");

    const output = stripAnsi(table.render());
    expect(output.split("\n")[0]).toContain("My Table");
  });

  it("truncates cells exceeding maxWidth", () => {
    const table = new Table()
      .addColumn("Name", { maxWidth: 5 })
      .addRow("toolongvalue");

    const output = stripAnsi(table.render());
    const dataLine = output.split("\n")[2]!;
    expect(dataLine).toContain("\u2026");
    expect(stripAnsi(dataLine).trim().length).toBeLessThanOrEqual(5);
  });

  it("handles empty table (header only)", () => {
    const table = new Table()
      .addColumn("A")
      .addColumn("B");

    const output = stripAnsi(table.render());
    const lines = output.split("\n");
    expect(lines.length).toBe(2); // header + separator
  });

  it("right-aligns columns", () => {
    const table = new Table()
      .addColumn("Label")
      .addColumn("Num", { align: "right" })
      .addRow("x", "42")
      .addRow("y", "7");

    const output = stripAnsi(table.render());
    const lines = output.split("\n");
    // Row with "7" should have leading space before the digit (right-aligned to width of "Num"/42)
    const row2 = lines[3]!;
    expect(row2).toContain(" 7");
  });
});
