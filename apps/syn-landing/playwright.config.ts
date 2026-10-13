import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

// LANDING_PORT picks the preview port (default 3000). PW_CHROMIUM_PATH points
// at an already-installed Chromium, as apps/syn-ui's config does, so a local
// run can reuse a cached browser instead of downloading one.
const PORT = Number(process.env.LANDING_PORT ?? 3000);
const CHROMIUM =
  process.env.PW_CHROMIUM_PATH ??
  (existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  use: {
    baseURL: `http://localhost:${PORT}`,
    headless: true,
    ...(CHROMIUM ? { launchOptions: { executablePath: CHROMIUM } } : {}),
  },
  webServer: {
    command: `pnpm exec vite preview --port ${PORT} --strictPort`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
  },
});
