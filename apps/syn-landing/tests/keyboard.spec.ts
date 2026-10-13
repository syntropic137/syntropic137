import { test, expect } from "@playwright/test";

/**
 * Keyboard access in the lower sections (design/landing-plan.md, P7): the
 * eval explorer's ranking is a radio group driven by the arrow keys, the
 * install box's Copy button works from the keyboard and says so, and the
 * comparison is a real table.
 */

const focusRing = async (el: import("@playwright/test").Locator) =>
  el.evaluate((node) => {
    const s = getComputedStyle(node);
    return { style: s.outlineStyle, width: parseFloat(s.outlineWidth) };
  });

test.describe("Keyboard", () => {
  test("eval explorer: Tab reaches the pick, arrow keys move it", async ({ page }) => {
    await page.goto("/");
    const guide = page.getByRole("link", { name: "Read the evals guide" });
    await guide.scrollIntoViewIfNeeded();

    const ranking = page.getByRole("radiogroup", { name: "Ranked by quality per dollar" });
    const radios = ranking.getByRole("radio");
    await expect(radios).toHaveCount(4);

    // Default pick: the best quality per dollar, first in rank order.
    const first = radios.nth(0);
    await expect(first).toHaveAttribute("aria-checked", "true");
    await expect(first).toContainText("claude-sonnet-5-5");

    // From the guide link, one Tab lands on the picked row (roving tabindex).
    await guide.focus();
    await page.keyboard.press("Tab");
    await expect(first).toBeFocused();
    expect(await focusRing(first)).toMatchObject({ style: "solid" });

    // ArrowDown picks and focuses the next row; the verdict follows.
    await page.keyboard.press("ArrowDown");
    const second = radios.nth(1);
    await expect(second).toHaveAttribute("aria-checked", "true");
    await expect(second).toBeFocused();
    await expect(first).toHaveAttribute("aria-checked", "false");
    await expect(page.locator("sky-eval-explorer")).toContainText("Only 4 runs so far");

    // End, Home and wrapping ArrowUp.
    await page.keyboard.press("End");
    await expect(radios.nth(3)).toBeFocused();
    await expect(radios.nth(3)).toHaveAttribute("aria-checked", "true");
    await page.keyboard.press("Home");
    await expect(first).toBeFocused();
    await page.keyboard.press("ArrowUp");
    await expect(radios.nth(3)).toBeFocused();

    // Tab leaves the group in one step.
    await page.keyboard.press("Tab");
    await expect(radios.nth(3)).not.toBeFocused();
    await expect(radios.nth(0)).not.toBeFocused();
  });

  test("install box: Copy works from the keyboard and announces it", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto("/");
    const start = page.locator("#start");
    await start.scrollIntoViewIfNeeded();
    const copy = start.getByRole("button", { name: "Copy install command" });
    await copy.focus();
    expect(await focusRing(copy)).toMatchObject({ style: "solid" });
    await page.keyboard.press("Enter");
    await expect(copy).toContainText("Copied");
    await expect(start.getByRole("status")).toHaveText("Install command copied to the clipboard");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("npx @syntropic137/setup init");
  });

  test("comparison is a table with row and column headers", async ({ page }) => {
    await page.goto("/");
    const table = page.getByRole("table", { name: /Syntropic137/ });
    await expect(table.getByRole("columnheader")).toHaveCount(3);
    await expect(table.getByRole("rowheader")).toHaveCount(5);
    await expect(table.getByRole("rowheader").first()).toHaveText("What the agent did");
  });

  test("nav: Evals and Get started reach their sections", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Site" });
    await expect(nav.getByRole("link", { name: "Evals" })).toHaveAttribute("href", "#evals");
    await expect(page.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "#start");
    await expect(page.locator("#evals")).toHaveCount(1);
    await expect(page.locator("#start")).toHaveCount(1);
  });
});
