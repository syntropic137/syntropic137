import { describe, expect, it } from "vitest";
import {
  formatCost,
  formatDuration,
  formatStatus,
  formatTimestamp,
  formatTokens,
  statusStyle,
} from "../../src/output/format.js";

describe("formatCost", () => {
  it("formats small values with 4 decimals", () => {
    expect(formatCost(0.001)).toBe("$0.0010");
    expect(formatCost(0.0042)).toBe("$0.0042");
    expect(formatCost(0)).toBe("$0.0000");
  });

  it("formats larger values with 2 decimals", () => {
    expect(formatCost(1.5)).toBe("$1.50");
    expect(formatCost(0.01)).toBe("$0.01");
    expect(formatCost(99.99)).toBe("$99.99");
  });

  it("accepts string input", () => {
    expect(formatCost("0.0042")).toBe("$0.0042");
    expect(formatCost("1.5")).toBe("$1.50");
  });
});

describe("formatTokens", () => {
  it("formats millions", () => {
    expect(formatTokens(1_200_000)).toBe("1.2M");
    expect(formatTokens(1_000_000)).toBe("1.0M");
  });

  it("formats thousands", () => {
    expect(formatTokens(5_300)).toBe("5.3K");
    expect(formatTokens(1_000)).toBe("1.0K");
  });

  it("returns raw number for small values", () => {
    expect(formatTokens(500)).toBe("500");
    expect(formatTokens(0)).toBe("0");
  });
});

describe("formatDuration", () => {
  it("formats milliseconds", () => {
    expect(formatDuration(500)).toBe("500ms");
    expect(formatDuration(0)).toBe("0ms");
  });

  it("formats seconds", () => {
    expect(formatDuration(2500)).toBe("2.5s");
    expect(formatDuration(1000)).toBe("1.0s");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(330_000)).toBe("5m 30s");
    expect(formatDuration(120_000)).toBe("2m");
  });

  it("formats hours and minutes", () => {
    expect(formatDuration(5_400_000)).toBe("1h 30m");
    expect(formatDuration(3_600_000)).toBe("1h");
  });
});

describe("formatTimestamp", () => {
  it("returns dash for null/undefined", () => {
    expect(formatTimestamp(null)).toBe("-");
    expect(formatTimestamp(undefined)).toBe("-");
  });

  it("returns dash for empty string", () => {
    expect(formatTimestamp("")).toBe("-");
  });

  it("formats valid ISO timestamp", () => {
    const result = formatTimestamp("2026-03-16T14:30:00Z");
    expect(result).toMatch(/Mar/);
    expect(result).toMatch(/16/);
  });

  it("returns original string for invalid date", () => {
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });
});

describe("statusStyle", () => {
  it("returns color codes for known statuses", () => {
    expect(statusStyle("active")).not.toBe("");
    expect(statusStyle("failed")).not.toBe("");
    expect(statusStyle("running")).not.toBe("");
  });

  it("returns empty string for unknown status", () => {
    expect(statusStyle("whatever")).toBe("");
  });
});

describe("formatStatus", () => {
  it("returns plain text for unknown status", () => {
    expect(formatStatus("whatever")).toBe("whatever");
  });
});
