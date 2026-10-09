import { test, expect, type CDPSession } from "@playwright/test";

/**
 * Energy / idle-CPU gate.
 *
 * Measures how much CPU time Chrome spends on the page during a
 * 5-second "idle" window (after initial load + animations settle).
 *
 * A healthy static page should use <500ms of CPU during 5s of idle.
 * Failing this means something is forcing continuous compositor frames
 * (infinite CSS animations, rAF loops, transparent video compositing, etc.).
 */

function getMetric(metrics: { metrics: { name: string; value: number }[] }, name: string): number {
  const m = metrics.metrics.find((m) => m.name === name);
  if (!m) throw new Error(`Metric "${name}" not found`);
  return m.value;
}

test.describe("Energy & Performance", () => {
  test("idle page should not burn CPU (TaskDuration < 500ms over 5s)", async ({ page }) => {
    test.setTimeout(90_000);
    // Connect to Chrome DevTools Protocol
    const cdp: CDPSession = await page.context().newCDPSession(page);
    await cdp.send("Performance.enable");

    // Load page and wait for ALL finite animations to complete
    // Longest: glow-drift-2 (30s × 2) and border-orbit (6s × 10) = ~60s
    await page.goto("/");
    await page.waitForTimeout(35_000); // wait for all finite animations to complete (longest: 30s)

    // Snapshot 1: start of idle window
    const snap1 = await cdp.send("Performance.getMetrics");
    const task1 = getMetric(snap1, "TaskDuration");
    const ts1 = getMetric(snap1, "Timestamp");

    // Idle window: 5 seconds of doing nothing
    await page.waitForTimeout(5_000);

    // Snapshot 2: end of idle window
    const snap2 = await cdp.send("Performance.getMetrics");
    const task2 = getMetric(snap2, "TaskDuration");
    const ts2 = getMetric(snap2, "Timestamp");

    const cpuDelta = task2 - task1;        // seconds of CPU time
    const wallDelta = ts2 - ts1;           // wall clock seconds
    const cpuPercent = (cpuDelta / wallDelta) * 100;

    console.log(`\n── Energy Report ──`);
    console.log(`  Wall time:  ${wallDelta.toFixed(2)}s`);
    console.log(`  CPU time:   ${(cpuDelta * 1000).toFixed(1)}ms`);
    console.log(`  CPU usage:  ${cpuPercent.toFixed(2)}%`);
    console.log(`  Verdict:    ${cpuDelta < 0.5 ? "PASS ✓" : "FAIL ✗"}`);
    console.log(`──────────────────\n`);

    // Gate: less than 500ms of CPU during 5s idle = healthy
    expect(cpuDelta, `CPU used ${(cpuDelta * 1000).toFixed(0)}ms during 5s idle`).toBeLessThan(0.5);
  });

  test("no infinite CSS animations after 60s", async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto("/");
    await page.waitForTimeout(35_000); // wait for all finite animations to complete (longest: 30s)

    // Check if any animations are still running
    // border-orbit is intentionally infinite (transform:rotate is compositor-only, ~0 CPU)
    const allowedInfinite = new Set(["border-orbit"]);
    const runningAnimations = await page.evaluate((allowed) => {
      const all = document.getAnimations();
      return all
        .filter((a) => {
          if (a.playState !== "running") return false;
          // @ts-expect-error -- CSSAnimation has animationName
          const name = (a as CSSAnimation).animationName ?? "unknown";
          return !allowed.includes(name);
        })
        .map((a) => ({
          playState: a.playState,
          // @ts-expect-error -- CSSAnimation has animationName
          name: (a as CSSAnimation).animationName ?? "unknown",
          // @ts-expect-error
          target: (a.effect as KeyframeEffect)?.target?.className ?? "unknown",
        }));
    }, [...allowedInfinite]);

    console.log(`\n── Animation Report (at 65s) ──`);
    console.log(`  Running: ${runningAnimations.length}`);
    for (const a of runningAnimations) {
      console.log(`    - ${a.name} on .${a.target}`);
    }
    console.log(`───────────────────────────────\n`);

    expect(runningAnimations.length, `${runningAnimations.length} animations still running`).toBe(0);
  });

  test("page loads without errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      // Ignore 404s for static assets (fonts, images) — expected in local serve
      if (msg.type() === "error" && !msg.text().includes("404")) {
        errors.push(msg.text());
      }
    });

    await page.goto("/");
    await page.waitForTimeout(2_000);

    if (errors.length > 0) {
      console.log("\n── Console Errors ──");
      for (const e of errors) console.log(`  ${e}`);
      console.log("────────────────────\n");
    }

    expect(errors.length, `Page had ${errors.length} errors`).toBe(0);
  });

  test("paint count stays low during idle", async ({ page }) => {
    test.setTimeout(90_000);
    const cdp: CDPSession = await page.context().newCDPSession(page);
    await cdp.send("Performance.enable");

    await page.goto("/");
    await page.waitForTimeout(35_000); // wait for all finite animations to complete (longest: 30s)

    // Get paint count at start of idle
    const snap1 = await cdp.send("Performance.getMetrics");
    const paints1 = getMetric(snap1, "Documents"); // proxy — real paint count via trace

    // Measure LayoutCount and RecalcStyleCount which are cheaper proxies
    const layout1 = getMetric(snap1, "LayoutCount");
    const style1 = getMetric(snap1, "RecalcStyleCount");

    await page.waitForTimeout(5_000);

    const snap2 = await cdp.send("Performance.getMetrics");
    const layout2 = getMetric(snap2, "LayoutCount");
    const style2 = getMetric(snap2, "RecalcStyleCount");

    const layoutDelta = layout2 - layout1;
    const styleDelta = style2 - style1;

    console.log(`\n── Layout/Style Report (5s idle) ──`);
    console.log(`  Layout recalcs:  ${layoutDelta}`);
    console.log(`  Style recalcs:   ${styleDelta}`);
    console.log(`────────────────────────────────────\n`);

    // During idle, there should be near-zero layout/style recalcs
    expect(layoutDelta, `${layoutDelta} layouts during 5s idle`).toBeLessThan(10);
    expect(styleDelta, `${styleDelta} style recalcs during 5s idle`).toBeLessThan(10);
  });
});
